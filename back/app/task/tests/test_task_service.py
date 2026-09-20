from types import SimpleNamespace
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import TaskMessage
from app.task import task_service
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus
from app.task.schemas import TaskCreate
from app.topic import Topic


def _task(**kwargs: Any) -> Task:
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "label": "Task",
        "objective": "Objective",
        "status": TaskStatus.CREATE,
        "paused": False,
        "ai": False,
        "cost": 0.0,
        "effort": "standard",
        "auto_approve": False,
        "parent_id": None,
    }
    defaults.update(kwargs)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_retry_uses_delivery_only_recovery_for_failed_plan(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_id = uuid4()
    root = _task(
        status=TaskStatus.ERROR,
        plan={"steps": [{"label": "Deliver", "tools": ["messenger_room_send_file"]}], "cursor": 0},
        data={
            "delivery_recovery": {
                "status": "ready",
                "child_task_id": str(child_id),
                "filename": "final/report.html",
                "destination": "room-1",
                "tool": "messenger_room_send_file",
            }
        },
        execution_result={"prompt": "", "result": "failed", "success": False},
    )
    child = _task(
        id=child_id,
        parent_id=root.id,
        status=TaskStatus.ERROR,
        data={
            "plan_tools": ["file_write", "messenger_room_send_file"],
            "plan_context": "Create and deliver the report.",
            "_agent_run_checkpoint": {"status": "failed"},
        },
        execution_result={"prompt": "", "result": "budget", "success": False},
    )
    db.add_all([root, child])
    await db.commit()
    await db.refresh(root)
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    retried = await task_service.retry(root.id, root.revision)

    assert retried is not None
    assert retried.status == TaskStatus.PLAN
    assert retried.paused is True
    assert retried.execution_result is None
    assert retried.data is not None
    assert retried.data["delivery_recovery"]["status"] == "running"
    await db.refresh(child)
    assert child.status == TaskStatus.DISPATCH
    assert child.paused is False
    assert child.execution_result is None
    assert child.data is not None
    assert child.data["plan_tools"] == ["messenger_room_send_file"]
    assert child.data["delivery_policy"] == "required"
    assert child.data["_agent_run_checkpoint"] == {"status": "failed"}
    assert "Do not recreate" in child.data["plan_context"]


@pytest.mark.asyncio
async def test_retry_preserves_uncertain_effects_and_durable_working_set(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(
        status=TaskStatus.ERROR,
        data={
            "working_set": {
                "version": 1,
                "resources": [
                    {
                        "resource_type": "memory_document",
                        "role": "primary_working_document",
                        "reference": "document://existing",
                        "state": "active",
                    }
                ],
            },
            "_agent_run_checkpoint": {
                "status": "running",
                "data": {
                    "resume_safe": False,
                    "effects": [{"tool_name": "file_create", "status": "started"}],
                },
            },
        },
        execution_result={"prompt": "old", "result": "failed", "success": False},
        feedback="Previous failure",
        last_error="UnsafeCheckpointError",
        attempt_count=7,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    retried = await task_service.retry(task.id, task.revision)

    assert retried is not None
    assert retried.status == TaskStatus.DISPATCH
    assert retried.execution_result is None
    assert retried.feedback is None
    assert retried.last_error is None
    assert retried.attempt_count == 7
    assert retried.data is not None
    assert retried.data["_agent_run_checkpoint"]["data"]["effects"] == [
        {"tool_name": "file_create", "status": "started"}
    ]
    assert retried.data["_agent_run_checkpoint"]["result"] is None
    assert retried.data["working_set"]["resources"][0]["reference"] == (
        "document://existing"
    )


@pytest.mark.asyncio
async def test_create_inherits_parent_topic_immediately(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    topic = Topic(title=f"Inherited topic {uuid4()}")
    db.add(topic)
    await db.flush()
    parent = _task(topic_id=topic.id)
    db.add(parent)
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    child = await task_service.create(
        TaskCreate(label="Child", objective="Continue", parent_id=parent.id)
    )

    assert child.topic_id == topic.id


@pytest.mark.asyncio
async def test_create_inherits_parent_contact_without_waiting_for_topic(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent.models import Agent, Title
    from app.memory import MessengerContactObservation, observe_messenger_contact

    title = Title(label=f"Contact lineage {uuid4()}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Lineage",
        last_name="Agent",
        code=f"lineage-{uuid4()}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="telegram",
            user_id="human-42",
            display_name="Nicolas",
        )
    )
    parent = _task(agent_id=agent.id, contact_memory_item_id=contact_id)
    db.add(parent)
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    child = await task_service.create(
        TaskCreate(label="Child", objective="Continue", parent_id=parent.id)
    )

    assert child.topic_id is None
    assert child.contact_memory_item_id == contact_id


@pytest.mark.asyncio
async def test_create_persists_and_inherits_reasoning_effort_override(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _task(reasoning_effort_override="xhigh")
    db.add(parent)
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    child = await task_service.create(
        TaskCreate(label="Child", objective="Continue", parent_id=parent.id)
    )
    await db.refresh(child)

    assert child.reasoning_effort_override == "xhigh"


@pytest.mark.asyncio
async def test_created_task_keeps_user_language_for_background_execution(db, monkeypatch):
    from core.user import user_service
    from core.user.models import User

    user = User(email=f"language-{uuid4().hex}@example.test", hashed_password="unused", language="zh")
    db.add(user)
    await db.flush()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    user_service.set_current_user(user)
    try:
        task = await task_service.create(TaskCreate(
            label="Report", objective="Write a report.", data={"language": "en"},
        ))
    finally:
        user_service.set_current_user(None)
    await db.refresh(task)

    assert task.data["language"] == "zh"


@pytest.mark.asyncio
async def test_create_serializes_task_message_uuids(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_id = uuid4()
    sender_id = uuid4()
    recipient_id = uuid4()
    room_id = uuid4()
    file_id = uuid4()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    task = await task_service.create(
        TaskCreate(
            label="Conversation follow-up",
            objective="Recover archived messages.",
            messages=[
                TaskMessage(
                    messenger_message_id=message_id,
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    room_id=room_id,
                    file_ids=[file_id],
                    text="Recover the archive.",
                )
            ],
        )
    )

    assert task.messages is not None
    assert task.messages[0].messenger_message_id == message_id
    assert task.messages[0].sender_id == sender_id
    assert task.messages[0].recipient_id == recipient_id
    assert task.messages[0].room_id == room_id
    assert task.messages[0].file_ids == [file_id]


@pytest.mark.asyncio
async def test_explicit_delete_releases_stale_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(status=TaskStatus.SUCCESS)
    task_service.retain(task, "goal_judgement")
    db = SimpleNamespace(commit=AsyncMock())
    force_terminate = AsyncMock(return_value=task)
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_service, "force_terminate", force_terminate)
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    deleted = await task_service.delete(task.id)

    assert deleted is True
    assert task.deleted_at is not None
    assert task_service.retention_reasons(task) == []
    force_terminate.assert_awaited_once_with(
        task.id,
        None,
        notify_terminal=False,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_task_is_force_terminated_before_soft_delete(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import scheduler

    lease_token = uuid4()
    task = _task(
        status=TaskStatus.EXEC,
        lease_token=lease_token,
        lease_owner="worker-1",
    )
    attempt = TaskAttempt(
        task=task,
        attempt_number=1,
        phase=TaskStatus.EXEC.value,
        status=TaskAttemptStatus.CLAIMED.value,
        worker_id="worker-1",
        lease_token=lease_token,
    )
    db.add_all([task, attempt])
    await db.commit()
    task_id = task.id
    attempt_id = attempt.id

    monkeypatch.setattr(scheduler, "cancel", lambda task_id: True)
    notify = AsyncMock()
    monkeypatch.setattr(task_service, "_notify_force_terminated_deletions", notify)
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    deleted = await task_service.delete(task_id)

    assert deleted is True
    db.expire_all()
    persisted_task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .execution_options(include_historized=True)
    )
    persisted_attempt = await db.get(TaskAttempt, attempt_id)
    assert persisted_task is not None
    assert persisted_attempt is not None
    assert persisted_task.status == TaskStatus.ERROR
    assert persisted_task.deleted_at is not None
    assert persisted_task.lease_token is None
    assert persisted_attempt.status == TaskAttemptStatus.CANCELLED.value
    assert persisted_attempt.finished_at is not None
    assert persisted_attempt.retryable is False
    assert (persisted_attempt.data or {}).get("force_terminated") is True
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_can_be_soft_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(status=TaskStatus.CREATE)
    db = SimpleNamespace(commit=AsyncMock())
    emit = AsyncMock()
    force_terminate = AsyncMock(return_value=task)
    notify = AsyncMock()
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_service, "force_terminate", force_terminate)
    monkeypatch.setattr(task_service, "_notify_force_terminated_deletions", notify)
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    deleted = await task_service.delete(task.id)

    assert deleted is True
    assert task.deleted_at is not None
    db.commit.assert_awaited_once()
    emit.assert_awaited_once()
    force_terminate.assert_awaited_once_with(
        task.id,
        None,
        notify_terminal=False,
    )
    notify.assert_awaited_once_with([task])


@pytest.mark.asyncio
async def test_user_paused_active_task_can_be_soft_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(
        status=TaskStatus.DISPATCH,
        paused=True,
        data={"pause_reasons": [task_service.PAUSE_USER]},
    )
    db = SimpleNamespace(commit=AsyncMock())
    emit = AsyncMock()
    force_terminate = AsyncMock(return_value=task)
    notify = AsyncMock()
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(task_service, "force_terminate", force_terminate)
    monkeypatch.setattr(task_service, "_notify_force_terminated_deletions", notify)
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    deleted = await task_service.delete(task.id)

    assert deleted is True
    assert task.deleted_at is not None
    db.commit.assert_awaited_once()
    emit.assert_awaited_once()
    force_terminate.assert_awaited_once_with(
        task.id,
        None,
        notify_terminal=False,
    )
    notify.assert_awaited_once_with([task])


@pytest.mark.asyncio
async def test_cleanup_preserves_retained_success_task(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = _task(status=TaskStatus.SUCCESS)
    purgeable = _task(status=TaskStatus.SUCCESS)
    task_service.retain(retained, "goal_judgement")
    db.add_all([retained, purgeable])
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    await task_service.cleanup_all()

    kept = await db.scalar(
        select(Task)
        .where(Task.id == retained.id)
        .execution_options(include_historized=True)
    )
    purged = await db.scalar(
        select(Task)
        .where(Task.id == purgeable.id)
        .execution_options(include_historized=True)
    )
    assert kept is not None
    assert purged is None


@pytest.mark.asyncio
async def test_summarize_recent_counts_all_filtered_tasks(db: AsyncSession) -> None:
    marker = f"overview-{uuid4()}"
    db.add_all([
        _task(label=marker, status=TaskStatus.CREATE),
        _task(label=marker, status=TaskStatus.DISPATCH),
        _task(label=marker, status=TaskStatus.PLAN, paused=True),
        _task(label=marker, status=TaskStatus.SUCCESS),
        _task(label=marker, status=TaskStatus.ERROR, paused=True),
    ])
    await db.commit()

    total, summary = await task_service.summarize_recent(search=marker)
    errors = await task_service.get_recent(search=marker, errors_only=True)
    paused = await task_service.get_recent(search=marker, paused_only=True)
    paused_count = await task_service.count_recent(search=marker, paused_only=True)

    assert total == 5
    assert summary.running == 2
    assert summary.completed == 1
    assert summary.paused == 1
    assert summary.errors == 1
    assert [task.status for task in errors] == [TaskStatus.ERROR]
    assert [(task.status, task.paused) for task in paused] == [(TaskStatus.PLAN, True)]
    assert paused_count == 1


@pytest.mark.asyncio
async def test_recent_activity_filter_separates_active_tasks_from_history(
    db: AsyncSession,
) -> None:
    marker = f"activity-{uuid4()}"
    db.add_all([
        _task(label=marker, status=TaskStatus.CREATE),
        _task(label=marker, status=TaskStatus.EXEC),
        _task(label=marker, status=TaskStatus.PLAN, paused=True),
        _task(label=marker, status=TaskStatus.SUCCESS),
        _task(label=marker, status=TaskStatus.ERROR),
    ])
    await db.commit()

    active = await task_service.get_recent(search=marker, active=True)
    history = await task_service.get_recent(search=marker, active=False)
    active_count = await task_service.count_recent(search=marker, active=True)
    history_count = await task_service.count_recent(search=marker, active=False)

    assert {task.status for task in active} == {TaskStatus.CREATE, TaskStatus.EXEC}
    assert {task.status for task in history} == {
        TaskStatus.PLAN,
        TaskStatus.SUCCESS,
        TaskStatus.ERROR,
    }
    assert active_count == 2
    assert history_count == 3


@pytest.mark.asyncio
async def test_recent_topic_filter_applies_to_rows_count_and_summary(
    db: AsyncSession,
) -> None:
    topic = Topic(title=f"Topic {uuid4()}")
    other_topic = Topic(title=f"Other {uuid4()}")
    db.add_all([topic, other_topic])
    await db.flush()
    db.add_all([
        _task(topic_id=topic.id, status=TaskStatus.SUCCESS),
        _task(topic_id=topic.id, status=TaskStatus.ERROR),
        _task(topic_id=other_topic.id, status=TaskStatus.EXEC),
    ])
    await db.commit()

    tasks = await task_service.get_recent(topic_id=topic.id)
    count = await task_service.count_recent(topic_id=topic.id)
    total, summary = await task_service.summarize_recent(topic_id=topic.id)

    assert {task.topic_id for task in tasks} == {topic.id}
    assert count == total == 2
    assert summary.completed == 1
    assert summary.errors == 1
    assert summary.running == 0


@pytest.mark.asyncio
async def test_recent_date_range_is_inclusive_and_updates_summary(db: AsyncSession) -> None:
    marker = f"period-{uuid4()}"
    db.add_all([
        _task(
            label=marker,
            status=TaskStatus.SUCCESS,
            created_at=datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc),
        ),
        _task(
            label=marker,
            status=TaskStatus.ERROR,
            created_at=datetime(2025, 3, 1, 23, 59, tzinfo=timezone.utc),
        ),
        _task(
            label=marker,
            status=TaskStatus.DISPATCH,
            created_at=datetime(2025, 3, 2, 0, 0, tzinfo=timezone.utc),
        ),
    ])
    await db.commit()

    tasks = await task_service.get_recent(
        search=marker,
        date_from=date(2025, 2, 1),
        date_to=date(2025, 3, 1),
    )
    total, summary = await task_service.summarize_recent(
        search=marker,
        date_from=date(2025, 2, 1),
        date_to=date(2025, 3, 1),
    )

    assert {task.status for task in tasks} == {TaskStatus.SUCCESS, TaskStatus.ERROR}
    assert total == 2
    assert summary.completed == 1
    assert summary.errors == 1
    assert summary.running == 0


@pytest.mark.asyncio
async def test_recent_tasks_and_children_use_opposite_creation_order(
    db: AsyncSession,
) -> None:
    marker = f"chronology-{uuid4()}"
    oldest = datetime(2025, 1, 1, tzinfo=timezone.utc)
    newest = datetime(2025, 1, 3, tzinfo=timezone.utc)
    older_root = _task(
        label=marker,
        created_at=oldest,
        updated_at=newest,
    )
    newer_root = _task(
        label=marker,
        created_at=newest,
        updated_at=oldest,
    )
    older_child = _task(
        label="older-child",
        parent_id=older_root.id,
        created_at=oldest,
    )
    newer_child = _task(
        label="newer-child",
        parent_id=older_root.id,
        created_at=newest,
    )
    db.add_all([older_root, newer_root, newer_child, older_child])
    await db.commit()

    recent = await task_service.get_recent(search=marker)
    children = await task_service.get_children(older_root.id)

    assert [task.id for task in recent] == [newer_root.id, older_root.id]
    assert [task.id for task in children] == [older_child.id, newer_child.id]


@pytest.mark.asyncio
async def test_delete_soft_deletes_children_before_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(status=TaskStatus.SUCCESS)
    child = _task(parent_id=parent.id, status=TaskStatus.SUCCESS)
    grandchild = _task(parent_id=child.id, status=TaskStatus.SUCCESS)
    sibling = _task(parent_id=parent.id, status=TaskStatus.SUCCESS)
    children_by_parent = {
        parent.id: [child, sibling],
        child.id: [grandchild],
        grandchild.id: [],
        sibling.id: [],
    }
    db = SimpleNamespace(commit=AsyncMock())
    emit = AsyncMock()

    def _children_for(task_id: UUID) -> list[Task]:
        return children_by_parent[task_id]

    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(
        task_service,
        "get_children",
        AsyncMock(side_effect=_children_for),
    )
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    deleted = await task_service.delete(parent.id)

    assert deleted is True
    assert grandchild.deleted_at is not None
    assert child.deleted_at is not None
    assert sibling.deleted_at is not None
    assert parent.deleted_at is not None
    db.commit.assert_awaited_once()
    assert [call.args[2]["id"] for call in emit.await_args_list] == [
        str(grandchild.id),
        str(child.id),
        str(sibling.id),
        str(parent.id),
    ]


@pytest.mark.asyncio
async def test_delete_spares_other_agent_subtree(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deletion does not cross an agent boundary: delegated work owned by another agent survives.
    # Pausing does cascade, though that behavior is not tested here.
    parent = _task(agent_id=1, status=TaskStatus.SUCCESS)
    same_child = _task(parent_id=parent.id, agent_id=1, status=TaskStatus.SUCCESS)
    delegated = _task(parent_id=parent.id, agent_id=2)          # Another agent.
    delegated_child = _task(parent_id=delegated.id, agent_id=2)  # Other agent's subtree.
    children_by_parent = {
        parent.id: [same_child, delegated],
        same_child.id: [],
        delegated.id: [delegated_child],
        delegated_child.id: [],
    }
    db = SimpleNamespace(commit=AsyncMock())
    emit = AsyncMock()
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(
        task_service, "get_children", AsyncMock(side_effect=lambda tid: children_by_parent[tid])
    )
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    await task_service.delete(parent.id)

    assert parent.deleted_at is not None
    assert same_child.deleted_at is not None          # Same agent: deleted.
    assert delegated.deleted_at is None               # Other agent: preserved.
    assert delegated_child.deleted_at is None         # Its subtree is preserved too.
    emitted = [call.args[2]["id"] for call in emit.await_args_list]
    assert emitted == [str(same_child.id), str(parent.id)]


@pytest.mark.asyncio
async def test_pause_tree_marks_non_terminal_descendants(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(status=TaskStatus.PLAN)
    child = _task(parent_id=parent.id, status=TaskStatus.DISPATCH)
    done = _task(parent_id=parent.id, status=TaskStatus.SUCCESS)
    children_by_parent = {parent.id: [child, done], child.id: [], done.id: []}
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    emit = AsyncMock()

    def _children_for(task_id: UUID) -> list[Task]:
        return children_by_parent[task_id]

    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(side_effect=_children_for))
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    result = await task_service.pause_tree(parent.id)

    assert result is parent
    assert parent.paused is True
    assert child.paused is True
    assert done.paused is False
    db.commit.assert_awaited_once()
    assert [call.args[0].id for call in db.refresh.await_args_list] == [parent.id, child.id]
    assert [call.args[2]["id"] for call in emit.await_args_list] == [str(parent.id), str(child.id)]


@pytest.mark.asyncio
async def test_resume_tree_restarts_paused_parent_when_current_child_is_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A plan parent paused by a human may have its current step finish while paused. Resuming it
    # must advance the plan with paused=False and status PLAN.
    parent = _task(
        status=TaskStatus.PLAN,
        paused=True,
        data={"pause_reasons": ["user", "plan"]},
        plan={"steps": [{"label": "A", "objective": "oA"}], "cursor": 0},
    )
    child = _task(parent_id=parent.id, status=TaskStatus.SUCCESS, data={"plan_step": 0})
    children_by_parent = {parent.id: [child], child.id: []}
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    emit = AsyncMock()

    def _children_for(task_id: UUID) -> list[Task]:
        return children_by_parent[task_id]

    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(side_effect=_children_for))
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    result = await task_service.resume_tree(parent.id)

    assert result is parent
    assert parent.paused is False
    assert parent.status == TaskStatus.PLAN
    assert child.status == TaskStatus.SUCCESS
    db.commit.assert_awaited_once()
    assert [call.args[2]["id"] for call in emit.await_args_list] == [str(parent.id)]


@pytest.mark.asyncio
async def test_pause_tree_interrupts_running_action_and_requeues_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pausing interrupts an EXEC task already running in the scheduler and returns it to
    # DISPATCH so it can be restarted after resumption.
    from app.task import scheduler

    running = _task(status=TaskStatus.EXEC)
    idle_child = _task(parent_id=running.id, status=TaskStatus.CREATE)
    children_by_parent = {running.id: [idle_child], idle_child.id: []}
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    emit = AsyncMock()
    cancelled: list[UUID] = []

    def _cancel(task_id: UUID) -> bool:
        cancelled.append(task_id)
        return task_id == running.id  # Only the root is actually running.

    def _children_for(task_id: UUID) -> list[Task]:
        return children_by_parent[task_id]

    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=running))
    monkeypatch.setattr(task_service, "get_children", AsyncMock(side_effect=_children_for))
    monkeypatch.setattr(task_service.websocket, "emit", emit)
    monkeypatch.setattr(scheduler, "cancel", _cancel)

    result = await task_service.pause_tree(running.id)

    assert result is running
    assert running.paused is True
    assert idle_child.paused is True
    # Cancel the running action for every non-terminal descendant.
    assert cancelled == [running.id, idle_child.id]
    # Reclassify the interrupted execution as DISPATCH so it can restart on resume.
    assert running.status == TaskStatus.DISPATCH
    assert idle_child.status == TaskStatus.CREATE
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preempt_running_agent_tasks_requeues_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import scheduler

    running = _task(status=TaskStatus.EXEC, agent_id=7)
    requested = _task(agent_id=7)
    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )
    emit = AsyncMock()

    monkeypatch.setattr(task_service, "get_db", lambda: db)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=running))
    monkeypatch.setattr(task_service.websocket, "emit", emit)
    monkeypatch.setattr(
        scheduler,
        "running_task_ids_for_agent",
        lambda agent_id, *, exclude_task_id=None: [running.id]
        if agent_id == 7 and exclude_task_id == requested.id
        else [],
    )
    monkeypatch.setattr(scheduler, "cancel", lambda task_id: task_id == running.id)

    preempted = await task_service.preempt_running_agent_tasks(
        7,
        exclude_task_id=requested.id,
    )

    assert preempted == [running.id]
    assert running.status == TaskStatus.DISPATCH
    db.commit.assert_awaited_once()
    assert emit.await_args.args[2]["id"] == str(running.id)


@pytest.mark.asyncio
async def test_is_auto_approved_walks_ancestors(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _task(auto_approve=True)
    child = _task(parent_id=root.id)
    grandchild = _task(parent_id=child.id)
    plain = _task()
    by_id = {root.id: root, child.id: child, grandchild.id: grandchild, plain.id: plain}

    monkeypatch.setattr(
        task_service, "get_by_id", AsyncMock(side_effect=lambda tid: by_id.get(tid))
    )

    # A flag on the root covers the entire descendant tree.
    assert await task_service.is_auto_approved(grandchild) is True
    assert await task_service.is_auto_approved(child) is True
    assert await task_service.is_auto_approved(root) is True
    # Without a local flag or flagged ancestor, return False.
    assert await task_service.is_auto_approved(plain) is False


@pytest.mark.asyncio
async def test_is_auto_approved_stops_at_agent_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # auto_approve root for agent 1 -> task for agent 2 -> subtask for agent 2.
    root = _task(auto_approve=True, agent_id=1)
    peer = _task(parent_id=root.id, agent_id=2)
    peer_child = _task(parent_id=peer.id, agent_id=2)
    # A subtask owned by the same agent as the root preserves inheritance.
    same_agent_child = _task(parent_id=root.id, agent_id=1)
    by_id = {root.id: root, peer.id: peer, peer_child.id: peer_child,
             same_agent_child.id: same_agent_child}
    monkeypatch.setattr(
        task_service, "get_by_id", AsyncMock(side_effect=lambda tid: by_id.get(tid))
    )

    # Root auto_approve does not cross the agent boundary.
    assert await task_service.is_auto_approved(peer) is False
    assert await task_service.is_auto_approved(peer_child) is False
    # For the same agent, auto_approve propagates through the subtree.
    assert await task_service.is_auto_approved(root) is True
    assert await task_service.is_auto_approved(same_agent_child) is True


@pytest.mark.asyncio
async def test_apply_source_lineage_nests_under_source(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task()
    goal_id = uuid4()
    source = _task(
        parent_id=parent.id,
        goal_id=goal_id,
        reasoning_effort_override="xhigh",
        data={"language": "fr"},
    )
    monkeypatch.setattr(
        task_service, "get_by_id", AsyncMock(return_value=source)
    )

    new = TaskCreate(label="Continuation", objective="obj")
    await task_service.apply_source_lineage(new, source.id)

    assert new.source_task_id == source.id
    # Call-stack model: a delegated subtask becomes a direct child of its creator rather than
    # a sibling, even when the source already has a parent.
    assert new.parent_id == source.id
    assert (new.data or {}).get("delegated") is True
    assert (new.data or {}).get("language") == "fr"
    assert new.goal_id == goal_id
    assert new.reasoning_effort_override == "xhigh"


@pytest.mark.asyncio
async def test_apply_goal_lineage_inherits_parent_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal_id = uuid4()
    parent = _task(goal_id=goal_id)
    db = SimpleNamespace(scalar=AsyncMock(return_value=goal_id))
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    new = TaskCreate(label="Planned child", objective="obj", parent_id=parent.id)

    await task_service.apply_goal_lineage(new)

    assert new.goal_id == goal_id
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_goal_lineage_preserves_explicit_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_goal_id = uuid4()
    lookup = AsyncMock()
    monkeypatch.setattr(task_service, "get_by_id", lookup)
    new = TaskCreate(
        label="Explicit lineage",
        objective="obj",
        parent_id=uuid4(),
        goal_id=explicit_goal_id,
    )

    await task_service.apply_goal_lineage(new)

    assert new.goal_id == explicit_goal_id
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_reasoning_effort_override_is_inherited_from_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_id = uuid4()
    db = SimpleNamespace(scalar=AsyncMock(return_value="xhigh"))
    monkeypatch.setattr(task_service, "get_db", lambda: db)
    new = TaskCreate(label="Planned child", objective="obj", parent_id=parent_id)

    await task_service.apply_reasoning_effort_lineage(new)

    assert new.reasoning_effort_override == "xhigh"
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_source_lineage_preserves_explicit_child_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _task(data={"language": "fr"})
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=source))

    new = TaskCreate(
        label="English deliverable",
        objective="Write in English",
        data={"language": "en"},
    )
    await task_service.apply_source_lineage(new, source.id)

    assert (new.data or {}).get("language") == "en"


@pytest.mark.asyncio
async def test_apply_source_lineage_root_source_becomes_child(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _task()  # Root task (parent_id=None).
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=source))

    new = TaskCreate(label="Continuation", objective="obj")
    await task_service.apply_source_lineage(new, source.id)

    # With a root source, the new task becomes a true child subtask.
    assert new.source_task_id == source.id
    assert new.parent_id == source.id


@pytest.mark.asyncio
async def test_apply_source_lineage_none_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    called = AsyncMock()
    monkeypatch.setattr(task_service, "get_by_id", called)

    new = TaskCreate(label="Root", objective="obj")
    await task_service.apply_source_lineage(new, None)

    assert new.source_task_id is None
    assert new.parent_id is None
    called.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_source_lineage_keeps_explicit_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    explicit_parent = uuid4()
    source_parent = _task()
    source = _task(parent_id=source_parent.id)
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=source))

    new = TaskCreate(label="Continuation", objective="obj", parent_id=explicit_parent)
    await task_service.apply_source_lineage(new, source.id)

    # Never overwrite an existing parent.
    assert new.source_task_id == source.id
    assert new.parent_id == explicit_parent


@pytest.mark.asyncio
async def test_approval_action_denies_agent_interlocutor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=None))

    # Ask a human caller without auto_approve for approval in the room.
    assert await task_service.approval_action(_task(ai=False)) == "ask"
    # Refuse an AI-agent caller without auto_approve; agents cannot grant approval.
    assert await task_service.approval_action(_task(ai=True)) == "deny_agent"


@pytest.mark.asyncio
async def test_approval_action_auto_approve_beats_agent_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=None))

    # Explicit auto_approve takes precedence even in an agent-to-agent conversation.
    assert await task_service.approval_action(_task(ai=True, auto_approve=True)) == "auto"


@pytest.mark.asyncio
async def test_approval_action_auto_approve_inherited_from_ancestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _task(auto_approve=True)
    child = _task(ai=True, parent_id=root.id)
    by_id = {root.id: root, child.id: child}
    monkeypatch.setattr(
        task_service, "get_by_id", AsyncMock(side_effect=lambda tid: by_id.get(tid))
    )

    # An ancestor's auto_approve covers the agent-to-agent subtask.
    assert await task_service.approval_action(child) == "auto"
