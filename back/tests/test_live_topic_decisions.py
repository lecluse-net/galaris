"""Admission and topic inference use independent real PostgreSQL transactions."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage, ConversationTaskLink
from app.conversation.contracts import ConversationTurn
from app.conversation.facade import current_turn_scope
from app.dream import live_topics
from app.dream.models import DreamReceipt
from app.dream.mechanisms.sequential_topic_classification import (
    message_topic_classification_mechanism as mechanism,
)
from app.messenger import Message, MessengerUser, Room
from app.messenger.service import admit_incoming
from app.topic import Topic
from tests.test_decision_inference import decisions, runtime  # noqa: F401
from tests.test_decision_workflows import profile_context, memory_extraction_storage  # noqa: F401


async def context(decisions, runtime, *, specialized=True):
    db, _, _, _, mode = decisions
    task, profile = await profile_context(
        decisions, runtime, specialized=specialized, fallback=False
    )
    round_ = await db.scalar(
        select(ConversationRound)
        .join(ConversationTaskLink)
        .where(
            ConversationTaskLink.task_id == task.id,
        )
    )
    room = await db.get(Room, round_.room_id)
    connection = await db.get(Connection, room.connection_id)
    topic = Topic(title=f"Gardening {uuid4()}", description="Growing plants.")
    db.add(topic)
    await db.flush()
    previous = await db.scalar(select(Message).where(Message.messenger_room_id == room.id))
    previous.topic_id = topic.id
    sender = MessengerUser(
        tool_id=connection.tool_id,
        external_id=f"human-{uuid4()}",
        display_name="Morgan",
        galaris_user_id=task.agent.user_id,
        is_ai=False,
    )
    recipient = MessengerUser(
        tool_id=connection.tool_id,
        external_id=f"agent-{uuid4()}",
        agent_id=task.agent_id,
        is_ai=True,
    )
    db.add_all([sender, recipient])
    await db.commit()
    mode["selections"] = {"continuity": "same", "topic": str(topic.id)}
    return task, profile, round_, room, connection, sender, recipient, topic


async def message(db, scope, *, text="And how should I water the tomatoes?", topic=None):
    task, _, _, room, connection, sender, recipient, _ = scope
    row = Message(
        connection_id=connection.id,
        tool_id=connection.tool_id,
        platform="internal",
        remote_message_id=f"live-{uuid4()}",
        direction="inbound",
        text=text,
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        requester_user_id=task.agent.user_id,
        topic_id=topic,
        topic_overridden=topic is not None,
        metadata_={"language": "en"},
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    row.sender, row.recipient, row.room = sender, recipient, room
    return row


async def receipt(db, message_id, status):
    async with asyncio.timeout(10):
        while True:
            row = await db.scalar(
                select(DreamReceipt)
                .where(
                    DreamReceipt.mechanism_key == mechanism.key,
                    DreamReceipt.subject_id == str(message_id),
                )
                .execution_options(populate_existing=True)
            )
            if row is not None and row.status == status:
                return row
            if row is not None and row.status in {"error", "retry"} and status == "success":
                pytest.fail(row.last_error)
            await db.commit()
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("task_before_topic", [False, True])
async def test_live_topic_runs_alongside_admission_and_dispatch_then_dream_skips_it(
    decisions,
    runtime,
    memory_extraction_storage,
    task_before_topic,
):
    from app.agent.dispatcher import Dispatcher
    from app.task import TaskCreate, task_service

    db, _, calls, text_calls, mode = decisions
    scope = await context(decisions, runtime)
    task, _, round_, room, _, _, _, topic = scope
    row = await message(db, scope)
    started, gate = asyncio.Event(), asyncio.Event()

    async def provider_started():
        started.set()

    mode.update(gate=gate, before_response=provider_started)
    live_topics.start()
    try:
        async with asyncio.timeout(5):
            assert await admit_incoming(row)
            await started.wait()
        assert not gate.is_set()
        dispatched = await Dispatcher().run_conversation(
            round_id=round_.id,
            run_id=uuid4(),
            agent_id=task.agent_id,
            language="en",
            objective=row.text,
            sender_is_ai=False,
        )
        assert dispatched.success and not gate.is_set()
        direct_task = None
        if task_before_topic:
            direct_task, _ = await task_service.create_from_messenger(
                TaskCreate(
                    agent_id=task.agent_id,
                    label="Synthetic direct admission",
                    objective=row.text,
                ),
                row.id,
            )
        turn = ConversationTurn(
            room_id=room.id,
            round_id=round_.id,
            agent_id=task.agent_id,
            language="en",
            objective=row.text,
            messages=(),
            topic_id=None,
        )
        gate.set()
        completed = await receipt(db, row.id, "success")
        await db.refresh(row)
        assert row.topic_id == topic.id
        if direct_task is None:
            direct_task, _ = await task_service.create_from_messenger(
                TaskCreate(
                    agent_id=task.agent_id,
                    label="Synthetic late admission",
                    objective=row.text,
                ),
                row.id,
            )
        await db.refresh(direct_task)
        assert direct_task.topic_id == topic.id
        assert (await current_turn_scope(turn))[0] == topic.id
        # A tool invoked from the already-frozen turn must use the late topic.
        from app.memory import mcp as memory_tools
        from app.memory.models import MemoryTopicContactItem, MemoryTopicContactScope
        from app.tools.mcp_loader import McpToolContext

        await db.refresh(topic)
        assert topic.memory_item_id is not None
        remembered = json.loads(
            await memory_tools.memory_remember(
                McpToolContext(
                    agent_id=task.agent_id,
                    runtime="internal",
                    resources={"conversation_turn": turn},
                ),
                content="Morgan waters tomato plants on Monday mornings.",
                title="Watering schedule",
            )
        )
        assert "error" not in remembered, remembered
        assert (
            await db.scalar(
                select(MemoryTopicContactItem.item_id)
                .join(MemoryTopicContactScope)
                .where(
                    MemoryTopicContactItem.item_id == remembered["memory_id"],
                    MemoryTopicContactScope.topic_item_id == topic.memory_item_id,
                )
            )
            is not None
        )
        assert completed.cost == pytest.approx(0.0002)
        assert await mechanism.claim_one() is None
        await admit_incoming(row)
        assert len(calls) == 1 and not text_calls
    finally:
        gate.set()
        await live_topics.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "excluded", ["no_decision", "room_topic", "manual_topic", "historical", "denied"]
)
async def test_live_topic_respects_profile_manual_choices_history_and_contact_access(
    decisions,
    runtime,
    memory_extraction_storage,
    excluded,
):
    db, _, calls, text_calls, _ = decisions
    scope = await context(decisions, runtime, specialized=excluded != "no_decision")
    row = await message(db, scope, topic=scope[-1].id if excluded == "manual_topic" else None)
    if excluded == "room_topic":
        scope[3].topic_id = scope[-1].id
    if excluded == "historical":
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    if excluded == "denied":
        scope[5].galaris_user_id = None
    await db.commit()
    live_topics.start()
    try:
        await admit_incoming(row)
        await asyncio.gather(*tuple(live_topics._workers.values()))
        assert not calls and not text_calls
        assert (
            await db.scalar(select(DreamReceipt.id).where(DreamReceipt.subject_id == str(row.id)))
            is None
        )
    finally:
        await live_topics.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["manual", "new_input"])
async def test_late_classification_cannot_replace_manual_or_newer_input_topic(
    decisions,
    runtime,
    memory_extraction_storage,
    intervention,
):
    db, _, _, _, mode = decisions
    scope = await context(decisions, runtime)
    row = await message(db, scope)
    other = Topic(title=f"Astronomy {uuid4()}", description="Studying the sky.")
    db.add(other)
    await db.commit()
    gate, started = asyncio.Event(), asyncio.Event()

    async def provider_started():
        started.set()

    mode.update(gate=gate, before_response=provider_started)
    live_topics.start()
    try:
        await admit_incoming(row)
        async with asyncio.timeout(5):
            await started.wait()
        if intervention == "manual":
            await db.execute(
                update(Message)
                .where(Message.id == row.id)
                .values(
                    topic_id=other.id,
                    topic_overridden=True,
                )
            )
            await db.commit()
        else:
            newer = await message(db, scope, text="Now about Saturn.", topic=other.id)
            await admit_incoming(newer)
        gate.set()
        await receipt(db, row.id, "success")
        await db.refresh(row)
        if intervention == "manual":
            assert row.topic_id == other.id
        else:
            await db.refresh(scope[2])
            assert scope[2].topic_id == other.id
            assert row.topic_id == scope[-1].id
    finally:
        gate.set()
        await live_topics.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_dream_recovers_failed_or_cancelled_live_classification_without_losing_admission(
    decisions,
    runtime,
    memory_extraction_storage,
    cancel,
):
    from app.dream import scheduler

    db, _, calls, _, mode = decisions
    scope = await context(decisions, runtime)
    row = await message(db, scope)
    started = asyncio.Event()

    async def provider_started():
        started.set()

    mode.update(
        status=200 if cancel else 503,
        gate=asyncio.Event() if cancel else None,
        before_response=provider_started,
    )
    live_topics.start()
    try:
        assert await admit_incoming(row)
        async with asyncio.timeout(5):
            await started.wait()
        if cancel:
            await live_topics.stop()
        failed = await receipt(db, row.id, "retry")
        assert (
            await db.scalar(
                select(ConversationRoundMessage.round_id).where(
                    ConversationRoundMessage.message_id == row.id,
                )
            )
            is not None
        )
        failed.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        mode.update(status=200, gate=None)
        claim = await mechanism.claim_one()
        assert claim is not None and claim.receipt_id == failed.id
        await scheduler._run_claim(mechanism, claim)
        await receipt(db, row.id, "success")
        assert len(calls) == 2
    finally:
        await live_topics.stop()
