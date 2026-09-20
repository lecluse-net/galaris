import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import get_db_session
from app.agent.contracts import HarnessCancellationReceipt
from app.task import replacement, scheduler, task_service
from app.task.models import Task, TaskAttempt, TaskStatus


def task(**values):
    return Task(id=uuid4(), label="Report", objective="<p>Prepare report.</p>",
                status=values.pop("status", TaskStatus.CREATE), **values)


@pytest.mark.asyncio
async def test_queued_replacement_is_durable_idempotent_and_preserves_other_holds(committed_database, monkeypatch):
    monkeypatch.setattr(scheduler, "wake", lambda *_: None)
    async with get_db_session() as db:
        original = task(data={"receipt": "delivered"})
        independent = task()
        db.add_all([original, independent])
        await db.flush()
        original_id, revision = original.id, original.revision
    async with get_db_session() as db:
        successor = task()
        accepted = await replacement.prepare_replacement(successor, predecessor_id=original_id,
            expected_revision=revision, action_key="replace-once")
        assert accepted is successor and successor.paused
        successor_id = successor.id
    # A new worker replays the admission, then recovers from the durable queue.
    async with get_db_session() as db:
        replay = await replacement.prepare_replacement(task(), predecessor_id=original_id,
            expected_revision=revision, action_key="replace-once")
        assert replay.id == successor_id
        task_service.suspend(replay, "user")
    async with get_db_session():
        await replacement.reconcile_replacements()
        await replacement.reconcile_replacements()
    async with get_db_session() as db:
        successor = await db.get(Task, successor_id)
        original = await db.get(Task, original_id)
        assert replacement.replacement_state(successor)["state"] == "confirmed"
        assert task_service.pause_reasons(successor) == ["user"]
        assert original.status == TaskStatus.ERROR and original.data["receipt"] == "delivered"
        assert (await db.get(Task, independent.id)).status == TaskStatus.CREATE
        assert len(list(await db.scalars(select(Task)))) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["requested", "unknown", "confirmed"])
async def test_remote_replacement_requires_confirmed_stop_and_released_lease(db, monkeypatch, state):
    run_id, token = uuid4(), uuid4()
    original = task(status=TaskStatus.EXEC, lease_token=token,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        data={"_agent_run_identity": {"driver_code": "remote", "request_run_id": str(run_id)}})
    db.add(original)
    await db.commit()
    successor = task()
    await replacement.prepare_replacement(successor, predecessor_id=original.id,
        expected_revision=original.revision, action_key="one")
    await db.commit()
    control = AsyncMock(return_value=HarnessCancellationReceipt(run_id=run_id, scope="remote", state=state))
    monkeypatch.setattr(replacement, "cancel_agent_run", control)
    monkeypatch.setattr(scheduler, "wake", lambda *_: None)
    await replacement.reconcile_replacements()
    assert successor.paused  # A remote receipt alone cannot release the local worker's slot.
    original.lease_token = None
    original.lease_expires_at = None
    await db.commit()
    await replacement.reconcile_replacements()
    await db.refresh(successor)
    assert replacement.replacement_pending(successor) is (state != "confirmed")
    assert successor.paused is (state != "confirmed")


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["scope", "revision", "child", "process", "leased_child", "grandchild"])
async def test_replacement_conflict_never_stops_or_creates_work(db, blocker):
    original = task(message_group_id="room-a")
    db.add(original)
    await db.flush()
    if blocker == "child":
        db.add(task(parent_id=original.id))
    if blocker == "leased_child":
        db.add(task(parent_id=original.id, status=TaskStatus.ERROR, lease_token=uuid4()))
    if blocker == "grandchild":
        child = task(parent_id=original.id, status=TaskStatus.SUCCESS)
        db.add(child)
        await db.flush()
        db.add(task(parent_id=child.id))
    if blocker == "process":
        original.data = {"awaiting_reply": {"kind": "process"}}
    await db.commit()
    count = len(list(await db.scalars(select(Task))))
    successor = task(message_group_id="room-b" if blocker == "scope" else "room-a")
    with pytest.raises(task_service.TaskConflictError):
        await replacement.prepare_replacement(successor, predecessor_id=original.id,
            expected_revision=original.revision - (1 if blocker == "revision" else 0), action_key="one")
    assert original.status == TaskStatus.CREATE
    assert len(list(await db.scalars(select(Task)))) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "restart", "new_run", "child", "process"])
async def test_replacement_does_not_follow_a_changed_predecessor(db, monkeypatch, change):
    original = task(message_group_id="room-a")
    db.add(original)
    await db.commit()
    successor = await replacement.prepare_replacement(task(message_group_id="room-a"),
        predecessor_id=original.id, expected_revision=original.revision, action_key="one")
    await db.commit()
    if change == "scope":
        original.message_group_id = "room-b"
    elif change == "restart":
        original.status = TaskStatus.CREATE
    elif change == "child":
        db.add(task(parent_id=original.id))
    elif change == "process":
        original.data = {**original.data, "awaiting_reply": {"kind": "process"}}
    else:
        original.data = {**original.data, "_agent_run_identity": {
            "driver_code": "remote", "request_run_id": str(uuid4())}}
    await db.commit()
    control = AsyncMock()
    monkeypatch.setattr(replacement, "cancel_agent_run", control)
    await replacement.reconcile_replacements()
    assert successor.paused
    assert replacement.replacement_state(successor)["state"] == "conflict"
    control.assert_not_called()


@pytest.mark.asyncio
async def test_removing_pause_cannot_bypass_pending_replacement(db, monkeypatch):
    from app.agent.models import Agent, Title
    import app.agent as agent_domain

    title = Title(label="Replacement owner", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(title_id=title.id, first_name="Queue", last_name="Owner",
                  code=f"replacement-{uuid4().hex}")
    db.add(owner)
    await db.flush()
    original = task(agent_id=owner.id)
    db.add(original)
    await db.commit()
    successor = await replacement.prepare_replacement(task(agent_id=owner.id),
        predecessor_id=original.id, expected_revision=original.revision, action_key="one")
    task_service.clear_pauses(successor)
    successor.status = TaskStatus.DISPATCH
    await db.commit()
    monkeypatch.setattr(agent_domain, "max_parallel_tasks_for_agent", AsyncMock(return_value=None))
    with pytest.raises(scheduler.InlineClaimUnavailable):
        await scheduler.claim_inline_execution(successor.id)
    assert successor.lease_token is None
    assert successor.attempt_count == 0


@pytest.mark.asyncio
async def test_cancelled_worker_waits_for_command_commit_before_recording_stop(committed_database):
    token = uuid4()
    async with get_db_session() as db:
        original = task(status=TaskStatus.ERROR, lease_token=token)
        db.add(original)
        await db.flush()
        identifier = original.id
        attempt = TaskAttempt(task_id=identifier, attempt_number=1, phase="EXEC",
            status="CLAIMED", lease_token=token, worker_id="old")
        db.add(attempt)
    entered = asyncio.Event()
    async def release():
        entered.set()
        await scheduler._release_cancelled_claim(identifier, token)
    async with get_db_session() as db:
        await db.scalar(select(Task).where(Task.id == identifier).with_for_update())
        pending = asyncio.create_task(release())
        await entered.wait()
        await db.commit()
    await asyncio.wait_for(pending, 3)
    async with get_db_session() as db:
        original = await db.get(Task, identifier)
        attempt = await db.scalar(select(TaskAttempt).where(TaskAttempt.task_id == identifier))
        assert original.lease_token is None
        assert attempt.status == "CANCELLED"
        assert attempt.data["local_execution_stopped"] is True


@pytest.mark.asyncio
async def test_task_heartbeat_cannot_resurrect_an_expired_owner(db):
    token = uuid4()
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    original = task(lease_token=token, lease_expires_at=expired)
    db.add(original)
    await db.commit()
    assert not await scheduler._renew_lease(original.id, token)
    await db.refresh(original)
    assert original.lease_expires_at == expired


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted_terminal", [False, True])
async def test_a_failed_run_event_is_not_itself_stop_evidence(db, monkeypatch, accepted_terminal):
    run_id, attempt_id = uuid4(), uuid4()
    original = task(status=TaskStatus.ERROR, data={"_agent_run_identity": {
        "driver_code": "remote-test", "request_run_id": str(run_id), "attempt_id": str(attempt_id)}})
    db.add(original)
    await db.flush()
    db.add(TaskAttempt(id=attempt_id, task_id=original.id, attempt_number=1, phase="EXEC",
        status="ERROR", worker_id="old", lease_token=uuid4(), finished_at=datetime.now(timezone.utc),
        data={"agent_events": [{"kind": "run.failed", "identity": {"run_id": str(run_id)},
            "payload": {"execution_stopped": True} if accepted_terminal else {}}]}))
    await db.commit()
    successor = await replacement.prepare_replacement(task(), predecessor_id=original.id,
        expected_revision=original.revision, action_key="one")
    await db.commit()
    monkeypatch.setattr(replacement, "cancel_agent_run", AsyncMock(return_value=HarnessCancellationReceipt(
        run_id=run_id, scope="remote", state="requested")))
    monkeypatch.setattr(scheduler, "wake", lambda *_: None)
    await replacement.reconcile_replacements()
    assert successor.paused is (not accepted_terminal)


@pytest.mark.asyncio
async def test_local_successor_waits_for_cleanup_and_survives_worker_restart(committed_database, monkeypatch):
    token, run_id, attempt_id = uuid4(), uuid4(), uuid4()
    entered, cleaning, finish_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def action(*_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish_cleanup.wait()
    monkeypatch.setattr(scheduler, "_run_action", action)
    monkeypatch.setattr(scheduler, "wake", lambda *_: None)
    control = AsyncMock(return_value=HarnessCancellationReceipt(run_id=run_id, scope="local", state="unknown"))
    monkeypatch.setattr(replacement, "cancel_agent_run", control)
    async with get_db_session() as db:
        original = task(status=TaskStatus.EXEC, lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            data={"_agent_run_identity": {"driver_code": "embedded-test", "local_interrupt": True,
                  "request_run_id": str(run_id), "attempt_id": str(attempt_id)}})
        db.add(original)
        await db.flush()
        original_id = original.id
        db.add(TaskAttempt(id=attempt_id, task_id=original_id, attempt_number=1,
            phase="EXEC", status="CLAIMED", lease_token=token, worker_id="local"))
    worker = asyncio.create_task(scheduler._run_claimed_action(original_id, TaskStatus.EXEC, token))
    monkeypatch.setitem(scheduler._running, original_id, worker)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with get_db_session() as db:
            original = await db.get(Task, original_id)
            successor = await replacement.prepare_replacement(task(), predecessor_id=original_id,
                expected_revision=original.revision, action_key="once")
            successor_id = successor.id
        await asyncio.wait_for(cleaning.wait(), 3)
        async with get_db_session() as db:
            await replacement.reconcile_replacements()
            assert (await db.get(Task, successor_id)).paused
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(worker, 3)
        # No live registry or process-local cancellation receipt is needed for recovery.
        async with get_db_session() as db:
            await replacement.reconcile_replacements()
            successor = await db.get(Task, successor_id)
            assert not successor.paused
            assert replacement.replacement_state(successor)["state"] == "confirmed"
            assert (await db.get(TaskAttempt, attempt_id)).data["local_execution_stopped"] is True
    finally:
        finish_cleanup.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
