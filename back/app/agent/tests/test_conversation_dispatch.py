"""Conversation-only advisory routing never substitutes for a durable effect."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import conversation_dispatch as routing
from app.llm.decision_contracts import ChoiceAnswer, DecisionResult
from app.llm.structured_service import StructuredInferenceResult


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setattr(routing, "resolve_agent_decision_models", AsyncMock(
        return_value=(SimpleNamespace(id=12), None, False)))
    return dict(agent=SimpleNamespace(profile_id=3), agent_id=7,
        round_id=uuid4(), run_id=uuid4(), objective="Here is the fictional code.",
        history="Assistant: What is the fictional launch code?", active_work=(),
        pending_interactions=(), load_processes=AsyncMock(return_value=()))


def decision(continuity="none", process="none"):
    return StructuredInferenceResult(output=DecisionResult(
        answers={"continuity": ChoiceAnswer(choice=continuity), "process": ChoiceAnswer(choice=process)},
        model="synthetic-decision"), cost=0.002, messages=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("forced", [False, True])
async def test_absent_decision_model_or_forced_response_skips_catalog_and_inference(monkeypatch, inputs, forced):
    resolve = AsyncMock(return_value=(None, None, False))
    infer = AsyncMock(side_effect=AssertionError("No decision model is configured"))
    monkeypatch.setattr(routing, "resolve_agent_decision_models", resolve)
    monkeypatch.setattr(routing, "run_decision", infer)
    result = await routing.analyze_conversation_work(**inputs, force_response=forced)
    assert result.continuity_status == result.process_status == "not_evaluated"
    assert result.cost == 0
    inputs["load_processes"].assert_not_awaited()
    infer.assert_not_awaited()
    if forced:
        resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", ["answer", "related"])
async def test_correlates_exact_wait_or_progress_and_independent_new_process(monkeypatch, inputs, relation):
    task_id, run_id, definition_id = uuid4(), uuid4(), 401
    task_uri = f"galaris://task/{task_id}"
    inputs.update(active_work=({"kind": "task", "task_id": str(task_id), "label": "Synthetic report",
            "operational_state": "RUNNING"},),
        pending_interactions=({"reference": "SYNTH123", "title": "Synthetic launch code",
            "body": "Which fictional code?", "run_id": str(run_id)},),
        objective="Here is the fictional code. Also launch a synthetic report.",
        load_processes=AsyncMock(return_value=({"definition_id": str(definition_id),
            "workflow_id": "synthetic-report", "label": "Synthetic report", "description": "Produce a fictional report."},)))
    choice = "interaction:SYNTH123" if relation == "answer" else f"task:{task_id}"
    infer = AsyncMock(return_value=decision(choice, str(definition_id)))
    monkeypatch.setattr(routing, "run_decision", infer)
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == result.process_status == "selected"
    assert result.continuity.relation == relation
    if relation == "answer":
        assert result.continuity.reference == "SYNTH123"
        assert result.continuity.run_id == str(run_id)
    else:
        assert result.continuity.task_uri == task_uri
    assert result.process.definition_id == definition_id
    assert result.process.workflow_id == "synthetic-report"
    request = infer.await_args.args[0]
    assert request.task_id is None
    assert request.conversation_round_id == inputs["round_id"]
    assert request.agent_run_id == inputs["run_id"]
    assert request.llm_id == 12
    assert request.allow_text_fallback is False
    assert result.cost == 0.002


@pytest.mark.asyncio
@pytest.mark.parametrize("continuity,process", [("none", "none"), ("uncertain", "none"), ("none", "uncertain")])
async def test_evaluations_have_independent_explicit_status(monkeypatch, inputs, continuity, process):
    monkeypatch.setattr(routing, "run_decision", AsyncMock(return_value=decision(continuity, process)))
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == continuity
    assert result.process_status == process
    assert result.continuity is None and result.process is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("Synthetic provider failure"), ValueError("Invalid choice")])
async def test_failed_analysis_leaves_both_decisions_to_executor(monkeypatch, inputs, failure):
    monkeypatch.setattr(routing, "run_decision", AsyncMock(side_effect=failure))
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == result.process_status == "not_evaluated"
    assert result.reason == "analysis_unavailable"


@pytest.mark.asyncio
async def test_rejects_invented_target_and_preserves_cancellation(monkeypatch, inputs):
    infer = AsyncMock(return_value=decision("invented-uuid", "none"))
    monkeypatch.setattr(routing, "run_decision", infer)
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == result.process_status == "not_evaluated"
    infer.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await routing.analyze_conversation_work(**inputs)


@pytest.mark.asyncio
async def test_unavailable_or_partial_catalog_does_not_prove_no_process(monkeypatch, inputs):
    monkeypatch.setattr(routing, "run_decision", AsyncMock(return_value=decision()))
    inputs["load_processes"] = AsyncMock(side_effect=PermissionError("Synthetic unavailable tools"))
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == "none"
    assert result.process_status == "uncertain"
    inputs["load_processes"] = AsyncMock(return_value=tuple({"definition_id": i + 1,
        "workflow_id": f"synthetic-{i}"} for i in range(201)))
    result = await routing.analyze_conversation_work(**inputs)
    assert result.process_status == "uncertain"
    inputs["active_work"] = None
    result = await routing.analyze_conversation_work(**inputs)
    assert result.continuity_status == "uncertain"


@pytest.mark.asyncio
async def test_full_context_and_configured_fallback_reach_decision_without_stopped_work(monkeypatch, inputs):
    waiting, stopped = str(uuid4()), str(uuid4())
    inputs.update(active_work=(
        {"task_id": waiting, "operational_state": "WAITING", "waits": [{"question": "Which fictional planet?"}]},
        {"task_id": stopped, "operational_state": "PAUSED", "pause_reasons": ["user"]}),
        objective="Use the attached file chat://synthetic-room/synthetic-file.")
    infer = AsyncMock(return_value=decision(f"task:{waiting}:wait:0"))
    monkeypatch.setattr(routing, "run_decision", infer)
    monkeypatch.setattr(routing, "resolve_agent_decision_models", AsyncMock(
        return_value=(SimpleNamespace(id=12), SimpleNamespace(id=13), True)))
    result = await routing.analyze_conversation_work(**inputs)
    request = infer.await_args.args[0]
    assert "chat://synthetic-room/synthetic-file" in request.prompt
    assert request.fallback_llm_id == 13 and request.allow_text_fallback is True
    assert not any(stopped in key for key in request.questions["continuity"].criteria)
    assert result.continuity.question == "Which fictional planet?"
    inputs["objective"] = "x" * 60_001
    result = await routing.analyze_conversation_work(**inputs)
    assert result.reason == "context_limit"
    assert infer.await_count == 1
