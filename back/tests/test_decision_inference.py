"""Decisions cross the real durable lifecycle and DB; only HTTP is replaced."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.llm import LLM, LLMProvider
from app.llm.contracts import DecisionInferenceRequest
from app.llm.decision_contracts import ChoiceQuestion
from app.llm.facade import control_inference, read_inference, run_decision, start_inference, stream_inference
from app.llm.models import LLMCall
from tests import test_inference_lifecycle as lifecycle

runtime = lifecycle.runtime
HttpClient = httpx.AsyncClient


@pytest_asyncio.fixture
async def decisions(runtime, monkeypatch):
    db, text_model, text_requests, text_mode = runtime
    connection = LLMProvider(name=f"decision-{uuid4()}", catalog_code="openrouter",
                             base_url="https://openrouter.ai/api/v1", is_active=True,
                             provider_type="openai_compatible")
    db.add(connection)
    await db.flush()
    llm = LLM(llm_provider_id=connection.id, provider=connection, code=f"decision-{uuid4()}",
              label="Decision test", llm_name="test/decision", primary_capability="decision",
              service_capabilities=["decision"], input_text=True, output_text=False)
    db.add(llm)
    await db.commit()
    calls = []
    mode = {"status": 200, "choice": "EXEC:high", "gate": None}
    TextClient = httpx.AsyncClient
    text_mode.update(structured=True, concurrent=True,
                     outputs=[json.dumps({"selections": {"dispatch": "EXEC:standard"}})])

    async def respond(request):
        if request.url.path != "/api/alpha/decisions":
            if mode.get("reject_text"):
                text_requests.append(json.loads(request.content))
                return httpx.Response(400, json={"error": {"message": "Protocol refused", "type": "invalid_request_error"}})
            async with TextClient() as client:
                return await client.send(request, stream=True)
        calls.append(json.loads(request.content))
        if mode.get("before_response") is not None:
            await mode["before_response"]()
        if mode["gate"] is not None:
            await mode["gate"].wait()
        answers = {"dispatch": {"type": "choice", "choice": mode["choice"],
                                "confidence": 0.75,
                                "probabilities": {"EXEC:standard": 0.25, "EXEC:high": 0.75}}}
        if "language" in calls[-1]["questions"]:
            answers["language"] = {"type": "choice", "choice": "fr"}
        if "selections" in mode:
            answers = {key: {"type": "choice", "choice": mode["selections"][key]}
                       for key in calls[-1]["questions"]}
        return httpx.Response(mode["status"], json={
            "model": "test/decision-resolved", "id": "decision-request",
            "answers": answers,
            "usage": {"input_tokens": 42, "output_tokens": 3, "cost": 0.0002},
        })

    class Client(HttpClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    request = DecisionInferenceRequest(
        llm_id=llm.id, fallback_llm_id=text_model.id, prompt="Choose the task effort.",
        purpose="lab.mechanism_run", count_tokens_before_request=False,
        questions={"dispatch": ChoiceQuestion(instructions="Choose an execution effort.", criteria={
            "EXEC:standard": "Routine task", "EXEC:high": "Difficult task",
        })},
    )
    return db, request, calls, text_requests, mode


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "invalid", 503])
async def test_decision_cost_provenance_and_single_terminal_survive_fallback(decisions, failure):
    db, request, native_calls, text_calls, mode = decisions
    if failure == "invalid":
        mode["choice"] = "PLAN:high"
    elif failure:
        mode["status"] = failure
    key = await start_inference(request)
    completed = await lifecycle.state(key, "completed")
    events = [event async for event in stream_inference(key)]
    assert sum(event.kind == "result" for event in events) == 1
    result = completed.attempts[-1].result
    decision = result.structured_output
    assert decision["source"] == ("text" if failure else "specialized")
    assert bool(decision["fallback_reason"]) == bool(failure)
    assert decision["answers"]["dispatch"]["confidence"] == (None if failure else 0.75)
    assert len(native_calls) == 1
    assert len(text_calls) == (1 if failure else 0)
    calls = list(await db.scalars(select(LLMCall).order_by(LLMCall.started_at)))
    assert len(calls) == 1 + bool(failure)
    assert completed.cost == pytest.approx(sum(call.cost for call in calls))
    if failure != 503:
        assert calls[0].cost == pytest.approx(0.0002)
        assert calls[0].input_tokens == 42
        assert calls[0].output_tokens == 3
        assert calls[0].effective_model == "test/decision-resolved"
    assert all(call.inference_attempt_id == completed.attempts[-1].id for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403])
async def test_access_denied_never_uses_text_fallback(decisions, status):
    _, request, calls, text_calls, mode = decisions
    mode["status"] = status
    with pytest.raises(RuntimeError, match="refused access|budget is exhausted"):
        await run_decision(request)
    assert len(calls) == 1
    assert text_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("specialized", [False, True])
async def test_task_profile_selects_decision_or_existing_text_path(decisions, runtime, monkeypatch, specialized):
    from dataclasses import replace
    from app.agent.contracts import DriverPipelinePolicy
    from app.agent.dispatcher import Dispatcher
    from app.agent.registry import INTERNAL_HARNESS
    from app.llm.profile_models import LlmProfile
    from app.task import task_service
    from tests.test_dispatcher_inference import dispatch_context

    db, request, calls, text_calls, _ = decisions
    _, text_model, _, text_mode = runtime
    _, _, task_id, _ = await dispatch_context(db, "task")
    task = await task_service.get_by_id(task_id)
    profile = LlmProfile(label=f"decision-profile-{uuid4()}",
                         decision_llm_id=request.llm_id if specialized else None,
                         text_low_llm_id=text_model.id)
    db.add(profile)
    await db.flush()
    task.agent.profile_id = profile.id
    await db.commit()
    spec = replace(INTERNAL_HARNESS, pipeline_policy=DriverPipelinePolicy(
        use_planner=False, use_briefing=False, uses_llm_calls=True,
        execution_efforts=frozenset({"standard", "high"}),
    ))
    # The harness is an execution boundary; exercise the real dispatcher and profile resolution.
    async def harness(self, task):
        return spec
    monkeypatch.setattr(Dispatcher, "_resolve_task_driver", harness)
    text_mode["outputs"] = [json.dumps({"route": "EXEC", "effort": "high", "language": "fr"})]
    result = await Dispatcher().run(task)
    assert result.success
    assert (result.decision.route, result.decision.effort, result.decision.language) == ("EXEC", "high", "fr")
    assert len(calls) == int(specialized)
    assert len(text_calls) == int(not specialized)
    if specialized:
        assert set(calls[0]["questions"]["dispatch"]["criteria"]) == {"EXEC:standard", "EXEC:high"}
        assert result.decision_inference["source"] == "specialized"
        assert result.cost == pytest.approx(0.0002)


@pytest.mark.asyncio
async def test_lab_runs_real_dispatcher_with_decision_candidate_and_no_hidden_fallback(decisions):
    from app.lab.mechanism_registry import evaluate_mechanism, get_mechanism

    db, request, calls, text_calls, mode = decisions
    llm = await db.get(LLM, request.llm_id)
    inputs = {"objective": "<p>Résoudre le problème de calcul.</p>",
              "pipeline_policy": {"use_planner": False, "use_briefing": False,
                                  "execution_efforts": ["standard", "high"], "uses_llm_calls": True}}
    result, cost = await evaluate_mechanism(get_mechanism("dispatcher"), input_data=inputs, llm=llm)
    assert (result["route"], result["effort"], result["language"]) == ("EXEC", "high", "fr")
    assert result["decision_inference"]["model"] == "test/decision-resolved"
    assert cost == pytest.approx(0.0002)
    mode["status"] = 503
    with pytest.raises(RuntimeError, match="503"):
        await evaluate_mechanism(get_mechanism("dispatcher"), input_data=inputs, llm=llm)
    assert len(calls) == 2
    assert text_calls == []


@pytest.mark.asyncio
async def test_stop_silent_decision_provider_never_uses_fallback(decisions):
    _, request, calls, text_calls, mode = decisions
    mode["gate"] = asyncio.Event()
    key = await start_inference(request)
    async with asyncio.timeout(10):
        while not calls:
            await asyncio.sleep(0.01)
    await control_inference(key, "stop")
    stopped = await lifecycle.state(key, "stopped")
    assert stopped.attempts[-1].result.success is False
    assert text_calls == []
    assert (await read_inference(key)).status == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("limits", [{"request_limit": 1}, {"allow_text_fallback": False}])
async def test_request_budget_or_policy_prevents_a_second_provider_call(decisions, limits):
    _, request, calls, text_calls, mode = decisions
    mode["status"] = 503
    with pytest.raises(RuntimeError, match="503"):
        await run_decision(request.model_copy(update=limits))
    assert len(calls) == 1
    assert text_calls == []


@pytest.mark.asyncio
async def test_deadline_never_extends_into_a_text_fallback(decisions):
    _, request, calls, text_calls, mode = decisions
    mode["gate"] = asyncio.Event()
    with pytest.raises(RuntimeError):
        await run_decision(request.model_copy(update={"timeout_seconds": 0.2}))
    assert len(calls) == 1
    assert text_calls == []


@pytest.mark.asyncio
async def test_resume_rejects_changed_provider_binding(decisions):
    db, request, calls, text_calls, mode = decisions
    mode["gate"] = asyncio.Event()
    key = await start_inference(request)
    async with asyncio.timeout(10):
        while not calls:
            await asyncio.sleep(0.01)
    await control_inference(key, "pause")
    await lifecycle.state(key, "paused")
    model = await db.get(LLM, request.llm_id)
    model.llm_name = "another-decision-deployment"
    await db.commit()
    await control_inference(key, "resume")
    failed = await lifecycle.state(key, "failed")
    assert "binding changed" in failed.attempts[-1].result.metadata["error"]
    assert len(calls) == 1
    assert text_calls == []


@pytest.mark.asyncio
async def test_sdk_protocol_fallback_cannot_exceed_physical_call_budget(decisions, runtime):
    db, request, calls, text_calls, mode = decisions
    _, text_model, _, _ = runtime
    text_model.provider.catalog_code = "perplexity"
    text_model.provider.base_url = "https://api.perplexity.ai/v1"
    await db.commit()
    mode.update(status=503, reject_text=True)
    with pytest.raises(RuntimeError):
        await run_decision(request)
    assert len(calls) == len(text_calls) == 1
    assert len(list(await db.scalars(select(LLMCall)))) == 2


@pytest.mark.asyncio
async def test_stop_during_text_fallback_preserves_partial_output(decisions, runtime):
    _, request, calls, text_calls, mode = decisions
    _, _, _, text_mode = runtime
    mode["status"] = 503
    text_mode["gate"] = asyncio.Event()
    key = await start_inference(request)
    stream = stream_inference(key)
    first = await asyncio.wait_for(anext(stream), 10)
    assert first.message.content == "Je réfléchis."
    await control_inference(key, "stop")
    stopped = await lifecycle.state(key, "stopped")
    assert stopped.attempts[-1].result.messages[0].content == first.message.content
    assert len(calls) == len(text_calls) == 1
    assert sum(event.kind == "result" for event in [event async for event in stream]) == 1
