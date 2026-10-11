from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.agent import dispatcher_service, planner_service
from app.agent.contracts import DispatchDecision, DispatchResult, TaskDispatchDecision
from app.task.models import Task, TaskStatus


def task(**values):
    defaults = dict(id=uuid4(), label="Synthetic mission", objective="<p>Prepare the study.</p>",
                    status=TaskStatus.CREATE, cost=0.0, effort="standard", data={}, paused=False)
    return Task(**(defaults | values))


def test_organization_is_independent_of_route_and_effort():
    decision = TaskDispatchDecision.model_validate({"route": "EXEC", "effort": "high",
                                                    "organization": "tracked"})
    assert decision.model_dump()["organization"] == "tracked"


@pytest.mark.asyncio
@pytest.mark.parametrize("organization", ["direct", "tracked", "clarify"])
async def test_dispatch_applies_organization_without_an_extra_model_call(monkeypatch, organization):
    current = task()
    result = DispatchResult(prompt="Synthetic request", decision=DispatchDecision.model_validate(
        {"route": "EXEC", "organization": organization, "clarification_questions": ["Which scope?"]}
    ))
    inference = AsyncMock(return_value=result)
    monkeypatch.setattr(dispatcher_service, "get_dispatcher", lambda: type("Dispatcher", (), {"run": inference})())
    monkeypatch.setattr(dispatcher_service.task_port, "save", AsyncMock())
    question = AsyncMock(return_value=True)
    monkeypatch.setattr(planner_service, "_request_clarification", question)
    await dispatcher_service.run(current)
    assert inference.await_count == 1
    assert current.data["organization"] == organization
    if organization == "clarify":
        assert question.await_count == 1
        assert current.data["organization_clarification"] is True
    else:
        question.assert_not_awaited()
        assert current.status == TaskStatus.DISPATCH


@pytest.mark.asyncio
async def test_unavailable_organization_question_fails_without_execution(monkeypatch):
    current = task()
    result = DispatchResult(prompt="Synthetic request", decision=DispatchDecision.model_validate(
        {"route": "EXEC", "organization": "clarify", "clarification_questions": ["Which scope?"]}
    ))
    monkeypatch.setattr(dispatcher_service, "get_dispatcher", lambda: type("Dispatcher", (), {"run": AsyncMock(return_value=result)})())
    monkeypatch.setattr(dispatcher_service.task_port, "save", AsyncMock())
    monkeypatch.setattr(planner_service, "_request_clarification", AsyncMock(return_value=False))
    await dispatcher_service.run(current)
    assert current.status == TaskStatus.ERROR
    assert current.get_execution_result().metadata["failure_code"] == "ORGANIZATION_CLARIFICATION_REQUIRED"


@pytest.mark.asyncio
async def test_organization_timeout_never_starts_work(monkeypatch):
    current = task(status=TaskStatus.PLAN, paused=True, data={
        "organization_clarification": True, "clarification_questions": ["Which scope?"],
        "clarification_deadline": "2000-01-01T00:00:00+00:00", "pause_reasons": ["clarify"],
    })
    monkeypatch.setattr(planner_service.task_port, "list_planner_clarification_candidates", AsyncMock(return_value=[current]))
    monkeypatch.setattr(planner_service.task_port, "is_held_by_user", lambda _: False)
    monkeypatch.setattr(planner_service.task_port, "save", AsyncMock())
    monkeypatch.setattr(planner_service, "_notify_legacy_failure", AsyncMock())
    monkeypatch.setattr(planner_service, "resume_parent", AsyncMock())
    from app.agent import observers
    monkeypatch.setattr(observers, "notify_terminal_task", AsyncMock())
    await planner_service.resume_expired_clarifications()
    assert current.status == TaskStatus.ERROR
    assert current.data["clarifications"][0]["answer"] is None


@pytest.mark.asyncio
async def test_answer_reassesses_organization_and_ignores_late_replies(monkeypatch):
    from app.messenger.interactions import ChoiceResolution, PendingChoice
    from datetime import datetime, timezone
    current = task(status=TaskStatus.PLAN, paused=True, data={
        "organization_clarification": True, "clarification_questions": ["Which scope?"],
        "pause_reasons": ["clarify"],
    })
    monkeypatch.setattr(planner_service.task_port, "get_by_id", AsyncMock(return_value=current))
    saved = AsyncMock()
    monkeypatch.setattr(planner_service.task_port, "save", saved)
    schedule = lambda _: None
    monkeypatch.setattr(planner_service, "go_next", schedule)
    interaction = PendingChoice(id=uuid4(), kind="planner_clarification", agent_id=1,
        tool_id=None, room_id="synthetic", user_id=None, title="Scope", body="Which scope?",
        options=[], metadata={"task_id": str(current.id)}, expires_at=datetime.now(timezone.utc))
    answer = ChoiceResolution(interaction_id=interaction.id, kind=interaction.kind, text="The complete collection",
                              option_id=None, metadata={})
    await planner_service._handle_clarification_answer(interaction, answer)
    assert current.status == TaskStatus.CREATE
    assert current.paused is False
    assert current.data["clarifications"][0]["answer"] == "The complete collection"
    assert saved.await_count == 1
    await planner_service._handle_clarification_answer(interaction, answer)
    assert saved.await_count == 1


@pytest.mark.asyncio
async def test_inline_workflow_cannot_execute_while_organization_is_unclear(monkeypatch):
    from app.agent.workflow import should_execute
    current = task()
    result = DispatchResult(prompt="Synthetic request", decision=DispatchDecision(
        route="EXEC", organization="clarify"))
    monkeypatch.setattr(dispatcher_service, "run", AsyncMock(return_value=result))
    assert await should_execute(current) is False


@pytest.mark.asyncio
async def test_executor_receives_the_requesters_organization_answer():
    from types import SimpleNamespace
    from app.agent.executor_service import build_task_prompt
    answer = "Only inspect the Nacre account; do not inspect or change the others."
    current = SimpleNamespace(agent=None, shared_context="", last_error="", consecutive_failures=0,
        objective="<p>Inspect the accounts.</p>", data={
            "organization": "direct", "language": "en", "organization_clarification": True,
            "clarifications": [{"questions": ["Which scope?"], "answer": answer}],
        })
    prompt = await build_task_prompt(current)
    assert answer in prompt
