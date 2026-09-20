"""Briefing guarantees through the SDK, gateway and committed inference journal."""

import asyncio
import json

import pytest
from sqlalchemy import select

from app.agent import briefing_service as briefing
from app.llm import inference_execution as execution, output_registry
from app.llm.contracts import StructuredInferenceRequest
from app.llm.facade import (
    control_inference,
    inference_output_spec,
    llm_call_accounting,
    read_inference,
    start_inference,
    stream_inference,
)
from app.llm.models import LLMCall, LLMInference
from app.task.models import Task, TaskAttempt, TaskStatus
from tests import test_inference_lifecycle as lifecycle
from tests.test_dispatcher_inference import dispatch_context

runtime = lifecycle.runtime
state = lifecycle.state


async def briefing_context(db):
    context, _, task_id, attempt_id = await dispatch_context(db, "task")
    task = await db.get(Task, task_id)
    task.status = TaskStatus.BRIEFING
    task.effort = "high"
    attempt = await db.get(TaskAttempt, attempt_id)
    attempt.phase = "BRIEFING"
    await db.commit()
    context.agent = None
    context.label = task.label
    context.objective = task.objective
    context.effort = "high"
    context.messages = []
    return context, attempt_id


def draft(identifier=None):
    return {
        "result": "Vérifier les contraintes, exécuter puis contrôler le résultat.",
        "choices": [
            {
                "kind": "tool" if identifier else "other",
                "identifier": identifier or "check_result",
                "label": "Contrôle",
                "reason": "Vérifier le résultat.",
            }
        ],
    }


def contextual_request(llm, identifier, *, retries=1):
    briefing.register_briefing_output_contracts()
    return StructuredInferenceRequest(
        llm_id=llm.id,
        prompt="Préparer le travail.",
        purpose="lab.mechanism_run",
        count_tokens_before_request=False,
        output_retries=retries,
        output=inference_output_spec(
            "galaris.briefing/v1",
            context={
                "tools": [{"identifier": identifier, "label": "Resource"}],
                "processes": [],
            },
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("lab", [False, True])
@pytest.mark.parametrize("invalid", ["resource", "empty", "no_issues"])
async def test_briefing_native_retry_preserves_context_lineage_and_accounting(
    runtime, lab, invalid
):
    db, llm, requests, mode = runtime
    task, attempt_id = await briefing_context(db)
    wrong = draft("not-in-the-catalog")
    if invalid == "empty":
        wrong["choices"] = []
    if invalid == "no_issues":
        wrong = {**draft(), "result": "NO ISSUES"}
    mode.update(structured=True, outputs=[json.dumps(wrong), json.dumps(draft())])
    with llm_call_accounting() as accounting:
        result = await briefing.generate(task, llm_override=llm, record_task_trace=not lab)
    assert result.success is True
    assert result.result == draft()["result"]
    assert result.choices[0].kind == "other"
    assert len(requests) == 2
    assert all(request["stream"] and request["tools"] for request in requests)
    retry = json.dumps(requests[1]["messages"])
    assert {
        "resource": "Unknown or unavailable",
        "empty": "cannot leave choices empty",
        "no_issues": "forbidden",
    }[invalid] in retry
    key = await db.scalar(select(LLMInference.id))
    saved = await read_inference(key)
    assert saved.status == "completed"
    assert saved.request.output.contract == "galaris.briefing/v1"
    assert "tools" in saved.request.output.context
    assert saved.request.reasoning_effort == "low"
    assert saved.request.task_id == (None if lab else task.id)
    calls = list(await db.scalars(select(LLMCall)))
    assert result.cost == saved.cost == accounting.cost == pytest.approx(sum(c.cost for c in calls))
    assert all(c.task_attempt_id == (None if lab else attempt_id) for c in calls)
    assert all(c.agent_id == task.agent_id for c in calls)
    assert saved.request.purpose == ("lab.mechanism_run" if lab else "agent.briefing")
    events = [event async for event in stream_inference(key)]
    assert sum(event.kind == "result" for event in events) == 1
    assert events[-1].result.structured_output == draft()


@pytest.mark.asyncio
async def test_briefing_failure_keeps_existing_fallback_and_partial_output(runtime):
    db, llm, requests, mode = runtime
    task, _ = await briefing_context(db)
    mode.update(structured=True, outputs=[json.dumps(draft("unavailable"))] * 2)
    result = await briefing.generate(task, llm_override=llm)
    assert not result.success
    assert result.result and not result.choices
    assert len(requests) == 2
    key = await db.scalar(select(LLMInference.id))
    saved = await read_inference(key)
    assert saved.status == "failed"
    assert saved.attempts[-1].result.messages
    assert saved.attempts[-1].result.structured_output is None


@pytest.mark.asyncio
async def test_contextual_validation_survives_pause_worker_restart_and_replay(runtime, monkeypatch):
    _, llm, requests, mode = runtime
    mode.update(structured=True, gate=asyncio.Event(), outputs=[json.dumps(draft("allowed"))])
    request = contextual_request(llm, "allowed")
    key = await start_inference(request)
    stream = stream_inference(key)
    assert (await asyncio.wait_for(anext(stream), 10)).message.content == "Je réfléchis."
    await control_inference(key, "pause")
    paused = await state(key, "paused")
    await stream.aclose()
    await execution.stop()
    monkeypatch.delitem(output_registry._contracts, "galaris.briefing/v1")
    briefing.register_briefing_output_contracts()
    mode.update(
        outputs=[
            json.dumps(draft("allowed")),
            json.dumps(draft("new-resource")),
            json.dumps(draft("allowed")),
            json.dumps(draft("allowed")),
        ]
    )
    mode["gate"].set()
    await control_inference(key, "resume")
    completed = await state(key, "completed")
    assert completed.attempts[0] == paused.attempts[0]
    assert completed.request.output.context == request.output.context
    assert completed.attempts[-1].result.structured_output == draft("allowed")
    assert len(requests) == 3
    assert "new-resource" in json.dumps(requests[-1]["messages"])
    replay = await control_inference(key, "replay")
    repeated = await state(replay.replay_id, "completed")
    assert repeated.request == completed.request
    assert repeated.attempts[-1].result.structured_output == draft("allowed")
    assert await read_inference(key) == completed


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_validation_context(runtime):
    _, llm, requests, mode = runtime
    mode.update(
        structured=True,
        concurrent=True,
        gate=asyncio.Event(),
        outputs=[json.dumps(draft("one"))] * 2,
    )
    first = await start_inference(contextual_request(llm, "one", retries=0))
    second = await start_inference(contextual_request(llm, "two", retries=0))
    async with asyncio.timeout(10):
        while len(requests) < 2:
            await asyncio.sleep(0.02)
        mode["gate"].set()
        results = await asyncio.gather(
            _terminal(first),
            _terminal(second),
        )
    assert results[0].success is True
    assert results[1].success is False
    assert (await read_inference(second)).request.output.context["tools"][0]["identifier"] == "two"


async def _terminal(key):
    return [event async for event in stream_inference(key)][-1].result


@pytest.mark.asyncio
async def test_malformed_validation_context_is_rejected_before_admission(runtime):
    db, llm, requests, _ = runtime
    request = contextual_request(llm, "one")
    request.output.context = {"tools": "invalid", "processes": []}
    with pytest.raises(ValueError):
        await start_inference(request)
    assert requests == []
    assert await db.scalar(select(LLMInference.id)) is None


@pytest.mark.asyncio
async def test_cancelling_briefing_stops_the_inference_and_preserves_fragments(runtime):
    db, llm, requests, mode = runtime
    task, _ = await briefing_context(db)
    mode.update(structured=True, outputs=[json.dumps(draft())], gate=asyncio.Event())
    consumer = asyncio.create_task(briefing.generate(task, llm_override=llm))
    async with asyncio.timeout(10):
        while not (key := await db.scalar(select(LLMInference.id))):
            await asyncio.sleep(0.02)
        stream = stream_inference(key)
        assert (await anext(stream)).message.content == "Je réfléchis."
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        tail = [event async for event in stream]
    saved = await read_inference(key)
    assert saved.status == "stopped"
    assert tail[-1].result.success is False
    assert saved.attempts[-1].result.messages[0].content == "Je réfléchis."
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_lab_briefing_preserves_its_schema_retry_and_resource_catalog(runtime, monkeypatch):
    from app.lab import mechanism_registry as lab
    from app.lab.contracts import resolve_input

    db, llm, requests, mode = runtime
    definition = lab.get_mechanism("briefing")
    _, inputs = resolve_input(
        "briefing",
        {"variable_value": "Préparer le travail."},
        {"resources": [{"kind": "tool", "identifier": "allowed", "label": "Resource"}]},
    )
    mode.update(
        structured=True,
        outputs=[
            json.dumps(draft("unknown")),
            json.dumps(draft("allowed")),
            json.dumps(draft("allowed")),
        ],
    )
    with llm_call_accounting() as accounting:
        output, cost = await lab.evaluate_mechanism(definition, input_data=inputs, llm=llm)
    assert output == lab.BriefingEvaluationOutput.model_validate(draft("allowed")).model_dump(
        mode="json"
    )
    assert len(requests) == 2
    key = await db.scalar(select(LLMInference.id))
    saved = await read_inference(key)
    assert saved.request.output.context == {"resources": inputs["resources"]}
    assert saved.request.output.json_schema == lab.BriefingEvaluationOutput.model_json_schema()
    assert saved.request.model_field == "text_high_llm_id"
    assert saved.request.output_retries == 1
    assert saved.cost == accounting.cost == cost
    await execution.stop()
    monkeypatch.delitem(output_registry._contracts, "galaris.lab.briefing/v1")
    lab.register_inference_output_contracts()
    replay = await control_inference(key, "replay")
    repeated = await state(replay.replay_id, "completed")
    assert repeated.attempts[-1].result.structured_output == output
