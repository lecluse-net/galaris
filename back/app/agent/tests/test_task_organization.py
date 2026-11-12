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
async def test_answered_organization_can_wait_again_then_resume(db, monkeypatch):
    """A persisted answer must not turn another clarify decision into a terminal error."""
    from types import SimpleNamespace
    from sqlalchemy import select
    import app.messenger as messenger_module
    from app.messenger.models import Interaction
    from app.messenger.interactions import ChoiceResolution, PendingChoice
    from app.task.agent_adapter import as_agent_task

    current = task(message_platform="internal", message_group_id="synthetic-room",
                   data={"origin": "conversation"})
    db.add(current)
    await db.commit()
    current_id = current.id
    decisions = [DispatchResult(prompt="Synthetic request", decision=DispatchDecision(
        route="EXEC", organization=organization, clarification_questions=questions,
    )) for organization, questions in [
        ("clarify", ["Which collection?"]),
        ("clarify", ["Which period should the report cover?"]),
        ("tracked", []),
    ]]
    inference = AsyncMock(side_effect=decisions)
    monkeypatch.setattr(dispatcher_service, "get_dispatcher", lambda: SimpleNamespace(run=inference))
    send = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(messenger_module, "resolve_task_messaging", AsyncMock(return_value=(
        SimpleNamespace(connection_id=None, tool_id=None, send_to_room=send), "self",
    )))
    monkeypatch.setattr(planner_service, "go_next", lambda _: None)

    async def pending():
        interaction = await db.scalar(select(Interaction).where(
            Interaction.metadata_["task_id"].as_string() == str(current_id),
            Interaction.metadata_["clarification_round"].as_integer()
            == len(current.data.get("clarifications", [])),
        ))
        assert interaction is not None
        return PendingChoice(id=interaction.id, kind=interaction.kind, agent_id=None,
            tool_id=None, room_id=interaction.room_id, user_id=None, title=interaction.title,
            body=interaction.body, options=[], metadata=interaction.metadata_,
            expires_at=interaction.expires_at)

    async def answer(interaction, text):
        await planner_service._handle_clarification_answer(interaction, ChoiceResolution(
            interaction_id=interaction.id, kind=interaction.kind, option_id=None,
            metadata=interaction.metadata, text=text,
        ))

    await dispatcher_service.run(as_agent_task(current))
    assert current.status == TaskStatus.PLAN and current.paused
    first = await pending()
    await answer(first, "The equipment collection.")
    assert current.status == TaskStatus.CREATE and not current.paused

    await dispatcher_service.run(as_agent_task(current))
    assert current.status == TaskStatus.PLAN and current.paused
    second = await pending()
    assert second.id != first.id
    assert not await planner_service.request_organization_clarification(
        as_agent_task(current), ["Duplicate question?"],
    )
    await answer(first, "A stale answer must not resolve the second question.")
    assert current.status == TaskStatus.PLAN and current.paused
    assert len(current.data["clarifications"]) == 1
    await answer(second, "The previous quarter; inspection only.")
    assert current.status == TaskStatus.CREATE and not current.paused

    await dispatcher_service.run(as_agent_task(current))
    db.expire_all()
    stored = await db.get(Task, current_id)
    assert stored is not None
    assert stored.status == TaskStatus.DISPATCH and not stored.paused
    assert stored.data["organization"] == "tracked"
    assert [item["answer"] for item in stored.data["clarifications"]] == [
        "The equipment collection.", "The previous quarter; inspection only.",
    ]
    assert stored.get_execution_result() is None
    assert send.await_count == 2
    assert inference.await_count == 3
    assert len(list((await db.scalars(select(Interaction).where(
        Interaction.metadata_["task_id"].as_string() == str(current_id),
    ))).all())) == 2


@pytest.mark.asyncio
async def test_fast_followup_answer_does_not_restore_closed_wait(committed_database, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import app.messenger as messenger_module
    from app.messenger import interactions
    from app.task.agent_adapter import as_agent_task
    from core.database import get_db_session

    current = task(message_platform="internal", message_group_id="synthetic-room", data={
        "origin": "conversation", "organization_clarification": True,
        "clarifications": [{"questions": ["Which collection?"], "answer": "Equipment."}],
    })
    monkeypatch.setattr(planner_service, "go_next", lambda _: None)
    monkeypatch.setattr(messenger_module, "resolve_task_messaging",
                        AsyncMock(return_value=(SimpleNamespace(), "self")))

    async def deliver(_messenger, *, request, **kwargs):
        interaction = interactions.PendingChoice(id=uuid4(), kind=request.kind, agent_id=None,
            tool_id=None, room_id="synthetic-room", user_id=None, title=request.title,
            body=request.body, options=[], metadata=request.metadata,
            expires_at=datetime.now(timezone.utc))
        legacy = replace(interaction, id=uuid4(), metadata={"task_id": str(current.id)})
        async with get_db_session() as reply_db:
            await planner_service._handle_clarification_answer(legacy, interactions.ChoiceResolution(
                interaction_id=legacy.id, kind=legacy.kind, option_id=None,
                metadata=legacy.metadata, text="An old answer delivered before the new prompt returns.",
            ))
            stored = await reply_db.get(Task, current.id)
            assert stored.paused and len(stored.data["clarifications"]) == 1
            await planner_service._handle_clarification_answer(interaction, interactions.ChoiceResolution(
                interaction_id=interaction.id, kind=interaction.kind, option_id=None,
                metadata=interaction.metadata, text="Previous quarter; inspection only.",
            ))
        return interaction

    monkeypatch.setattr(interactions, "create_choice", deliver)
    async with get_db_session() as db:
        db.add(current)
        await db.commit()
        assert await planner_service.request_organization_clarification(as_agent_task(current), ["Which period?"])
        await db.refresh(current)
        assert current.status == TaskStatus.CREATE and not current.paused
        assert len(current.data["clarifications"]) == 2
        assert "clarification_interaction_id" not in current.data
        assert "clarification_questions" not in current.data


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_unanswered_round_never_authorizes_followup(answer):
    current = task(message_platform="internal", message_group_id="synthetic-room", data={
        "origin": "conversation", "clarifications": [{"questions": ["Which scope?"], "answer": answer}],
    })
    assert not planner_service._can_request_clarification(current, allow_followup=True)


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
