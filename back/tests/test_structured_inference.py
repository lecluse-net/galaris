import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field, Json
from sqlalchemy import select

from app.agent import AIResult
from app.llm import inference_execution as execution, inference_store as store
from app.llm.contracts import StructuredInferenceRequest
from app.llm.facade import (
    control_inference,
    inference_output_spec,
    read_inference,
    register_inference_output,
    start_inference,
    stream_inference,
)
from app.llm.models import LLMCall, LLMInference
from app.llm.structured_service import StructuredOutputRetry
from tests import test_inference_lifecycle as lifecycle

runtime = lifecycle.runtime
state = lifecycle.state


class Decision(BaseModel):
    count: int = Field(ge=1)


def validate_decision(value: Decision) -> Decision:
    if value.count < 3:
        raise StructuredOutputRetry("At least three entries are needed.")
    return value


@pytest.fixture
def output_contract():
    key = f"tests.decision.{uuid4()}/v1"
    register_inference_output(key, Decision, validator=validate_decision)
    return key


def request_for(llm, key, *, mode="tool", retries=2):
    return StructuredInferenceRequest(
        llm_id=llm.id, prompt="Count entries.", system_prompt="Return a decision.",
        purpose="lab.mechanism_run", parameters={"temperature": 0.2, "max_tokens": 256},
        reasoning_effort="low", count_tokens_before_request=False,
        output=inference_output_spec(key, mode=mode), output_retries=retries,
    )


@pytest.mark.asyncio
async def test_output_tool_name_fragments_still_form_one_message(runtime, output_contract):
    _, llm, requests, mode = runtime
    mode.update(structured=True, outputs=['{"count":3}'], split_tool_name=True)
    key = await start_inference(request_for(llm, output_contract))
    completed = await state(key, "completed")
    tools = [message for message in completed.attempts[-1].result.messages
             if message.tool_call_external_id]
    assert len(tools) == 1
    assert tools[0].tool_name == requests[0]["tools"][0]["function"]["name"]
    assert tools[0].tool_arguments == {"count": 3}


@pytest.mark.asyncio
async def test_typed_adapter_preserves_pydantic_aliases_and_json_fields(runtime):
    class Payload(BaseModel):
        label: str = Field(alias="name")
        values: Json[list[int]]

    _, llm, _, mode = runtime
    key = f"tests.payload.{uuid4()}/v1"
    register_inference_output(key, Payload)
    mode.update(structured=True, outputs=[json.dumps({"name": "entries", "values": "[1,2]"})])
    inference = await execution.run_structured(request_for(llm, key), Payload)
    assert inference.output.label == "entries"
    assert inference.output.values == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("output_mode", ["tool", "prompted"])
@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_structured_validation_retries_keep_stream_transcript_and_cost(
    runtime, output_contract, output_mode, protocol
):
    db, llm, requests, mode = runtime
    if protocol == "responses":
        llm.provider.base_url = "https://api.openai.com/v1"
        await db.commit()
    mode.update(structured=True, outputs=['{"count":0}', '{"count":2}', '{"count":3}'])
    request = request_for(llm, output_contract, mode=output_mode)
    result = await execution.run_structured(request, Decision)
    assert result.output == Decision(count=3)
    key = await db.scalar(select(LLMInference.id))
    snapshot = await read_inference(key)
    assert snapshot.request == request
    assert snapshot.status == "completed"
    events = [event async for event in stream_inference(key)]
    assert events[-1].kind == "result"
    assert sum(event.kind == "result" for event in events) == 1
    terminal = events[-1].result
    assert terminal.structured_output == {"count": 3}
    assert json.loads(terminal.result) == {"count": 3}
    assert len(requests) == 3
    assert all(request["stream"] is True for request in requests)
    assert all(bool(request.get("tools")) == (output_mode == "tool") for request in requests)
    assert "At least three entries" in json.dumps(requests[-1])
    reconstructed = AIResult(prompt="")
    for event in events:
        if event.message is not None:
            reconstructed.add_message(event.message)
    assert reconstructed.messages == terminal.messages
    assert len(terminal.messages) == 6  # One thinking and one output block per SDK request.
    if output_mode == "tool":
        tools = [message for message in terminal.messages if message.tool_call_external_id]
        assert [message.tool_arguments for message in tools] == [
            {"count": 0}, {"count": 2}, {"count": 3}
        ]
        assert len({message.stream_id for message in tools}) == 3
        assert result.messages[-1].parts[0].part_kind == "tool-return"
    calls = list(await db.scalars(select(LLMCall)))
    assert len(calls) == 3
    assert {call.reasoning_effort for call in calls} == {"low"}
    assert result.cost == snapshot.cost == pytest.approx(sum(call.cost for call in calls))
    assert terminal.usage.requests == 3
    assert (await read_inference(key)).attempts[-1].result == terminal
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("output_mode", ["tool", "prompted"])
async def test_invalid_output_is_a_failed_terminal_without_validated_data(
    runtime, output_contract, output_mode
):
    _, llm, requests, mode = runtime
    mode.update(structured=True, outputs=["not JSON"])
    key = await start_inference(request_for(llm, output_contract, mode=output_mode, retries=0))
    events = [event async for event in stream_inference(key)]
    assert len(requests) == 1
    assert events[-1].result.success is False
    assert events[-1].result.structured_output is None
    assert (await read_inference(key)).status == "failed"
    assert sum(event.kind == "result" for event in events) == 1
    assert any(message.content == "not JSON" for message in events[-1].result.messages)


@pytest.mark.asyncio
async def test_structured_pause_restart_resume_and_force_replay_keep_original_history(
    runtime, output_contract
):
    _, llm, requests, mode = runtime
    mode.update(structured=True, outputs=['{"count":3}'] * 4, tool_gate=asyncio.Event())
    key = await start_inference(request_for(llm, output_contract))
    stream = stream_inference(key)
    async with asyncio.timeout(10):
        async for event in stream:
            if event.message and event.message.tool_call_external_id:
                assert event.message.content == ""
                break
    await control_inference(key, "pause")
    paused = await state(key, "paused")
    assert paused.attempts[-1].result.structured_output is None
    assert (await anext(stream)).kind == "result"
    await stream.aclose()
    await execution.stop()
    mode["tool_gate"].set()
    await control_inference(key, "resume")
    completed = await state(key, "completed")
    assert completed.attempts[0] == paused.attempts[0]
    assert completed.attempts[-1].result.structured_output == {"count": 3}
    replay = await control_inference(key, "replay")
    repeated = await state(replay.replay_id, "completed")
    assert repeated.request == completed.request
    assert repeated.replay_of_id == key
    assert len(requests) == 3
    assert await read_inference(key) == completed


@pytest.mark.asyncio
@pytest.mark.parametrize("output_mode", ["tool", "prompted"])
@pytest.mark.parametrize("action", ["stop", "shutdown"])
async def test_stop_or_worker_shutdown_preserves_unvalidated_partial_output(
    runtime, output_contract, output_mode, action
):
    _, llm, requests, mode = runtime
    mode.update(structured=True, outputs=['{"count":3}'] * 2,
                partial_gate=asyncio.Event(), fragment_delay=True)
    key = await start_inference(request_for(llm, output_contract, mode=output_mode))
    stream = stream_inference(key)
    async with asyncio.timeout(10):
        async for event in stream:
            if event.message and event.message.content == '{"c':
                break
    if action == "stop":
        await control_inference(key, "stop")
    else:
        await execution.stop()
    snapshot = await state(key, "stopped" if action == "stop" else "interrupted")
    result = snapshot.attempts[-1].result
    assert result.structured_output is None and not result.success
    assert any(message.content == '{"c' for message in result.messages)
    assert (await anext(stream)).result == result
    await stream.aclose()
    assert len(requests) == 1
    mode["partial_gate"].set()
    if action == "stop":
        with pytest.raises(ValueError):
            await control_inference(key, "resume")
        replay = await control_inference(key, "replay")
        resumed_key = replay.replay_id
    else:
        await control_inference(key, "resume")
        resumed_key = key
    resumed = await state(resumed_key, "completed")
    assert resumed.attempts[-1].result.structured_output == {"count": 3}


@pytest.mark.asyncio
async def test_new_conversation_input_stops_owned_structured_inference(runtime, output_contract):
    from app.conversation import ConversationTurn, ConversationSuperseded, run_preparation

    db, llm, requests, mode = runtime
    pending = asyncio.Event()
    gate = asyncio.Event()
    mode.update(structured=True, outputs=['{"count":3}'], partial_gate=gate, fragment_delay=True)
    async def newer_input():
        return pending.is_set()
    turn = ConversationTurn(room_id=uuid4(), round_id=uuid4(), agent_id=1,
        language="fr", objective="Count", messages=(), should_interrupt=newer_input)
    owner = asyncio.create_task(run_preparation(turn, lambda: execution.run_structured(
        request_for(llm, output_contract), Decision,
    )))
    stream = None
    try:
        async with asyncio.timeout(10):
            key = None
            while key is None:
                key = await db.scalar(select(LLMInference.id))
                await asyncio.sleep(0)
            stream = stream_inference(key)
            async for event in stream:
                if event.message and event.message.content == '{"c':
                    break
            pending.set()
            with pytest.raises(ConversationSuperseded):
                await owner
        snapshot = await read_inference(key)
        assert snapshot.status == "stopped"
        assert snapshot.attempts[-1].result.structured_output is None
        assert len(requests) == 1
        assert not gate.is_set()
    finally:
        owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
        if stream is not None:
            await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_schema", [False, True])
async def test_output_contract_is_checked_before_admission_and_after_restart(
    runtime, output_contract, monkeypatch, changed_schema
):
    from app.llm import output_registry

    _, llm, requests, mode = runtime
    request = request_for(llm, output_contract)
    mismatched = request.model_copy(deep=True)
    mismatched.output.json_schema = {"type": "string"}
    with pytest.raises(ValueError, match="schema changed"):
        await start_inference(mismatched)
    key = await execution.transaction(lambda: store.create(request))
    registered = output_registry._contracts[output_contract]
    if changed_schema:
        class ChangedDecision(BaseModel):
            name: str

        with pytest.raises(ValueError, match="already registered"):
            register_inference_output(output_contract, ChangedDecision)
        monkeypatch.setitem(output_registry._contracts, output_contract,
                            output_registry.OutputContract(ChangedDecision, None))
    else:
        monkeypatch.delitem(output_registry._contracts, output_contract)
    # A restarted worker never substitutes an unregistered schema with a text call.
    await execution.execute(key)
    failed = await read_inference(key)
    assert failed.status == "failed"
    assert failed.attempts[-1].result.structured_output is None
    assert ("schema changed" if changed_schema else "Unknown inference output contract") in failed.attempts[-1].result.metadata["error"]
    assert requests == []
    monkeypatch.setitem(output_registry._contracts, output_contract, registered)
    mode.update(structured=True, outputs=['{"count":3}'])
    replay = await control_inference(key, "replay")
    assert (await state(replay.replay_id, "completed")).attempts[-1].result.structured_output == {"count": 3}


@pytest.mark.asyncio
async def test_real_lab_dispatcher_preserves_decision_retries_and_accounting(runtime):
    from app.lab.mechanism_registry import evaluate_mechanism, get_mechanism
    from app.llm.facade import llm_call_accounting

    db, llm, requests, mode = runtime
    mode.update(structured=True, outputs=['{"route":"WRONG"}', '{"route":"EXEC","language":"FR"}'])
    definition = get_mechanism("dispatcher")
    with llm_call_accounting() as accounting:
        output, cost = await evaluate_mechanism(
            definition, input_data={**definition.default_input, "objective": "Répondre à Alice."},
            llm=llm,
        )
    assert output == {"route": "EXEC", "effort": "standard", "language": "fr",
                      "reasoning": ""}
    assert len(requests) == 2
    key = await db.scalar(select(LLMInference.id))
    snapshot = await read_inference(key)
    assert snapshot.status == "completed"
    assert snapshot.request.output.contract == "galaris.dispatcher.active/v3"
    assert snapshot.request.parameters == {"temperature": 0.0, "max_tokens": 256}
    assert snapshot.request.output_retries is None
    calls = list(await db.scalars(select(LLMCall)))
    assert cost == accounting.cost == snapshot.cost == pytest.approx(sum(call.cost for call in calls))
    assert all(call.inference_attempt_id is not None for call in calls)
