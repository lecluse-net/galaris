"""Real PostgreSQL worker races; no shared rollback transaction or fake locks."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation.models import ConversationRound, ConversationRoundMessage
from app.conversation.service import (
    claim_next_round, renew_round_lease, build_turn, complete_round,
    fail_round, mark_effect_if_fresh, round_attempt_succeeded,
)
from app.conversation.contracts import ConversationLeaseLostError, ConversationOutcome
from app.messenger.models import Message, Room
from app.tools.models import Tool
from app.task import scheduler as task_scheduler
from app.task.models import Task, TaskAttempt, TaskStatus
from core.database import get_db_session
from core.user.models import User


async def seed_round():
    suffix = uuid4().hex
    async with get_db_session() as db:
        user = User(email=f"{suffix}@example.test", hashed_password="unused")
        title = Title(label=suffix, gender="X")
        tool = Tool(code=suffix, label=suffix, description="", connection_schema={})
        db.add_all([user, title, tool])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, first_name="Race", last_name="Test", code=suffix)
        db.add(agent)
        await db.flush()
        connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        room = Room(connection_id=connection.id, external_id=suffix, label="Race room", kind="direct", conversation_type="text")
        db.add(room)
        await db.flush()
        message = Message(connection_id=connection.id, tool_id=tool.id, platform="internal", remote_message_id=suffix, direction="inbound", messenger_room_id=room.id, room_id=suffix, text="race")
        round_ = ConversationRound(room_id=room.id, status="FROZEN")
        db.add_all([message, round_])
        await db.flush()
        db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
        return round_.id


@pytest.mark.asyncio
async def test_independent_workers_claim_a_round_once(committed_database):
    round_id = await seed_round()
    barrier = asyncio.Barrier(2)

    async def worker(name):
        async with get_db_session() as db:
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            await barrier.wait()
            claim = await claim_next_round(name)
            return pid, claim.id if claim else None

    async with asyncio.timeout(10):
        results = await asyncio.gather(worker("one"), worker("two"))
    assert results[0][0] != results[1][0], "Must exercise distinct PostgreSQL connections"
    assert [row[1] for row in results if row[1] is not None] == [round_id]
    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        assert round_.attempt_count == 1
        assert round_.lease_owner in {"one", "two"}


@pytest.mark.asyncio
@pytest.mark.parametrize("effect_started", [False, True])
async def test_expired_worker_cannot_renew_after_recovery(committed_database, effect_started):
    round_id = await seed_round()
    async with get_db_session():
        original = await claim_next_round("old-worker")
        old_token = original.lease_token
    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        round_.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        round_.effect_started = effect_started
    async with get_db_session():
        recovered = await claim_next_round("new-worker")
    async with get_db_session():
        assert not await renew_round_lease(round_id, old_token)
        assert not await round_attempt_succeeded(round_id, old_token)
    async with get_db_session() as db:
        stored = await db.scalar(select(ConversationRound).where(ConversationRound.id == round_id))
        if effect_started:
            assert recovered is None
            assert stored.status == "ERROR_RESOLVED"
            assert stored.attempt_count == 1
        else:
            assert recovered.id == round_id
            assert stored.lease_token != old_token
            assert stored.lease_owner == "new-worker"
            assert stored.attempt_count == 2

    if not effect_started:
        async with get_db_session():
            assert await complete_round(
                round_id, ConversationOutcome(text=""), lease_token=recovered.lease_token,
            ) == "SUCCEEDED"
        async with get_db_session():
            assert await round_attempt_succeeded(round_id, recovered.lease_token)
            assert not await round_attempt_succeeded(round_id, old_token)


@pytest.mark.asyncio
async def test_replaced_worker_cannot_mutate_the_new_attempt(committed_database):
    round_id = await seed_round()
    async with get_db_session():
        original = await claim_next_round("old-worker")
        old_token = original.lease_token
    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        round_.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with get_db_session():
        recovered = await claim_next_round("new-worker")
        new_token = recovered.lease_token
    for operation in (
        lambda: build_turn(round_id, lease_token=old_token),
        lambda: complete_round(round_id, ConversationOutcome(text="stale"), lease_token=old_token),
    ):
        with pytest.raises(ConversationLeaseLostError):
            async with get_db_session():
                await operation()
    async with get_db_session():
        assert not await mark_effect_if_fresh(round_id, lease_token=old_token)
        await fail_round(round_id, "stale failure", lease_token=old_token)
    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        assert round_.lease_token == new_token
        assert round_.status == "CLAIMED"
        assert not round_.effect_started
        assert round_.execution_result is None
        assert round_.last_error != "stale failure"


@pytest.mark.asyncio
async def test_a_completed_round_cannot_be_completed_twice(committed_database):
    round_id = await seed_round()
    async with get_db_session():
        original = await claim_next_round("worker")
        token = original.lease_token
        await complete_round(round_id, ConversationOutcome(text=""), lease_token=token)
    with pytest.raises(ConversationLeaseLostError):
        async with get_db_session():
            await complete_round(round_id, ConversationOutcome(text="late"), lease_token=token)


@pytest.mark.asyncio
async def test_abrupt_worker_exit_leaves_a_recoverable_durable_claim(committed_database):
    round_id = await seed_round()
    database_name = committed_database.kw["bind"].url.database
    # Exit without application shutdown/finally blocks, after the claim commits.
    # The child can reach only the dedicated clone configured for this test.
    script = """
import asyncio, os
import main
from app.conversation.service import claim_next_round
from core.database import get_db_session
async def crash():
    async with get_db_session():
        claim = await claim_next_round('crashed-process')
        assert str(claim.id) == os.environ['EXPECTED_ROUND']
        os._exit(17)
asyncio.run(crash())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        env={**os.environ, "POSTGRES_DB": database_name, "EXPECTED_ROUND": str(round_id)},
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(30):
            _, stderr = await process.communicate()
        assert process.returncode == 17, stderr.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    async with get_db_session() as db:
        stored = await db.get(ConversationRound, round_id)
        assert stored.lease_owner == "crashed-process"
        assert stored.status == "CLAIMED"
        old_token = stored.lease_token
        stored.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with get_db_session():
        recovered = await claim_next_round("replacement-process")
        assert recovered.id == round_id
        assert recovered.attempt_count == 2
        assert recovered.lease_token != old_token


@pytest.mark.asyncio
async def test_task_schedulers_create_one_attempt_for_a_concurrent_claim(committed_database):
    round_id = await seed_round()
    async with get_db_session() as db:
        agent_id = await db.scalar(
            select(Connection.agent_id).join(Room, Room.connection_id == Connection.id)
            .join(ConversationRound, ConversationRound.room_id == Room.id)
            .where(ConversationRound.id == round_id)
        )
        task = Task(label="Concurrent task", objective="Execute once", agent_id=agent_id, status=TaskStatus.CREATE)
        db.add(task)
        await db.flush()
        task_id = task.id
    barrier = asyncio.Barrier(2)

    async def claim():
        await barrier.wait()
        return await task_scheduler._next_task(set(), set())

    async with asyncio.timeout(10):
        claims = await asyncio.gather(claim(), claim())
    assert [claim[0] for claim in claims if claim is not None] == [task_id]
    async with get_db_session() as db:
        attempts = list(await db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task_id)))
        assert len(attempts) == 1
        stored = await db.get(Task, task_id)
        assert stored.attempt_count == 1
        assert stored.lease_token == attempts[0].lease_token
