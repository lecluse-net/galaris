"""Goal monitoring is exclusively one native closed choice, including failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.goal import evaluation
from app.goal.schemas import GoalDecision
from app.llm.decision_contracts import ChoiceAnswer, DecisionResult, DecisionUnavailable
from app.llm.structured_service import StructuredInferenceResult


@pytest.mark.parametrize("payload", [{}, {"action": "UNKNOWN"}, {"action": "PAUSE"},
    {"action": "STOP", "tracking_content": "<p>Unrequested synthesis.</p>"}])
def test_monitoring_accepts_only_a_closed_choice(payload):
    with pytest.raises(ValidationError):
        GoalDecision.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["CONTINUE", "STOP"])
async def test_monitoring_uses_one_native_choice_without_text_or_synthesis(monkeypatch, action):
    native = AsyncMock(return_value=StructuredInferenceResult(
        output=DecisionResult(model="synthetic-decision", answers={"action": ChoiceAnswer(choice=action)}),
        cost=0.0001, messages=[]))
    text = AsyncMock(side_effect=AssertionError("Goal monitoring must never use text inference"))
    monkeypatch.setattr(evaluation, "run_decision", native)
    monkeypatch.setattr("app.llm.structured_service.run_structured", text)
    result = await evaluation.evaluate_goal(llm=SimpleNamespace(id=42), prompt="Synthetic observed cycle.",
        system_prompt="Decide against the original criteria.", task_id=None, agent_id=None)
    assert result.output.model_dump() == {"action": action}
    assert result.cost == 0.0001
    native.assert_awaited_once()
    request = native.await_args.args[0]
    from app.goal.cycle_context import goal_judgement_runtime_instructions
    assert request.system_prompt.count(goal_judgement_runtime_instructions()) == 1
    assert request.llm_id == 42
    assert request.request_limit == 1
    assert request.allow_text_fallback is False and request.fallback_llm_id is None
    assert set(request.questions) == {"action"}
    assert set(request.questions["action"].criteria) == {"CONTINUE", "STOP"}
    text.assert_not_awaited()


@pytest.mark.asyncio
async def test_specialist_failure_does_not_use_text_fallback(monkeypatch):
    native = AsyncMock(side_effect=DecisionUnavailable("Synthetic provider outage"))
    text = AsyncMock(side_effect=AssertionError("Unexpected generative fallback"))
    monkeypatch.setattr(evaluation, "run_decision", native)
    monkeypatch.setattr("app.llm.structured_service.run_structured", text)
    with pytest.raises(DecisionUnavailable):
        await evaluation.evaluate_goal(llm=SimpleNamespace(id=42), prompt="Synthetic cycle.",
            system_prompt="Decide.", task_id=None, agent_id=None)
    native.assert_awaited_once()
    text.assert_not_awaited()
