from types import SimpleNamespace
import asyncio
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
@pytest.mark.parametrize("failure", ["revision", "goal", "notification", "lifecycle", "timeout"])
async def test_force_termination_survives_stale_views_and_failed_followups(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    from app import agent as agent_domain
    from app.goal import facade as goal_facade
    from app.task import scheduler

    token = uuid4()
    task = _task(status=TaskStatus.EXEC, lease_token=token, lease_owner="stuck-worker",
        paused=True, next_attempt_at=datetime.now(timezone.utc),
        data={"pause_reasons": [task_service.PAUSE_USER]})
    attempt = TaskAttempt(task=task, attempt_number=1, phase="EXEC",
        worker_id="stuck-worker", lease_token=token)
    db.add_all([task, attempt])
    await db.commit()
    task_id, attempt_id, revision = task.id, attempt.id, task.revision
    monkeypatch.setattr(scheduler, "cancel", lambda _: True)
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    monkeypatch.setattr(agent_domain, "handle_terminal_task", AsyncMock())
    if failure == "goal":
        monkeypatch.setattr(goal_facade, "lock_cycle_for_forced_task",
            AsyncMock(side_effect=RuntimeError("Synthetic unavailable Goal")))
    elif failure == "notification":
        monkeypatch.setattr(task_service.websocket, "emit",
            AsyncMock(side_effect=RuntimeError("Synthetic unavailable websocket")))
    elif failure in {"lifecycle", "timeout"}:
        async def broken_lifecycle(_task):
            # A failing followup must never roll back the durable stop.
            task.feedback = "Synthetic uncommitted followup"
            await db.flush()
            if failure == "timeout":
                await asyncio.Future()
            raise RuntimeError("Synthetic unavailable lifecycle")
        monkeypatch.setattr(agent_domain, "handle_terminal_task", broken_lifecycle)
        monkeypatch.setattr(task_service, "_FORCE_TERMINATE_FOLLOWUP_TIMEOUT", 0.05, raising=False)

    result = await task_service.force_terminate(task_id, revision - 1 if failure == "revision" else revision)

    assert result is not None and result.status == TaskStatus.ERROR
    await db.refresh(task)
    await db.refresh(attempt)
    assert task.status == TaskStatus.ERROR and not task.paused
    assert task.lease_token is None and task.lease_owner is None
    assert task.lease_expires_at is None and not task.cancel_requested
    assert task.next_attempt_at is None
    assert task.feedback == task.last_error
    assert attempt.status == TaskAttemptStatus.CANCELLED.value
    assert attempt.finished_at is not None and not attempt.retryable
    assert attempt.data["force_terminated"] is True
    repeated = await task_service.force_terminate(task_id, revision)
    assert repeated is not None and repeated.revision == result.revision


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
async def test_retry_nested_finished_plan_reopens_failed_leaf_without_replaying_success(db, monkeypatch):
    from app.agent import planner_service

    root = _task(status=TaskStatus.ERROR, plan={"steps": [{}, {}], "cursor": 2})
    done = _task(parent_id=root.id, status=TaskStatus.SUCCESS, data={"plan_step": 0},
                 execution_result={"prompt": "", "result": "Saved", "success": True})
    group = _task(parent_id=root.id, status=TaskStatus.ERROR, data={"plan_step": 1},
                  plan={"steps": [{}], "cursor": 1})
    leaf = _task(parent_id=group.id, status=TaskStatus.ERROR, data={"plan_step": 0},
                 last_error="ReasoningDegenerationError: synthetic repeated reasoning", feedback="Previous failure")
    db.add_all([root, done, group, leaf])
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    monkeypatch.setattr(planner_service, "go_next", lambda *_: None)
    monkeypatch.setattr(planner_service, "_synthesize", AsyncMock(return_value=("Synthetic failure", 0.0)))

    await task_service.retry(root.id, root.revision)
    await planner_service.advance(root)
    await planner_service.advance(group)

    assert done.status == TaskStatus.SUCCESS
    assert done.get_execution_result().result == "Saved"
    assert root.plan["cursor"] == 1
    assert group.plan["cursor"] == 0
    assert leaf.status == TaskStatus.DISPATCH and not leaf.paused
    assert leaf.last_error is None
    assert leaf.data["reasoning_recovery_requested"] is True


@pytest.mark.asyncio
async def test_retry_plan_keeps_unmaterialized_work_and_completed_group_reports(db, monkeypatch):
    root = _task(status=TaskStatus.ERROR, plan={"steps": [{}, {}], "cursor": 2})
    done_group = _task(parent_id=root.id, status=TaskStatus.SUCCESS, data={"plan_step": 0},
                       plan={"steps": [{"run_after_failure": True}], "cursor": 1})
    done_report = _task(parent_id=done_group.id, status=TaskStatus.SUCCESS, data={"plan_step": 0},
                        execution_result={"prompt": "", "result": "Saved report", "success": True})
    db.add_all([root, done_group, done_report])
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    await task_service.retry(root.id, root.revision)

    assert root.plan["cursor"] == 1  # A missing child is unfinished work.
    assert done_group.status == TaskStatus.SUCCESS
    assert done_report.status == TaskStatus.SUCCESS and not done_report.paused
    assert done_report.get_execution_result().result == "Saved report"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["UnsafeCheckpointError", "ReasoningDegenerationError"])
async def test_retry_preserves_uncertain_effects_and_durable_working_set(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
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
                "driver_code": "internal",
                "runtime_run_id": "synthetic-internal-run",
                "status": "running",
                "data": {
                    "version": 5,
                    "resume_safe": False,
                    "effects": [{"tool_name": "file_create", "status": "started"}],
                },
            },
        },
        execution_result={"prompt": "old", "result": "failed", "success": False},
        feedback="Previous failure",
        last_error=failure,
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
    assert bool(retried.data.get("reasoning_recovery_requested")) is (failure == "ReasoningDegenerationError")
    assert retried.data["_agent_run_checkpoint"]["data"]["effects"] == [
        {"tool_name": "file_create", "status": "started"}
    ]
    assert retried.data["_agent_run_checkpoint"]["result"] is None
    assert retried.data["working_set"]["resources"][0]["reference"] == (
        "document://existing"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("planned", [False, True])
@pytest.mark.parametrize("status", ["completed", "failed", "outcome_unknown", "cancelled", "running", "waiting_for_authorization"])
async def test_retry_starts_fresh_managed_operation_on_same_task_and_keeps_evidence(db, monkeypatch, planned, status):
    from copy import deepcopy

    checkpoint = {"request_run_id": str(uuid4()), "driver_code": "openai_messages", "runtime_run_id": "a" * 64,
        "status": status, "data": {"version": 1, "run_context": "synthetic-authority"}}
    failed = _task(status=TaskStatus.ERROR, data={"_agent_run_checkpoint": checkpoint},
        execution_result={"prompt": "", "result": "Original runtime failure", "success": False},
        last_error="Original runtime failure", attempt_count=1)
    root = _task(status=TaskStatus.ERROR, plan={"steps": [{}], "cursor": 1}) if planned else failed
    if planned:
        failed.parent_id = root.id
        failed.data = {**failed.data, "plan_step": 0}
        db.add(root)
    db.add(failed)
    await db.commit()
    failed_id, root_id, revision = failed.id, root.id, root.revision
    saved_checkpoint = deepcopy(checkpoint)
    original_parameters = (failed.label, failed.objective, failed.agent_id, failed.effort,
                           failed.forced_route, failed.forced_effort)
    emit = AsyncMock()
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    await task_service.retry(root_id, revision)

    await db.refresh(failed)
    await db.refresh(root)
    assert failed.id == failed_id
    assert failed.status == TaskStatus.DISPATCH
    assert failed.last_error is None and failed.execution_result is None
    assert failed.data['_agent_run_retry_checkpoint'] == saved_checkpoint
    assert '_agent_run_checkpoint' not in failed.data
    assert '_agent_run_identity' not in failed.data
    assert failed.attempt_count == 1
    assert (failed.label, failed.objective, failed.agent_id, failed.effort,
            failed.forced_route, failed.forced_effort) == original_parameters


@pytest.mark.asyncio
@pytest.mark.parametrize("planned", [False, True])
@pytest.mark.parametrize("driver", ["internal", "hermes", "openai_messages"])
async def test_retry_preserves_driver_recovery_and_remote_effect_receipts(db, monkeypatch, planned, driver):
    from copy import deepcopy
    from app.agent import has_resumable_run_checkpoint

    remote = driver != "internal"
    payload = {
        "internal": {"version": 5, "resume_safe": True,
                     "effects": [{"status": "completed", "tool_name": "file_create"}],
                     "message_history": []},
        "hermes": {"execution_strategy": "direct", "cancellation_target": {"url": "http://example.test"}},
        "openai_messages": {"version": 1, "run_context": "synthetic-encrypted-authority",
                            "cursor": {"messages": 2, "text": 8}},
    }[driver]
    checkpoint = {
        "schema_version": 1, "driver_code": driver, "runtime_run_id": "a" * 64,
        "status": "waiting_for_authorization" if remote else "failed", "data": payload,
        "result": {"prompt": "<p>Synthetic objective</p>", "result": "Recorded tool receipt",
                   "success": False, "tools_used": ["file_create"]},
    }
    original = deepcopy(checkpoint)
    failed = _task(status=TaskStatus.ERROR, data={"_agent_run_checkpoint": checkpoint},
                   execution_result={"prompt": "", "result": "Previous failure", "success": False})
    if planned:
        root = _task(status=TaskStatus.ERROR, plan={"steps": [{}], "cursor": 1})
        failed.parent_id = root.id
        failed.data = {**failed.data, "plan_step": 0}
        db.add(root)
    else:
        root = failed
    db.add(failed)
    await db.commit()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    await task_service.retry(root.id, root.revision)
    await db.refresh(failed)

    if driver == "openai_messages":
        assert failed.data["_agent_run_retry_checkpoint"] == original
        assert "_agent_run_checkpoint" not in failed.data
        assert not has_resumable_run_checkpoint(failed)
        assert failed.execution_result is None
        return
    saved = failed.data["_agent_run_checkpoint"]
    assert has_resumable_run_checkpoint(failed)
    assert saved["runtime_run_id"] == original["runtime_run_id"]
    assert saved["data"] == original["data"]
    if remote:
        assert saved == original  # The remote actor and its effect evidence remain authoritative.
    else:
        assert saved["result"] is None and saved["status"] == "interrupted"
    assert failed.execution_result is None


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
    for state in ({"errors_only": True}, {"paused_only": True}, {"active": True},
                  {"active": False}, {"paused_only": True, "active": True},
                  {"errors_only": True, "active": False}):
        page_total, overview = await task_service.summarize_recent(search=marker, **state)
        assert page_total == await task_service.count_recent(search=marker, **state)
        assert overview == summary


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
async def test_pause_tree_marks_non_terminal_descendants(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(status=TaskStatus.PLAN)
    child = _task(parent_id=parent.id, status=TaskStatus.DISPATCH)
    done = _task(parent_id=parent.id, status=TaskStatus.SUCCESS)
    db.add_all([parent, child, done])
    await db.flush()
    emit = AsyncMock()
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    result = await task_service.pause_tree(parent.id)

    assert result is parent
    assert parent.paused is True
    assert child.paused is True
    assert done.paused is False
    # Persistence is the guarantee; individual refresh calls are incidental.
    await db.refresh(child)
    assert child.paused is True
    assert [call.args[2]["id"] for call in emit.await_args_list] == [str(parent.id), str(child.id)]


@pytest.mark.asyncio
async def test_resume_tree_restarts_paused_parent_when_current_child_is_done(
    db: AsyncSession,
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
    db.add_all([parent, child])
    await db.flush()
    emit = AsyncMock()
    monkeypatch.setattr(task_service.websocket, "emit", emit)

    result = await task_service.resume_tree(parent.id)

    assert result is parent
    assert parent.paused is False
    assert parent.status == TaskStatus.PLAN
    assert child.status == TaskStatus.SUCCESS
    await db.refresh(parent)
    assert not parent.paused and parent.status == TaskStatus.PLAN
    assert [call.args[2]["id"] for call in emit.await_args_list] == [str(parent.id)]


@pytest.mark.asyncio
async def test_pause_tree_interrupts_running_action_and_requeues_exec(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pausing interrupts an EXEC task already running in the scheduler and returns it to
    # DISPATCH so it can be restarted after resumption.
    from app.task import scheduler

    running = _task(status=TaskStatus.EXEC)
    idle_child = _task(parent_id=running.id, status=TaskStatus.CREATE)
    db.add_all([running, idle_child])
    await db.flush()
    emit = AsyncMock()
    cancelled: list[UUID] = []

    def _cancel(task_id: UUID) -> bool:
        cancelled.append(task_id)
        return task_id == running.id  # Only the root is actually running.

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
    await db.refresh(running)
    assert running.paused and running.status == TaskStatus.DISPATCH


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

    # Historical flags are readable but grant no authority, including to descendants.
    assert await task_service.is_auto_approved(grandchild) is False
    assert await task_service.is_auto_approved(child) is False
    assert await task_service.is_auto_approved(root) is False
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
    # Same-agent lineage does not restore retired authority either.
    assert await task_service.is_auto_approved(root) is False
    assert await task_service.is_auto_approved(same_agent_child) is False


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
    # The current manager receives the request even when work originates from an agent.
    assert await task_service.approval_action(_task(ai=True)) == "ask"


@pytest.mark.asyncio
async def test_approval_action_auto_approve_beats_agent_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=None))

    # Historical approval flags cannot authorize agent-to-agent work.
    assert await task_service.approval_action(_task(ai=True, auto_approve=True)) == "ask"


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

    # An ancestor cannot grant one-action authority to a subtask.
    assert await task_service.approval_action(child) == "ask"
