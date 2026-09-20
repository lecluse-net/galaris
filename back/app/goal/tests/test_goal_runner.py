from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.goal import goal_service, runner, settings_service
from app.goal.models import (
    Goal,
    GoalCycle,
    GoalCycleStatus,
    GoalCycleTrigger,
    GoalCycleTriggerKind,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)
from app.goal.schemas import (
    GoalAgentReferrerInput,
    GoalApiCreate,
    GoalCommand,
    GoalCreate,
    GoalJudgement,
    GoalMessengerReferrerInput,
    GoalProgress,
    GoalScheduleWindow,
    GoalUpdate,
)
from app.goal.tests.factories import make_goal
from app.llm.models import LLMCall
from app.llm.structured_service import StructuredInferenceResult
from app.llm.trace import infer_call_type
from app.memory import service as memory_service
from app.memory.goal_document_adapter import reconcile_goal_document_paths
from app.memory.models import MemoryItem
from app.messenger.models import MessengerUser
from app.memory.schemas import DocumentOwnerUpdate, MemoryItemUpdate, MemoryPayload
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus
from app.task import task_service
from app.tools.models import Tool
from core.user import user_service
from core.user.models import User


async def _new_agent(db) -> Agent:
    title_id = await db.scalar(select(Title.id).limit(1))
    if title_id is None:
        title = Title(label="Test", gender="M")
        db.add(title)
        await db.flush()
        title_id = title.id
    agent = Agent(
        title_id=title_id,
        code=f"goal-test-{uuid4().hex[:10]}",
        first_name="Goal",
        last_name="Tester",
        agent_driver="internal",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


def test_public_goal_contract_rejects_an_agent_referrer() -> None:
    with pytest.raises(ValidationError):
        GoalApiCreate.model_validate(
            {
                "title": "Human supervision only",
                "description": "An agent cannot supervise this Goal.",
                "agent_id": 1,
                "referrer": {"type": "AGENT", "agent_id": 2},
            }
        )


@pytest.fixture(autouse=True)
def _configured_goal_tracking_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most Goal scenarios assume the mandatory dedicated model is selected."""

    monkeypatch.setattr(
        goal_service,
        "get_tracking_llm",
        AsyncMock(return_value=SimpleNamespace(id=None)),
    )


def _judgement(action: str = "CONTINUE") -> GoalJudgement:
    return GoalJudgement(
        action=action,  # type: ignore[arg-type]
        reason="Useful work remains." if action == "CONTINUE" else "Objective reached.",
        progress=GoalProgress(
            changed=True,
            summary="A concrete milestone was completed.",
            evidence=["Milestone artifact"],
        ),
        tracking_content=(
            "# Goal tracking\n\n"
            "## Current state\n\nA concrete milestone was completed.\n\n"
            "## Remaining work\n\nContinue from the completed milestone."
        ),
    )


def test_next_cycle_at_is_a_minimum_delay_after_task_completion() -> None:
    finished = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc)

    assert runner.next_cycle_at(finished, 3600) == finished + timedelta(hours=1)
    assert runner.next_cycle_at(finished, 0) == finished
    assert runner.next_cycle_at(finished, -10) == finished


@pytest.mark.parametrize(
    "field_name",
    [
        "title",
        "description",
        "tracking_content",
        "agent_id",
        "referrer",
        "referrer_max_reminders",
        "schedule_enabled",
        "schedule",
    ],
)
def test_goal_update_rejects_explicit_null(field_name: str) -> None:
    with pytest.raises(ValidationError):
        GoalUpdate.model_validate({"expected_revision": 1, field_name: None})


def test_goal_create_requires_a_referrer() -> None:
    with pytest.raises(ValidationError):
        GoalCreate.model_validate(
            {
                "title": "Unowned intent",
                "description": "A Goal must always identify who assigned it.",
                "agent_id": 1,
            }
        )


def test_goal_create_defaults_to_one_human_referrer_reminder() -> None:
    data = GoalCreate.model_validate(
        {
            "title": "Ask when blocked",
            "description": "Wait safely for the person who assigned the Goal.",
            "agent_id": 1,
            "referrer": {"type": "AGENT", "agent_id": 2},
        }
    )

    assert data.referrer_max_reminders == 1
    assert data.schedule_enabled is False
    assert data.schedule == []
    with pytest.raises(ValidationError):
        GoalCreate.model_validate(
            {
                **data.model_dump(),
                "referrer_max_reminders": -1,
            }
        )


def test_goal_requires_exactly_one_automatic_trigger_mode() -> None:
    parent_goal_id = uuid4()
    data = GoalCreate.model_validate(
        {
            "title": "Parent-driven Goal",
            "description": "Wait for another Goal.",
            "agent_id": 1,
            "referrer": {"type": "AGENT", "agent_id": 2},
            "cycle_delay_seconds": None,
            "parent_goal_id": parent_goal_id,
        }
    )
    update_data = GoalUpdate.model_validate(
        {"expected_revision": 1, "cycle_delay_seconds": None}
    )

    assert data.cycle_delay_seconds is None
    assert data.parent_goal_id == parent_goal_id
    assert "cycle_delay_seconds" in update_data.model_fields_set
    assert update_data.cycle_delay_seconds is None
    with pytest.raises(ValidationError, match="exactly one automatic trigger"):
        GoalCreate.model_validate(
            {
                **data.model_dump(),
                "parent_goal_id": None,
            }
        )
    with pytest.raises(ValidationError, match="exactly one automatic trigger"):
        GoalCreate.model_validate(
            {
                **data.model_dump(),
                "cycle_delay_seconds": 3600,
            }
        )
    with pytest.raises(ValidationError, match="cannot define its own time window"):
        GoalCreate.model_validate(
            {
                **data.model_dump(),
                "schedule_enabled": True,
                "schedule": [
                    {
                        "weekdays": [0],
                        "start_time": "09:00",
                        "end_time": "17:00",
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_goal_hierarchy_rejects_cycles(db) -> None:
    owner = await _new_agent(db)
    referrer = await _new_agent(db)
    parent = await goal_service.create(
        GoalCreate(
            title="Parent",
            description="Root Goal",
            agent_id=owner.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            active=False,
        )
    )
    child = await goal_service.create(
        GoalCreate(
            title="Child",
            description="Sub-goal",
            agent_id=owner.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=None,
            parent_goal_id=parent.id,
            active=False,
        )
    )

    with pytest.raises(goal_service.GoalConflictError, match="hierarchy cycle"):
        await goal_service.update(
            parent.id,
            GoalUpdate(
                expected_revision=parent.revision,
                cycle_delay_seconds=None,
                parent_goal_id=child.id,
            ),
        )


@pytest.mark.asyncio
async def test_goal_can_switch_between_temporal_and_parent_driven_modes(db) -> None:
    owner = await _new_agent(db)
    referrer = await _new_agent(db)
    parent = await goal_service.create(
        GoalCreate(
            title="Parent",
            description="Drive the child Goal.",
            agent_id=owner.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            active=False,
        )
    )
    child = await goal_service.create(
        GoalCreate(
            title="Child",
            description="Start with a temporal trigger.",
            agent_id=owner.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=3600,
            active=False,
        )
    )

    relational = await goal_service.update(
        child.id,
        GoalUpdate(
            expected_revision=child.revision,
            cycle_delay_seconds=None,
            parent_goal_id=parent.id,
            schedule_enabled=False,
            schedule=[],
        ),
    )

    assert relational is not None
    assert relational.cycle_delay_seconds is None
    assert relational.parent_goal_id == parent.id
    assert relational.schedule_enabled is False

    temporal = await goal_service.update(
        child.id,
        GoalUpdate(
            expected_revision=relational.revision,
            cycle_delay_seconds=7200,
            parent_goal_id=None,
        ),
    )

    assert temporal is not None
    assert temporal.cycle_delay_seconds == 7200
    assert temporal.parent_goal_id is None


@pytest.mark.asyncio
async def test_completed_parent_cycle_triggers_child_cycle_once(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_agent = await _new_agent(db)
    child_agent = await _new_agent(db)
    referrer = await _new_agent(db)
    parent = await make_goal(
        title="Parent",
        description="Advance the root objective.",
        agent_id=parent_agent.id,
        referrer_type=GoalReferrerType.AGENT,
        referrer_agent_id=referrer.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.ACTIVE,
    )
    child = await make_goal(
        title="Child",
        description="Run after the parent.",
        agent_id=child_agent.id,
        referrer_type=GoalReferrerType.AGENT,
        referrer_agent_id=referrer.id,
        cycle_delay_seconds=None,
        parent_goal_id=parent.id,
        status=GoalStatus.ACTIVE,
    )
    source_task = Task(
        label="Parent cycle",
        objective="Complete one parent cycle",
        status=TaskStatus.SUCCESS,
        agent_id=parent_agent.id,
        goal=parent,
    )
    token = uuid4()
    source_cycle = GoalCycle(
        goal=parent,
        task=source_task,
        sequence=1,
        status=GoalCycleStatus.JUDGING,
        task_finished_at=datetime.now(timezone.utc),
        lease_token=token,
    )
    db.add_all([parent, child, source_task, source_cycle])
    await db.commit()
    parent_revision = parent.revision
    source_cycle_id = source_cycle.id
    child_id = child.id
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())

    await runner._finish_judgement(  # pyright: ignore[reportPrivateUsage]
        source_cycle_id,
        token,
        _judgement("CONTINUE"),
        expected_goal_revision=parent_revision,
        cost=0.0,
        llm_id=None,
    )

    trigger = await db.scalar(
        select(GoalCycleTrigger).where(
            GoalCycleTrigger.goal_id == child_id,
            GoalCycleTrigger.source_cycle_id == source_cycle_id,
        )
    )
    assert trigger is not None
    assert await runner.start_due_cycle() is True
    assert await runner.start_due_cycle() is False

    child_cycle = await db.scalar(
        select(GoalCycle).where(GoalCycle.goal_id == child_id)
    )
    assert child_cycle is not None
    assert child_cycle.trigger_kind == GoalCycleTriggerKind.RELATIONAL
    assert child_cycle.source_cycle_id == source_cycle_id
    await db.refresh(trigger)
    assert trigger.consumed_cycle_id == child_cycle.id


def test_goal_judgement_rejects_unknown_fields_and_stop_without_evidence() -> None:
    payload = _judgement("STOP").model_dump()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        GoalJudgement.model_validate(payload)

    payload = _judgement("STOP").model_dump()
    payload["progress"]["evidence"] = []
    with pytest.raises(ValidationError):
        GoalJudgement.model_validate(payload)


@pytest.mark.asyncio
async def test_goal_markdown_is_stored_in_editable_protected_documents(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    manager = await db.get(User, agent.user_id)
    assert manager is not None
    manager.language = "fr"
    await db.commit()
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)

    created = await goal_service.create(
        GoalCreate(
            title="Document / backed Goal",
            description="# Objective\n\nKeep the source durable.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            active=False,
        )
    )

    description = await db.get(MemoryItem, created.description_document_id)
    tracking = await db.get(MemoryItem, created.tracking_document_id)
    assert description is not None
    assert tracking is not None
    assert description.node_kind == tracking.node_kind == "document"
    assert description.deletion_protected is True
    assert tracking.deletion_protected is True
    assert description.read_only is False
    assert tracking.read_only is False
    assert description.title == "Document / backed Goal — Description"
    assert tracking.title == "Document / backed Goal — Suivi"
    assert description.metadata_["document_path"] == "Objectifs/Document backed Goal"
    assert tracking.metadata_["document_path"] == "Objectifs/Document backed Goal"
    with pytest.raises(memory_service.MemoryPermissionError, match="cannot be forgotten"):
        await memory_service.forget_item(
            description.id, actor_agent_id=agent.id
        )
    with pytest.raises(memory_service.MemoryPermissionError, match="controlled by its Goal"):
        await memory_service.update_item(
            description.id,
            MemoryItemUpdate(
                expected_revision=description.revision,
                metadata={**description.metadata_, "document_path": "Elsewhere"},
            ),
            actor_agent_id=agent.id,
        )
    with pytest.raises(memory_service.MemoryPermissionError, match="controlled by its Goal"):
        await memory_service.update_item(
            description.id,
            MemoryItemUpdate(
                expected_revision=description.revision,
                metadata={"document_path": description.metadata_["document_path"]},
            ),
            actor_agent_id=agent.id,
        )
    with pytest.raises(memory_service.MemoryPermissionError, match="controlled by its Goal"):
        await memory_service.update_item(
            description.id,
            MemoryItemUpdate(
                expected_revision=description.revision,
                title="Renamed outside the Goal",
            ),
            actor_agent_id=agent.id,
        )
    with pytest.raises(memory_service.MemoryPermissionError, match="controlled by its Goal"):
        await memory_service.transfer_document_owner(
            description.id,
            DocumentOwnerUpdate(
                expected_revision=description.revision,
                expected_lock_version=description.lock_version,
                kind="agent",
                id=referrer.id,
            ),
            actor_agent_id=agent.id,
        )

    await memory_service.update_item(
        description.id,
        MemoryItemUpdate(
            expected_revision=description.revision,
            payload=MemoryPayload(text="<h1>Revised objective</h1>"),
        ),
        actor_agent_id=agent.id,
    )
    refreshed = await goal_service.get_read(created.id)
    assert refreshed is not None
    assert refreshed.description == "<h1>Revised objective</h1>"
    assert refreshed.revision == created.revision + 1

    renamed = await goal_service.update(
        created.id,
        GoalUpdate(
            expected_revision=refreshed.revision,
            title="Cap / Nord",
        ),
    )
    assert renamed is not None
    renamed_description = await db.get(MemoryItem, created.description_document_id)
    renamed_tracking = await db.get(MemoryItem, created.tracking_document_id)
    assert renamed_description is not None
    assert renamed_tracking is not None
    assert renamed_description.title == "Cap / Nord — Description"
    assert renamed_tracking.title == "Cap / Nord — Suivi"
    assert renamed_description.metadata_["document_path"] == "Objectifs/Cap Nord"
    assert renamed_tracking.metadata_["document_path"] == "Objectifs/Cap Nord"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_folder", [True, False])
async def test_goal_document_reconciliation_repairs_legacy_folders_and_titles(
    db, legacy_folder: bool
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    manager = await db.get(User, agent.user_id)
    assert manager is not None
    manager.language = "fr"
    await db.commit()
    created = await goal_service.create(
        GoalCreate(
            title="Plan / lancement",
            description="Préparer le lancement.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            active=False,
        )
    )
    documents = [
        await db.get(MemoryItem, created.description_document_id),
        await db.get(MemoryItem, created.tracking_document_id),
    ]
    assert all(document is not None for document in documents)
    for index, document in enumerate(documents):
        assert document is not None
        document.title = "Description" if index == 0 else "Suivi"
        document.metadata_ = {
            **document.metadata_,
            "document_path": (
                f"Goals/{created.id}" if legacy_folder else "Objectifs/Plan lancement"
            ),
        }
    await db.commit()

    assert await reconcile_goal_document_paths(db) == 2
    await db.commit()
    assert await reconcile_goal_document_paths(db) == 0
    assert all(
        document is not None
        and document.metadata_["document_path"] == "Objectifs/Plan lancement"
        for document in documents
    )
    assert [document.title for document in documents if document is not None] == [
        "Plan / lancement — Description",
        "Plan / lancement — Suivi",
    ]


@pytest.mark.asyncio
async def test_goal_schedule_is_persisted_and_updated_with_the_goal(db) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    created = await goal_service.create(
        GoalCreate(
            title="Scheduled Goal",
            description="Run only during this Goal's own window.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            schedule_enabled=True,
            schedule=[
                GoalScheduleWindow(
                    weekdays=[0, 1, 2, 3, 4],
                    start_time="09:00",
                    end_time="17:00",
                )
            ],
            active=False,
        )
    )

    assert created.schedule_enabled is True
    assert created.schedule[0].weekdays == [0, 1, 2, 3, 4]

    updated = await goal_service.update(
        created.id,
        GoalUpdate(
            expected_revision=created.revision,
            schedule_enabled=False,
            schedule=[],
        ),
    )

    assert updated is not None
    assert updated.schedule_enabled is False
    assert updated.schedule == []


@pytest.mark.asyncio
async def test_due_goal_creates_an_ordinary_dispatcher_owned_task(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    publish = AsyncMock()
    monkeypatch.setattr("app.task.task_service.publish_created", publish)

    created = await goal_service.create(
        GoalCreate(
            title="Develop the company",
            description="Grow revenue and improve operations over time.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=3600,
        )
    )

    assert await runner.start_due_cycle() is True
    assert await runner.start_due_cycle() is False

    task = await db.scalar(select(Task).where(Task.goal_id == created.id))
    cycle = await db.scalar(select(GoalCycle).where(GoalCycle.goal_id == created.id))
    goal = await db.get(Goal, created.id)
    assert task is not None
    assert cycle is not None
    assert goal is not None
    assert task.status == TaskStatus.CREATE
    assert task.agent_id == agent.id
    assert task.forced_route is None
    assert task.forced_effort is None
    assert task.goal_id == created.id
    assert task.data is not None
    assert task.data["goal_referrer_agent_id"] == referrer.id
    assert "retention_reasons" in task.data
    assert f"id={referrer.id}" in (task.objective or "")
    assert "DURABLE GOAL TRACKING" in (task.objective or "")
    assert created.referrer is not None
    assert created.referrer.type == GoalReferrerType.AGENT
    assert created.referrer.agent_id == referrer.id
    assert cycle.task_id == task.id
    assert cycle.sequence == 1
    assert goal.next_cycle_at is None
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_messenger_goal_cycles_keep_the_linked_galaris_requester(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    tool = Tool(
        code=f"goal-requester-{uuid4().hex[:8]}",
        label="Goal requester test",
        description="",
        connection_schema={},
    )
    owner = User(
        email=f"goal-owner-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    creator = User(
        email=f"goal-creator-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    db.add_all([tool, owner, creator])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    identity = MessengerUser(
        tool_id=tool.id,
        external_id="linked-owner",
        display_name="Linked owner",
        is_ai=False,
        galaris_user_id=owner.id,
    )
    db.add_all([connection, identity])
    await db.commit()

    messenger = SimpleNamespace(
        tool_id=tool.id,
        self_id="goal-agent",
        kind="test_messenger",
    )
    monkeypatch.setattr(
        "app.messenger.service.messenger_for_agent_connection",
        AsyncMock(return_value=messenger),
    )
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())

    user_service.set_current_user(creator)
    try:
        created = await goal_service.create(
            GoalCreate(
                title="Messenger-owned Goal",
                description="Keep the subscription requester durable.",
                agent_id=agent.id,
                referrer=GoalMessengerReferrerInput(
                    type="MESSENGER",
                    connection_id=connection.id,
                    user_id="linked-owner",
                    display_name="Linked owner",
                ),
            )
        )
    finally:
        user_service.set_current_user(None)

    assert created.created_by == creator.id
    assert created.requester_user_id == owner.id
    persisted = await db.get(Goal, created.id)
    assert persisted is not None
    persisted.requester_user_id = None  # Simulate a Goal created before requester snapshots.
    await db.commit()
    assert await runner.start_due_cycle() is True
    task = await db.scalar(select(Task).where(Task.goal_id == created.id))
    assert task is not None
    assert task.requester_user_id == owner.id
    await db.refresh(persisted)
    assert persisted.requester_user_id == owner.id


@pytest.mark.asyncio
async def test_due_goal_waits_while_agent_has_pending_work(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    user = User(
        email=f"goal-search-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    created = await goal_service.create(
        GoalCreate(
            title="Background objective",
            description="Advance only while the agent is idle.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=0,
        )
    )
    db.add(
        Task(
            label="Interactive work already queued",
            objective="Handle the user's request",
            status=TaskStatus.CREATE,
            agent_id=agent.id,
            paused=False,
            cost=0.0,
        )
    )
    await db.commit()

    assert await runner.start_due_cycle() is False
    assert await db.scalar(
        select(GoalCycle.id).where(GoalCycle.goal_id == created.id)
    ) is None


@pytest.mark.asyncio
async def test_manual_only_due_cycle_is_started_without_scheduled_due_cycles(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled_agent = await _new_agent(db)
    manual_agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.task.task_service.publish_created",
        AsyncMock(),
    )
    monkeypatch.setattr(
        settings_service,
        "is_goal_processing_allowed",
        lambda *_args, **_kwargs: False,
    )
    scheduled = await goal_service.create(
        GoalCreate(
            title="Scheduled objective",
            description="Wait for the configured weekly schedule.",
            agent_id=scheduled_agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
        )
    )
    manual = await goal_service.create(
        GoalCreate(
            title="Manual objective",
            description="Start immediately even outside the schedule.",
            agent_id=manual_agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            active=False,
        )
    )
    queued = await goal_service.run_now(
        manual.id,
        GoalCommand(expected_revision=manual.revision),
    )
    assert queued is not None

    assert await runner.start_due_cycle(manual_only=True) is True

    manual_goal = await db.get(Goal, manual.id)
    assert manual_goal is not None
    assert manual_goal.manual_run_requested_at is None
    assert await db.scalar(
        select(Task.id).where(Task.goal_id == manual.id)
    ) is not None
    assert await db.scalar(
        select(Task.id).where(Task.goal_id == scheduled.id)
    ) is None


@pytest.mark.asyncio
async def test_due_goal_does_not_launch_without_dedicated_tracking_llm(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    agent_id = agent.id
    referrer = await _new_agent(db)
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    created = await goal_service.create(
        GoalCreate(
            title="Blocked until tracking is configured",
            description="No Task may be created without the dedicated Goal model.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=0,
        )
    )

    assert await runner.start_due_cycle() is False
    assert await db.scalar(
        select(GoalCycle.id).where(GoalCycle.goal_id == created.id)
    ) is None
    assert await db.scalar(select(Task.id).where(Task.goal_id == created.id)) is None

    page = await goal_service.list_page(agent_id=agent_id)
    assert page.tracking_llm_configured is False


@pytest.mark.asyncio
async def test_goal_search_can_match_a_referrer_agent(db) -> None:
    owner = await _new_agent(db)
    referrer = await _new_agent(db)
    created = await goal_service.create(
        GoalCreate(
            title="Searchable Goal",
            description="Search by the referring agent.",
            agent_id=owner.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=0,
        )
    )

    page = await goal_service.list_page(
        agent_id=owner.id,
        search=referrer.code,
    )

    assert [item.id for item in page.items] == [created.id]


@pytest.mark.asyncio
async def test_goal_cycles_are_paginated_newest_first(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Large cycle history",
        description="Exercise server-side pagination.",
        agent_id=agent.id,
        tracking_content="<h1>Current tracking</h1>",
        cycle_delay_seconds=0,
        status=GoalStatus.COMPLETED,
    )
    db.add(goal)
    await db.flush()
    db.add_all(
        [
            GoalCycle(
                goal_id=goal.id,
                sequence=sequence,
                status=GoalCycleStatus.DECIDED,
                verdict=(
                    GoalVerdict.STOP if sequence == 55 else GoalVerdict.CONTINUE
                ),
            )
            for sequence in range(1, 56)
        ]
    )
    await db.commit()

    first = await goal_service.list_cycles(goal.id, page=1, page_size=20)
    second = await goal_service.list_cycles(goal.id, page=2, page_size=20)
    detail = await goal_service.get_detail(goal.id)

    assert first is not None and second is not None and detail is not None
    assert first.total == 55
    assert first.page == 1
    assert [cycle.sequence for cycle in first.items] == list(range(55, 35, -1))
    assert [cycle.sequence for cycle in second.items] == list(range(35, 15, -1))
    assert detail.tracking_content == "<h1>Current tracking</h1>"
    assert "cycles" not in detail.model_dump()


@pytest.mark.asyncio
async def test_continue_schedules_from_task_finish_and_keeps_paused_goal_paused(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    finished = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = uuid4()
    goal = await make_goal(
        title="Long objective",
        description="Keep improving the system.",
        agent_id=agent.id,
        cycle_delay_seconds=600,
        status=GoalStatus.PAUSED,
    )
    task = Task(
        label="Cycle 1",
        objective="Improve one part",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
        cost=1.25,
    )
    cycle = GoalCycle(
        goal=goal,
        sequence=1,
        task=task,
        status=GoalCycleStatus.JUDGING,
        task_finished_at=finished,
        task_cost=1.25,
        judge_cost=0.01,
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    goal_id, cycle_id = goal.id, cycle.id
    expected_revision = goal.revision
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._finish_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id,
        token,
        _judgement("CONTINUE"),
        expected_goal_revision=expected_revision,
        cost=0.05,
        llm_id=None,
    )

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_goal.status == GoalStatus.PAUSED
    assert persisted_goal.next_cycle_at == finished + timedelta(minutes=10)
    assert (await goal_service.read_markdown(persisted_goal)).tracking == _judgement(
        "CONTINUE"
    ).tracking_content
    assert persisted_cycle.verdict == GoalVerdict.CONTINUE
    assert persisted_cycle.judge_cost == pytest.approx(0.06)
    assert persisted_cycle.task_cost == pytest.approx(1.25)


@pytest.mark.asyncio
async def test_terminal_cycle_is_judged_once_and_stop_completes_goal(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Finite objective",
        description="Produce the requested deliverable.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Cycle 1",
        objective="Produce it",
        status=TaskStatus.SUCCESS,
        paused=True,
        agent_id=agent.id,
        goal=goal,
        feedback="Deliverable produced",
        cost=0.75,
        data={"pause_reasons": [task_service.PAUSE_AWAIT]},
    )
    cycle = GoalCycle(goal=goal, sequence=1, task=task)
    db.add_all([goal, task, cycle])
    await db.flush()
    db.add(
        TaskAttempt(
            task_id=task.id,
            attempt_number=1,
            phase=TaskStatus.DISPATCH.value,
            status="SUCCESS",
            worker_id="goal-test",
            lease_token=uuid4(),
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    goal_id, cycle_id, task_id, agent_id = goal.id, cycle.id, task.id, agent.id

    structured = AsyncMock(
        return_value=StructuredInferenceResult(
            output=_judgement("STOP"),
            cost=0.02,
            messages=[],
        )
    )
    monkeypatch.setattr(
        runner,
        "run_structured",
        structured,
    )
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    assert await runner.process_terminal_cycle() is True
    assert await runner.process_terminal_cycle() is False

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_goal.status == GoalStatus.COMPLETED
    assert persisted_goal.next_cycle_at is None
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.STOP
    assert persisted_cycle.judge_attempt_count == 1
    assert persisted_cycle.task_cost == pytest.approx(0.75)
    assert persisted_cycle.judge_cost == pytest.approx(0.02)
    assert (await goal_service.read_markdown(persisted_goal)).tracking == _judgement(
        "STOP"
    ).tracking_content
    structured.assert_awaited_once()
    tracking_call = structured.await_args.kwargs
    assert tracking_call["task_id"] == task_id
    assert tracking_call["agent_id"] == agent_id
    assert tracking_call["request_limit"] == 2
    assert infer_call_type([], tracking_call["system_prompt"]) == "goal_tracking"


@pytest.mark.asyncio
async def test_terminal_legacy_messenger_cycle_restores_frozen_requester(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    owner = User(
        email=f"legacy-goal-owner-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    tool = Tool(
        code=f"legacy-goal-chat-{uuid4().hex[:8]}",
        label="Legacy Goal Chat",
        description="",
        connection_schema={},
    )
    db.add_all([owner, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    goal = await make_goal(
        title="Legacy Messenger Goal",
        description="Judge a cycle created before requester snapshots.",
        agent_id=agent.id,
        requester_user_id=owner.id,
        referrer_type=GoalReferrerType.MESSENGER,
        referrer_connection_id=connection.id,
        referrer_user_id=f"user:{owner.id}",
        referrer_display_name="Legacy owner",
        referrer_platform="internal",
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Legacy cycle",
        objective="Finish work admitted before requester snapshots.",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
        messenger_connection_id=connection.id,
        requester_user_id=None,
    )
    cycle = GoalCycle(goal=goal, sequence=1, task=task)
    db.add_all([goal, task, cycle])
    await db.commit()
    task_id = task.id
    owner_id = owner.id

    async def structured(**_kwargs):
        persisted_task = await db.get(Task, task_id)
        assert persisted_task is not None
        assert persisted_task.requester_user_id == owner_id
        return StructuredInferenceResult(
            output=_judgement("CONTINUE"),
            cost=0.0,
            messages=[],
        )

    monkeypatch.setattr(runner, "run_structured", structured)
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    assert await runner.process_terminal_cycle() is True

    db.expire_all()
    persisted_task = await db.get(Task, task_id)
    assert persisted_task is not None
    assert persisted_task.requester_user_id == owner_id


@pytest.mark.asyncio
async def test_terminal_cycle_leaves_running_state_without_tracking_llm(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Waiting Goal cycle",
        description="The completed Task must no longer appear to be running.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Completed after a human answer",
        objective="Wait, resume, then finish",
        status=TaskStatus.SUCCESS,
        paused=True,
        agent_id=agent.id,
        goal=goal,
        cost=0.25,
        data={"pause_reasons": [task_service.PAUSE_AWAIT]},
    )
    cycle = GoalCycle(goal=goal, sequence=1, task=task)
    db.add_all([goal, task, cycle])
    await db.commit()
    cycle_id = cycle.id
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    assert await runner.process_terminal_cycle() is True

    db.expire_all()
    persisted = await db.get(GoalCycle, cycle_id)
    assert persisted is not None
    assert persisted.status == GoalCycleStatus.ERROR
    assert persisted.task_finished_at is not None
    assert persisted.task_cost == pytest.approx(0.25)
    assert persisted.error == "RuntimeError: No Goal model is configured for this agent profile."


@pytest.mark.asyncio
async def test_force_terminate_closes_cycle_and_replans_goal(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import agent as agent_domain
    from app.task import scheduler

    agent = await _new_agent(db)
    task_lease = uuid4()
    attempt_id = uuid4()
    cycle_id = uuid4()
    goal = await make_goal(
        title="Recover supervision",
        description="Continue monitoring after a stuck Task is abandoned.",
        agent_id=agent.id,
        cycle_delay_seconds=600,
        status=GoalStatus.ACTIVE,
    )
    child = await make_goal(
        title="Follow forced cycle",
        description="Run even when the parent cycle is force-terminated.",
        agent_id=agent.id,
        parent_goal_id=goal.id,
        cycle_delay_seconds=None,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Stuck cycle",
        objective="Work that never returned",
        status=TaskStatus.EXEC,
        paused=True,
        agent_id=agent.id,
        goal=goal,
        cost=1.25,
        lease_token=task_lease,
        lease_owner="dead-worker",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        cancel_requested=True,
        data={
            "pause_reasons": [task_service.PAUSE_USER],
            "retention_reasons": ["goal_judgement"],
        },
    )
    attempt = TaskAttempt(
        id=attempt_id,
        task=task,
        attempt_number=1,
        phase=TaskStatus.EXEC.value,
        status=TaskAttemptStatus.CLAIMED.value,
        worker_id="dead-worker",
        lease_token=task_lease,
    )
    cycle = GoalCycle(
        id=cycle_id,
        goal=goal,
        task=task,
        sequence=1,
        status=GoalCycleStatus.RUNNING,
    )
    db.add_all([goal, child, task, attempt, cycle])
    await db.commit()
    await db.refresh(task)
    task_id = task.id
    goal_id = task.goal_id
    child_id = child.id
    assert goal_id is not None
    revision = task.revision

    monkeypatch.setattr(scheduler, "cancel", lambda task_id: True)
    monkeypatch.setattr(scheduler, "wake", lambda task_id=None: None)
    terminal = AsyncMock()
    monkeypatch.setattr(agent_domain, "handle_terminal_task", terminal)
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    result = await task_service.force_terminate(task_id, revision)

    assert result is not None
    forced_revision = result.revision
    repeated = await task_service.force_terminate(task_id, forced_revision)
    assert repeated is not None
    assert repeated.revision == forced_revision
    db.expire_all()
    persisted_task = await db.get(Task, task_id)
    persisted_attempt = await db.get(TaskAttempt, attempt_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    persisted_goal = await db.get(Goal, goal_id)
    relational_trigger = await db.scalar(
        select(GoalCycleTrigger).where(
            GoalCycleTrigger.goal_id == child_id,
            GoalCycleTrigger.source_cycle_id == cycle_id,
        )
    )
    assert persisted_task is not None
    assert persisted_attempt is not None
    assert persisted_cycle is not None
    assert persisted_goal is not None
    assert relational_trigger is not None
    assert persisted_task.status == TaskStatus.ERROR
    assert persisted_task.paused is False
    assert persisted_task.lease_token is None
    assert persisted_task.cancel_requested is False
    assert task_service.retention_reasons(persisted_task) == []
    assert persisted_attempt.status == TaskAttemptStatus.CANCELLED.value
    assert persisted_attempt.finished_at is not None
    assert persisted_attempt.retryable is False
    assert (persisted_attempt.data or {}).get("force_terminated") is True
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.CONTINUE
    assert persisted_cycle.progress_changed is False
    assert persisted_cycle.task_finished_at is not None
    assert persisted_cycle.task_cost == pytest.approx(1.25)
    assert persisted_goal.status == GoalStatus.ACTIVE
    assert persisted_goal.next_cycle_at == (
        persisted_cycle.task_finished_at + timedelta(minutes=10)
    )
    terminal.assert_awaited_once()


@pytest.mark.asyncio
async def test_goal_costs_sum_task_snapshots_and_judgements(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Costed objective",
        description="Track every cycle.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.COMPLETED,
    )
    db.add(goal)
    await db.flush()
    db.add_all(
        [
            GoalCycle(
                goal_id=goal.id,
                sequence=1,
                status=GoalCycleStatus.DECIDED,
                verdict=GoalVerdict.CONTINUE,
                task_finished_at=datetime.now(timezone.utc),
                task_cost=1.2,
                judge_cost=0.03,
            ),
            GoalCycle(
                goal_id=goal.id,
                sequence=2,
                status=GoalCycleStatus.DECIDED,
                verdict=GoalVerdict.STOP,
                task_finished_at=datetime.now(timezone.utc),
                task_cost=0.8,
                judge_cost=0.02,
            ),
        ]
    )
    await db.commit()

    page = await goal_service.list_page(agent_id=agent.id)

    assert page.total == 1
    assert page.items[0].cycle_count == 2
    assert page.items[0].task_cost == pytest.approx(2.0)
    assert page.items[0].evaluation_cost == pytest.approx(0.05)
    assert page.items[0].total_cost == pytest.approx(2.05)
    assert page.summary.total_cost == pytest.approx(2.05)


@pytest.mark.asyncio
async def test_goal_summary_includes_live_cycle_task_cost(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Running cost",
        description="Expose spend while the current cycle is still running.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Live cycle",
        objective="Keep working",
        status=TaskStatus.EXEC,
        agent_id=agent.id,
        goal=goal,
        cost=0.42,
    )
    db.add_all([goal, task, GoalCycle(goal=goal, sequence=1, task=task)])
    await db.commit()

    page = await goal_service.list_page(agent_id=agent.id)

    assert page.items[0].task_cost == pytest.approx(0.42)
    assert page.items[0].total_cost == pytest.approx(0.42)
    assert page.summary.total_cost == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_goal_pause_resume_uses_optimistic_revision(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    created = await goal_service.create(
        GoalCreate(
            title="Managed objective",
            description="Exercise explicit lifecycle commands.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
        )
    )

    paused = await goal_service.pause(
        created.id, GoalCommand(expected_revision=created.revision)
    )
    assert paused is not None
    assert paused.status == GoalStatus.PAUSED

    with pytest.raises(goal_service.GoalRevisionConflict):
        await goal_service.resume(
            created.id, GoalCommand(expected_revision=created.revision)
        )

    resumed = await goal_service.resume(
        created.id, GoalCommand(expected_revision=paused.revision)
    )
    assert resumed is not None
    assert resumed.status == GoalStatus.ACTIVE
    assert resumed.next_cycle_at is not None


@pytest.mark.asyncio
async def test_goal_resume_restarts_completed_goal_and_preserves_history(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    created = await goal_service.create(
        GoalCreate(
            title="Restartable objective",
            description="Allow an accidental completion to be undone.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
        )
    )
    previous_cycle = GoalCycle(
        goal_id=created.id,
        sequence=1,
        status=GoalCycleStatus.DECIDED,
        verdict=GoalVerdict.STOP,
        reason="Previously considered complete.",
    )
    db.add(previous_cycle)
    await db.commit()

    completed = await goal_service.complete(
        created.id, GoalCommand(expected_revision=created.revision)
    )
    assert completed is not None
    assert completed.completed_at is not None

    before = datetime.now(timezone.utc)
    restarted = await goal_service.resume(
        created.id, GoalCommand(expected_revision=completed.revision)
    )
    after = datetime.now(timezone.utc)

    assert restarted is not None
    assert restarted.status == GoalStatus.ACTIVE
    assert restarted.completed_at is None
    assert restarted.next_cycle_at is not None
    assert before <= restarted.next_cycle_at <= after
    persisted_cycle = await db.get(GoalCycle, previous_cycle.id)
    assert persisted_cycle is not None
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.STOP


@pytest.mark.asyncio
async def test_goal_run_now_skips_delay_and_reactivates_goal(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    created = await goal_service.create(
        GoalCreate(
            title="Accelerated objective",
            description="Allow a human to request the next cycle immediately.",
            agent_id=agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=86_400,
            active=False,
        )
    )

    before = datetime.now(timezone.utc)
    queued = await goal_service.run_now(
        created.id, GoalCommand(expected_revision=created.revision)
    )
    after = datetime.now(timezone.utc)

    assert queued is not None
    assert queued.status == GoalStatus.ACTIVE
    assert queued.next_cycle_at is not None
    assert before <= queued.next_cycle_at <= after
    persisted = await db.get(Goal, created.id)
    assert persisted is not None
    assert persisted.manual_run_requested_at == queued.next_cycle_at


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["run_now", "resume"])
@pytest.mark.parametrize("task_status", [TaskStatus.ERROR, TaskStatus.SUCCESS])
@pytest.mark.parametrize("verdict", ["CONTINUE", "STOP"])
async def test_manual_cycle_request_survives_failed_tracking_recovery(
    db,
    monkeypatch: pytest.MonkeyPatch,
    command_name: str,
    task_status: TaskStatus,
    verdict: str,
) -> None:
    agent = await _new_agent(db)
    referrer = await _new_agent(db)
    goal = await make_goal(
        title="Recover a failed cycle evaluation",
        description="Honor a requested work cycle after tracking recovers.",
        agent_id=agent.id,
        referrer_type=GoalReferrerType.AGENT,
        referrer_agent_id=referrer.id,
        cycle_delay_seconds=86_400,
        status=GoalStatus.ERROR,
        last_error="Tracking provider returned HTTP 404",
    )
    task = Task(
        label="Previous work cycle",
        objective="Preserve the previous work result",
        status=task_status,
        agent_id=agent.id,
        goal=goal,
        feedback="Previous work result",
    )
    cycle = GoalCycle(
        goal=goal,
        task=task,
        sequence=18,
        status=GoalCycleStatus.ERROR,
        error="Tracking provider returned HTTP 404",
        task_finished_at=datetime.now(timezone.utc),
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    goal_id, task_id = goal.id, task.id
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "run_structured",
        AsyncMock(return_value=StructuredInferenceResult(
            output=_judgement(verdict), cost=0.02, messages=[],
        )),
    )

    command = goal_service.run_now if command_name == "run_now" else goal_service.resume
    queued = await command(goal_id, GoalCommand(expected_revision=goal.revision))
    assert queued is not None
    # A requested new cycle must wait for the previous evaluation to finish.
    assert await runner.start_due_cycle(manual_only=True) is False
    assert await runner.process_terminal_cycle() is True

    should_start = command_name == "run_now" and verdict == "CONTINUE"
    assert await runner.start_due_cycle(manual_only=True) is should_start
    assert await runner.start_due_cycle(manual_only=True) is False
    db.expire_all()
    tasks = list((await db.scalars(select(Task).where(Task.goal_id == goal_id))).all())
    assert len(tasks) == (2 if should_start else 1)
    previous_task = next(item for item in tasks if item.id == task_id)
    assert previous_task.status == task_status
    assert previous_task.feedback == "Previous work result"
    if should_start:
        next_cycle = await db.scalar(
            select(GoalCycle).where(GoalCycle.goal_id == goal_id, GoalCycle.sequence == 19)
        )
        assert next_cycle is not None
        assert next_cycle.trigger_kind == GoalCycleTriggerKind.MANUAL
        assert next_cycle.task_id != task_id
    persisted_goal = await db.get(Goal, goal_id)
    assert persisted_goal is not None
    assert persisted_goal.manual_run_requested_at is None


@pytest.mark.asyncio
async def test_goal_delay_edit_recalculates_from_previous_task_finish(db) -> None:
    agent = await _new_agent(db)
    finished = datetime.now(timezone.utc) - timedelta(hours=1)
    goal = await make_goal(
        title="Cadenced objective",
        description="Keep its cooldown anchored to actual Task completion.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.PAUSED,
        next_cycle_at=finished + timedelta(hours=1),
    )
    db.add(goal)
    await db.flush()
    db.add(
        GoalCycle(
            goal=goal,
            sequence=1,
            status=GoalCycleStatus.DECIDED,
            verdict=GoalVerdict.CONTINUE,
            task_finished_at=finished,
        )
    )
    await db.commit()
    goal_id, revision = goal.id, goal.revision

    updated = await goal_service.update(
        goal_id,
        GoalUpdate(expected_revision=revision, cycle_delay_seconds=7200),
    )

    assert updated is not None
    assert updated.cycle_delay_seconds == 7200
    assert updated.next_cycle_at == finished + timedelta(hours=2)


@pytest.mark.asyncio
async def test_goal_tracking_can_be_corrected_manually(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Correctable tracking",
        description="# Objective\n\nKeep the durable state accurate.",
        tracking_content="# Previous state\n\nThis information is outdated.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.PAUSED,
    )
    db.add(goal)
    await db.commit()
    goal_id, revision = goal.id, goal.revision

    corrected_tracking = "<h1>Current state</h1><p>The information has been corrected.</p>"
    updated = await goal_service.update(
        goal_id,
        GoalUpdate(
            expected_revision=revision,
            tracking_content=corrected_tracking,
        ),
    )

    assert updated is not None
    assert updated.tracking_content == corrected_tracking


@pytest.mark.asyncio
async def test_goal_complete_prevents_new_cycle(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Manual stop",
        description="Allow a human to stop the objective.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
        next_cycle_at=datetime.now(timezone.utc),
    )
    db.add(goal)
    await db.commit()
    goal_id, revision = goal.id, goal.revision

    completed = await goal_service.complete(
        goal_id, GoalCommand(expected_revision=revision)
    )

    assert completed is not None
    assert completed.status == GoalStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.next_cycle_at is None
    assert await runner.start_due_cycle() is False


@pytest.mark.asyncio
async def test_goal_complete_closes_failed_evaluation_cycle(db) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Stop failed evaluation",
        description="A manual stop must leave no open cycle.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ERROR,
        last_error="judge failed",
    )
    cycle = GoalCycle(
        goal=goal,
        sequence=1,
        status=GoalCycleStatus.ERROR,
        error="judge failed",
    )
    db.add_all([goal, cycle])
    await db.commit()
    goal_id, cycle_id, revision = goal.id, cycle.id, goal.revision

    completed = await goal_service.complete(
        goal_id, GoalCommand(expected_revision=revision)
    )

    assert completed is not None
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_cycle is not None
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.STOP
    assert completed.status == GoalStatus.COMPLETED


@pytest.mark.asyncio
async def test_failed_judgement_accounts_for_persisted_llm_calls(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    now = datetime.now(timezone.utc)
    token = uuid4()
    goal = await make_goal(
        title="Cost failures",
        description="Count evaluation spend even when structured output fails.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Completed cycle",
        objective="Work",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
        cost=0.2,
    )
    cycle = GoalCycle(
        goal=goal,
        sequence=1,
        task=task,
        status=GoalCycleStatus.JUDGING,
        judge_started_at=now - timedelta(seconds=5),
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.flush()
    db.add(
        LLMCall(
            task_id=task.id,
            provider_name="test",
            requested_model="judge",
            effective_model="judge",
            status="error",
            cost=0.07,
            started_at=now,
            completed_at=now,
        )
    )
    await db.commit()
    goal_id, cycle_id = goal.id, cycle.id
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._fail_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id,
        token,
        ValueError("invalid structured output"),
    )

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_goal.status == GoalStatus.ERROR
    assert persisted_cycle.status == GoalCycleStatus.ERROR
    assert persisted_cycle.judge_cost == pytest.approx(0.07)


@pytest.mark.asyncio
async def test_due_goal_stops_cleanly_when_owner_agent_is_deleted(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    goal = await make_goal(
        title="Orphaned objective",
        description="Do not create work for a deleted agent.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
        next_cycle_at=datetime.now(timezone.utc),
    )
    db.add(goal)
    await db.commit()
    goal_id, agent_id = goal.id, agent.id
    agent.soft_delete()
    await db.commit()
    db.expire_all()
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    assert await runner.start_due_cycle() is True

    persisted = await db.get(Goal, goal_id)
    assert persisted is not None
    assert persisted.status == GoalStatus.ERROR
    assert persisted.next_cycle_at is None
    assert str(agent_id) in (persisted.last_error or "")
    assert await db.scalar(select(Task.id).where(Task.goal_id == goal_id)) is None

    page = await goal_service.list_page(agent_id=agent_id)
    assert page.total == 1
    assert page.items[0].agent_name == f"Agent #{agent_id}"


@pytest.mark.asyncio
async def test_failed_judgement_preserves_manual_pause(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    token = uuid4()
    goal = await make_goal(
        title="Paused evaluation",
        description="A human pause must win over an evaluation failure.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.PAUSED,
    )
    task = Task(
        label="Terminal Task",
        objective="Work",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
    )
    cycle = GoalCycle(
        goal=goal,
        sequence=1,
        task=task,
        status=GoalCycleStatus.JUDGING,
        judge_started_at=datetime.now(timezone.utc),
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    goal_id, cycle_id = goal.id, cycle.id
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._fail_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id, token, RuntimeError("judge unavailable")
    )

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_goal.status == GoalStatus.PAUSED
    assert "judge unavailable" in (persisted_goal.last_error or "")
    assert persisted_cycle.status == GoalCycleStatus.ERROR


@pytest.mark.asyncio
async def test_manual_completion_closes_cycle_when_running_judge_fails(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    token = uuid4()
    goal = await make_goal(
        title="Completed during evaluation",
        description="Manual completion is authoritative.",
        agent_id=agent.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc),
    )
    task = Task(
        label="Terminal Task",
        objective="Work",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
    )
    cycle = GoalCycle(
        goal=goal,
        sequence=1,
        task=task,
        status=GoalCycleStatus.JUDGING,
        judge_started_at=datetime.now(timezone.utc),
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    goal_id, cycle_id = goal.id, cycle.id
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._fail_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id, token, RuntimeError("late judge failure")
    )

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_goal.status == GoalStatus.COMPLETED
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.STOP


@pytest.mark.asyncio
async def test_busy_earliest_goal_does_not_starve_another_agent(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy_agent = await _new_agent(db)
    free_agent = await _new_agent(db)
    referrer = await _new_agent(db)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())

    busy_goal = await goal_service.create(
        GoalCreate(
            title="Busy agent Goal",
            description="This due Goal is temporarily ineligible.",
            agent_id=busy_agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=0,
        )
    )
    free_goal = await goal_service.create(
        GoalCreate(
            title="Free agent Goal",
            description="This Goal must still get a cycle.",
            agent_id=free_agent.id,
            referrer=GoalAgentReferrerInput(type="AGENT", agent_id=referrer.id),
            cycle_delay_seconds=0,
        )
    )
    db.add(
        Task(
            label="Busy agent foreground work",
            objective="Keep the first agent occupied",
            status=TaskStatus.CREATE,
            agent_id=busy_agent.id,
            cost=0.0,
        )
    )
    await db.commit()

    assert await runner.start_due_cycle() is True
    assert await db.scalar(
        select(GoalCycle.id).where(GoalCycle.goal_id == busy_goal.id)
    ) is None
    assert await db.scalar(
        select(GoalCycle.id).where(GoalCycle.goal_id == free_goal.id)
    ) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["description", "tracking"])
async def test_goal_edit_discards_stale_judgement_and_keeps_task_retained(
    db, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    agent = await _new_agent(db)
    token = uuid4()
    goal = await make_goal(
        title="Mutable Goal",
        description="Initial instructions.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Finished cycle",
        objective="Follow the initial instructions",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
        cost=0.1,
    )
    task_service.retain(task, "goal_judgement")
    cycle = GoalCycle(
        goal=goal,
        task=task,
        sequence=1,
        status=GoalCycleStatus.JUDGING,
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    expected_revision = goal.revision
    cycle_id, goal_id, task_id = cycle.id, goal.id, task.id
    expected_tracking_revision = await goal_service.get_goal_document_store().revision(goal.tracking_document_id)
    target_document = goal.description_document_id if field == "description" else goal.tracking_document_id
    await goal_service.get_goal_document_store().update(
        target_document,
        content="Instructions changed while the evaluator was running.",
    )
    if field == "description":
        await goal_service.handle_goal_document_change(goal.description_document_id, "update")
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._finish_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id,
        token,
        _judgement("STOP"),
        expected_goal_revision=expected_revision,
        expected_tracking_revision=expected_tracking_revision,
        cost=0.04,
        llm_id=None,
    )

    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    persisted_task = await db.get(Task, task_id)
    assert persisted_goal is not None
    assert persisted_cycle is not None
    assert persisted_task is not None
    assert persisted_goal.status == GoalStatus.ACTIVE
    assert persisted_cycle.status == GoalCycleStatus.RUNNING
    assert persisted_cycle.verdict is None
    assert persisted_cycle.judge_cost == pytest.approx(0.04)
    assert task_service.retention_reasons(persisted_task) == ["goal_judgement"]


@pytest.mark.asyncio
async def test_finish_judgement_refreshes_task_before_releasing_retention(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    token = uuid4()
    goal = await make_goal(
        title="Concurrent Task metadata",
        description="Finish despite a concurrent Task revision.",
        agent_id=agent.id,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    task = Task(
        label="Finished cycle",
        objective="Complete one cycle",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        goal=goal,
        cost=0.1,
    )
    task_service.retain(task, "goal_judgement")
    cycle = GoalCycle(
        goal=goal,
        task=task,
        sequence=1,
        status=GoalCycleStatus.JUDGING,
        lease_token=token,
    )
    db.add_all([goal, task, cycle])
    await db.commit()
    expected_goal_revision = goal.revision
    cycle_id, task_id = cycle.id, task.id
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(
            revision=Task.revision + 1,
            data={
                "retention_reasons": ["goal_judgement"],
                "concurrent_update": True,
            },
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    monkeypatch.setattr(goal_service, "emit_updated", AsyncMock())

    await runner._finish_judgement(  # pyright: ignore[reportPrivateUsage]
        cycle_id,
        token,
        _judgement("CONTINUE"),
        expected_goal_revision=expected_goal_revision,
        cost=0.04,
        llm_id=None,
    )

    db.expire_all()
    persisted_cycle = await db.get(GoalCycle, cycle_id)
    persisted_task = await db.get(Task, task_id)
    assert persisted_cycle is not None
    assert persisted_task is not None
    assert persisted_cycle.status == GoalCycleStatus.DECIDED
    assert persisted_cycle.verdict == GoalVerdict.CONTINUE
    assert task_service.retention_reasons(persisted_task) == []
    assert persisted_task.data == {"concurrent_update": True}


@pytest.mark.asyncio
async def test_agent_cannot_be_its_own_goal_referrer(db) -> None:
    agent = await _new_agent(db)

    with pytest.raises(goal_service.GoalConflictError):
        await goal_service.create(
            GoalCreate(
                title="Self-referred Goal",
                description="The owner needs a distinct person to contact.",
                agent_id=agent.id,
                referrer=GoalAgentReferrerInput(type="AGENT", agent_id=agent.id),
            )
        )


@pytest.mark.asyncio
async def test_messenger_referrer_search_keeps_exact_connection(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.goal.contact_port import GoalHumanContact, contact_directory_port

    agent = await _new_agent(db)
    user = User(
        email=f"goal-referrer-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    search = AsyncMock(
        return_value=(
            GoalHumanContact(
                connection_id=17,
                tool_id=8,
                platform="nextcloud_talk",
                user_id="nicolas",
                display_name="Nicolas",
                galaris_user_id=user.id,
            ),
        )
    )
    monkeypatch.setattr(contact_directory_port, "list_humans", search)

    user_service.set_current_user(user)
    try:
        results = await goal_service.search_messenger_referrers(agent.id, "Nico")
    finally:
        user_service.set_current_user(None)

    assert len(results) == 1
    assert results[0].connection_id == 17
    assert results[0].user_id == "nicolas"
    assert results[0].platform == "nextcloud_talk"
    assert results[0].is_current_user is True
    search.assert_awaited_once_with(agent_id=agent.id, query="Nico")
