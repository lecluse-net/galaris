"""Persisted work wakes the runtime after commit, independently of UI callers."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event

from core.database import get_db_session
from core.user import UserModel
from app.conversation import scheduler as conversations
from app.conversation.models import ConversationRound, ConversationTaskLink, ConversationProcessLink
from app.conversation.tests.test_service import _scope
from app.process import ProcessDefinition, ProcessRun
from app.task import Task, TaskStatus, scheduler as tasks


async def scope(db):
    user = UserModel(email=f"wake-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    return await _scope(db, user_id=user.id)


@pytest_asyncio.fixture
async def parked_schedulers(committed_database, monkeypatch):
    # Isolate notification delivery from execution; the real ORM transactions,
    # post-commit observers and scheduler wake functions remain in the workflow.
    async def parked():
        await asyncio.Event().wait()

    monkeypatch.setattr(tasks, "_run_loop", parked)
    monkeypatch.setattr(conversations, "_run_loop", parked)
    tasks.start()
    conversations.start()
    try:
        yield tasks._wake_event, conversations._wake_event
    finally:
        await conversations.stop()
        await tasks.stop()


@pytest.mark.asyncio
async def test_task_admission_rollback_resume_and_completion_wake_after_commit(parked_schedulers):
    task_wake, conversation_wake = parked_schedulers
    async with get_db_session() as db:
        agent, _, _ = await scope(db)
        await db.commit()
        task = Task(label="Synthetic work", objective="Observe notifications", agent_id=agent.id,
                    status=TaskStatus.CREATE, paused=True)
        db.add(task)
        await db.flush()
        assert not task_wake.is_set()
        await db.commit()
        await asyncio.wait_for(task_wake.wait(), 1)
        await asyncio.wait_for(conversation_wake.wait(), 1)
        task_wake.clear()
        conversation_wake.clear()

        task.paused = False
        await db.flush()
        assert not task_wake.is_set()
        await db.rollback()
        await db.refresh(task)
        await db.commit()
        await asyncio.sleep(0)
        assert not task_wake.is_set()

        task.paused = False
        await db.commit()
        await asyncio.wait_for(task_wake.wait(), 1)
        task_wake.clear()
        # Renewing a lease does not rescan either work queue.
        task.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        await db.commit()
        await asyncio.sleep(0)
        assert not task_wake.is_set()
        assert not conversation_wake.is_set()

        task.status = TaskStatus.SUCCESS
        await db.commit()
        await asyncio.wait_for(task_wake.wait(), 1)
        await asyncio.wait_for(conversation_wake.wait(), 1)


@pytest.mark.asyncio
async def test_conversation_links_delivery_retries_and_process_completion_wake(parked_schedulers):
    _, wake = parked_schedulers
    async with get_db_session() as db:
        agent, connection, room = await scope(db)
        round_ = ConversationRound(room_id=room.id, status="FROZEN")
        task = Task(label="Synthetic result", agent_id=agent.id, status=TaskStatus.CREATE)
        definition = ProcessDefinition(tool_id=connection.tool_id, engine_process_id="wake-test", label="Wake test")
        db.add_all([round_, task, definition])
        await db.flush()
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id,
                         engine_code="fake", status="running", launch_snapshot={},
                         correlation_id=str(uuid4()), callback_token="synthetic-callback")
        db.add(run)
        await db.commit()
        await asyncio.wait_for(wake.wait(), 1)
        wake.clear()
        for link in (
            ConversationTaskLink(round_id=round_.id, task_id=task.id, action_key="task", notification_state="UNKNOWN"),
            ConversationProcessLink(round_id=round_.id, process_run_id=run.id, action_key="process", notification_state="UNKNOWN"),
        ):
            db.add(link)
            await db.flush()
            assert not wake.is_set()
            await db.commit()
            await asyncio.wait_for(wake.wait(), 1)
            wake.clear()
            link.notification_state = "IDLE" if isinstance(link, ConversationTaskLink) else "PENDING"
            await db.commit()
            await asyncio.wait_for(wake.wait(), 1)
            wake.clear()
        round_.status = "ERROR_RESOLVED"
        round_.delivery_state = "PENDING"
        await db.commit()
        await asyncio.wait_for(wake.wait(), 1)
        wake.clear()
        run.status = "success"
        await db.commit()
        await asyncio.wait_for(wake.wait(), 1)


@pytest.mark.asyncio
async def test_idle_schedulers_do_not_query_and_maintenance_does_not_rescan_tasks(
    committed_database, monkeypatch,
):
    # Real empty database, real claim queries; only the maintenance callback is synthetic.
    await tasks.stop()
    await conversations.stop()
    monkeypatch.setattr(tasks, "_periodic_jobs", {})
    monkeypatch.setattr(tasks, "_periodic_last_run", {})
    monkeypatch.setattr(tasks, "_last_reconcile", 0.0)
    maintained = asyncio.Event()

    async def maintenance():
        maintained.set()

    tasks.register_periodic_job("synthetic", maintenance, interval=0.5)
    async with get_db_session() as db:
        engine = db.bind.sync_engine
    queries = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        queries.append(statement)

    tasks.start()
    conversations.start()
    try:
        await asyncio.wait_for(maintained.wait(), 5)
        # Allow initial recovery/queue scans to finish before measuring idleness.
        await asyncio.sleep(0.5)
        maintained.clear()
        event.listen(engine, "before_cursor_execute", record)
        await asyncio.sleep(1.2)
        assert maintained.is_set(), "Periodic maintenance must keep running"
        assert queries == [], f"{len(queries)} queries while both queues were idle"
    finally:
        event.remove(engine, "before_cursor_execute", record)
        await conversations.stop()
        await tasks.stop()


@pytest.mark.asyncio
async def test_persisted_retry_deadline_survives_restart_without_a_local_timer(committed_database):
    async with get_db_session() as db:
        agent, _, _ = await scope(db)
        db.add(Task(id=uuid4(), label="Delayed work", agent_id=agent.id, status=TaskStatus.DISPATCH,
                    next_attempt_at=datetime.now(timezone.utc) + timedelta(seconds=3)))
    assert 0 < await tasks._next_scan_delay() <= 3
