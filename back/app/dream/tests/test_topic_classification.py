from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation.models import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.conversation.service import admit_message, claim_next_round
from app.dream.contracts import DreamClaim
from app.dream.mechanisms.sequential_topic_classification import (
    message_topic_classification_mechanism,
    propagate_classified_subject,
)
from app.dream.mechanisms.topic_classification import (
    TOPIC_APPROVAL_INTERACTION,
    task_topic_classification_mechanism,
)
from app.dream.models import DreamReceipt
from app.memory.models import MemoryItem
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.messenger import journal, resolve_from_message
from app.messenger._observations import (
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.models import (
    Interaction,
    Message,
    Room,
    MessengerUser,
)
from app.task.models import Task, TaskStatus
from app.topic import Topic, TopicClassification
from app.tools.models import Tool
from core.database import get_db
from core.params.runtime_settings import runtime_settings


class _FakeMessenger:
    tool_id = 42
    connection_id = 0

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []

    async def send_to_room(
        self, room_id: str, text: str, reply_to: str | None = None
    ) -> ObservedMessengerMessage:
        self.sent.append((room_id, text, reply_to))
        return ObservedMessengerMessage(id="topic-approval-prompt", text=text)


def _interaction_answer(sender_id: str, remote_id: str) -> Message:
    message = Message(
        id=uuid4(),
        connection_id=cast(int, None),
        tool_id=42,
        platform="test",
        remote_message_id=remote_id,
        direction="inbound",
        text="1",
        created_at=datetime.now(timezone.utc),
    )
    message.room = cast(Room, SimpleNamespace(id="private-room"))
    message.sender = MessengerUser(
        id=uuid4(),
        tool_id=42,
        external_id=sender_id,
    )
    return message


@pytest.mark.asyncio
async def test_expired_topic_approval_no_longer_blocks_message_classification(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    title = Title(label=f"Topic expiry {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Topic Expiry",
        code=f"topic-expiry-{suffix}",
        agent_driver="internal",
    )
    tool = Tool(
        code=f"topic-expiry-messenger-{suffix}",
        label="Topic Expiry Messenger",
        description="",
        connection_schema={},
    )
    db.add_all([owner, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    expired_room = Room(
        connection_id=connection.id,
        external_id=f"expired-room-{suffix}",
        label="Expired approval room",
        kind="direct",
        conversation_type="text",
    )
    active_room = Room(
        connection_id=connection.id,
        external_id=f"active-room-{suffix}",
        label="Active approval room",
        kind="direct",
        conversation_type="text",
    )
    db.add_all([expired_room, active_room])
    await db.flush()
    expired_message = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="test",
        remote_message_id=f"expired-message-{suffix}",
        direction="inbound",
        messenger_room_id=expired_room.id,
        room_id=expired_room.external_id,
        text="Classify me after the approval expires.",
        created_at=now - timedelta(minutes=2),
    )
    active_message = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="test",
        remote_message_id=f"active-message-{suffix}",
        direction="inbound",
        messenger_room_id=active_room.id,
        room_id=active_room.external_id,
        text="Wait for the active approval.",
        created_at=now - timedelta(minutes=1),
    )
    db.add_all([expired_message, active_message])
    await db.flush()
    db.add_all(
        [
            Interaction(
                reference=f"EXP{suffix}"[:12],
                kind=TOPIC_APPROVAL_INTERACTION,
                status="PENDING",
                connection_id=connection.id,
                tool_id=tool.id,
                room_id=str(expired_room.id),
                title="Expired topic approval",
                expires_at=now - timedelta(seconds=1),
            ),
            Interaction(
                reference=f"ACT{suffix}"[:12],
                kind=TOPIC_APPROVAL_INTERACTION,
                status="PENDING",
                connection_id=connection.id,
                tool_id=tool.id,
                room_id=str(active_room.id),
                title="Active topic approval",
                expires_at=now + timedelta(minutes=5),
            ),
        ]
    )
    await db.commit()

    claim = await message_topic_classification_mechanism.claim_one()

    assert claim is not None
    assert claim.subject_kind == "message"
    assert claim.subject_id == str(expired_message.id)
    assert await message_topic_classification_mechanism.claim_one() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_mode", ["number", "interpreted", "legacy"])
async def test_message_topic_approval_preserves_language_and_resolves_without_inference(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer_mode: str,
) -> None:
    from unittest.mock import AsyncMock

    from app.dream.mechanisms import sequential_topic_classification as mechanism
    from app.messenger import list_pending_choices, resolve_pending_choice

    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    monkeypatch.setattr(runtime_settings, "DEFAULT_LANGUAGE", "en")
    monkeypatch.setattr(runtime_settings, "DREAM_TOPIC_CREATION_MODE", "propose")
    try:
        suffix = uuid4().hex[:8]
        title = Title(label=f"Message approval {suffix}", gender="X")
        tool = Tool(
            code=f"approval-{suffix}", label="Approval", description="", connection_schema={}
        )
        db.add_all([title, tool])
        await db.flush()
        agent = Agent(
            title_id=title.id, first_name="Alice", last_name="Approval", code=f"approval-{suffix}"
        )
        db.add(agent)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        observation = ObservedMessengerMessage(
            id=f"source-{suffix}",
            platform="internal",
            tool_id=tool.id,
            sender=ObservedMessengerUser(id="user:1", connection_id=connection.id),
            room=ObservedMessengerRoom(id=f"provider-room-{suffix}", kind="direct"),
            text="salut",
        )
        await journal.persist_inbound(
            observation,
            connection_id=connection.id,
            platform="internal",
            metadata={"language": "fr"},
        )
        source = await journal.stored_message(
            connection_id=connection.id, remote_message_id=observation.id, direction="inbound"
        )
        assert source is not None
        await admit_message(source, agent_id=agent.id, connection_id=connection.id)
        decision = TopicClassification(
            action="create",
            title="Interactions sociales",
            description="Échanges informels.",
            keywords=["conversation"],
        )
        detector = AsyncMock(
            return_value=SimpleNamespace(
                evaluation=SimpleNamespace(
                    topic_id=uuid4(), classification=decision, model_dump=lambda **_: {}
                ),
                cost=0.01,
            )
        )
        monkeypatch.setattr(mechanism, "detect_topic_with_diagnostics", detector)
        monkeypatch.setattr(
            mechanism,
            "runtime_topic_detection_dependencies",
            AsyncMock(
                return_value=SimpleNamespace(
                    catalog=SimpleNamespace(list_candidates=AsyncMock(return_value=[]))
                )
            ),
        )
        messenger = _FakeMessenger()
        messenger.connection_id = connection.id
        messenger.tool_id = tool.id
        monkeypatch.setattr(
            "app.dream.mechanisms.topic_classification.messenger_for_agent_connection",
            AsyncMock(return_value=messenger),
        )
        claim = DreamClaim(
            receipt_id=uuid4(),
            lease_token=uuid4(),
            subject_kind="message",
            subject_id=str(source.id),
            attempts=1,
            prepared_payload=None,
        )
        prepared = await message_topic_classification_mechanism.prepare(claim)
        assert prepared.payload["language"] == "fr"
        await message_topic_classification_mechanism.apply(claim, prepared.payload)
        assert "Je propose de créer" in messenger.sent[0][1]
        assert "1. Créer" in messenger.sent[0][1]
        detector.reset_mock()
        scope = dict(
            agent_id=agent.id,
            connection_id=connection.id,
            tool_id=tool.id,
            room_id=str(source.messenger_room_id),
        )
        if answer_mode == "legacy":
            from app.dream.dbadmin import _reconcile_topic_approval_recipients

            legacy = await db.scalar(
                select(Interaction).where(Interaction.kind == TOPIC_APPROVAL_INTERACTION)
            )
            assert legacy is not None
            legacy.user_id = str(source.messenger_user_id)
            await db.commit()
            assert not await list_pending_choices(**scope, user_id="user:1")
            await _reconcile_topic_approval_recipients(db)
            await db.flush()
            await db.refresh(legacy)
            assert legacy.user_id == "user:1"
            assert legacy.status == "PENDING" and legacy.resolution is None
            await _reconcile_topic_approval_recipients(db)
            await db.refresh(legacy)
            assert legacy.user_id == "user:1"
        assert not await list_pending_choices(**scope, user_id="other-user")
        choices = await list_pending_choices(**scope, user_id="user:1")
        assert len(choices) == 1
        answer = _interaction_answer("user:1", f"reply-{suffix}")
        answer.connection_id = connection.id
        answer.tool_id = tool.id
        answer.room = source.room
        if answer_mode in {"number", "legacy"}:
            resolution = await resolve_from_message(answer, agent_id=agent.id)
            assert resolution is not None and resolution.option_id == "create"
        else:
            _, applied = await resolve_pending_choice(
                **scope,
                user_id="user:1",
                reference=choices[0].reference,
                option_id="create",
                response_text="Oui, crée ce dossier.",
            )
            assert applied
        source = await db.get(Message, source.id, populate_existing=True)
        assert source is not None
        assert source.topic_id is not None
        record = await db.get(Interaction, choices[0].id)
        assert record is not None and record.status == "RESOLVED"
        topic_id = source.topic_id
        assert await resolve_from_message(answer, agent_id=agent.id) is None
        await db.refresh(source)
        assert source.topic_id == topic_id
        detector.assert_not_awaited()
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_room_default_topic_skips_message_classification(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Room Topic {suffix}", gender="X")
    topic = Topic(title=f"Default {suffix}", description="", keywords=[])
    tool = Tool(
        code=f"room-topic-messenger-{suffix}",
        label="Room Topic Messenger",
        description="",
        connection_schema={},
    )
    db.add_all([title, topic, tool])
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Room Topic",
        code=f"room-topic-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"room-topic-{suffix}",
        label="Room with default Topic",
        kind="direct",
        conversation_type="text",
        topic_id=topic.id,
    )
    db.add(room)
    await db.flush()
    db.add(
        Message(
            connection_id=connection.id,
            tool_id=tool.id,
            platform="test",
            remote_message_id=f"room-topic-message-{suffix}",
            direction="inbound",
            messenger_room_id=room.id,
            room_id=room.external_id,
            text="Use the room topic without another classification.",
        )
    )
    await db.commit()

    assert await message_topic_classification_mechanism.count_pending() == 0
    assert await message_topic_classification_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_outbound_message_is_not_classified_again_by_dream(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Outbound Topic {suffix}", gender="X")
    tool = Tool(
        code=f"outbound-topic-messenger-{suffix}",
        label="Outbound Topic Messenger",
        description="",
        connection_schema={},
    )
    db.add_all([title, tool])
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Outbound Topic",
        code=f"outbound-topic-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"outbound-topic-room-{suffix}",
        label="Outbound Topic room",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    outbound = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="internal",
        remote_message_id=f"outbound-topic-message-{suffix}",
        direction="outbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        text="Agent response inherits the input Topic.",
    )
    db.add(outbound)
    await db.commit()

    assert await message_topic_classification_mechanism.count_pending() == 0
    assert await message_topic_classification_mechanism.claim_one() is None
    claim = DreamClaim(
        receipt_id=uuid4(),
        lease_token=uuid4(),
        subject_kind="message",
        subject_id=str(outbound.id),
        attempts=2,
        prepared_payload=None,
    )
    prepared = await message_topic_classification_mechanism.prepare(claim)
    assert prepared.payload == {}
    assert await message_topic_classification_mechanism.apply(claim, {}) == 0


@pytest.mark.asyncio
async def test_late_message_classification_updates_its_derived_task(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Late Topic {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Late Topic",
        code=f"late-topic-{suffix}",
        agent_driver="internal",
    )
    tool = Tool(
        code=f"late-topic-messenger-{suffix}",
        label="Late Topic Messenger",
        description="",
        connection_schema={},
    )
    db.add_all([owner, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    message = ObservedMessengerMessage(
        id=f"late-topic-message-{suffix}",
        platform="telegram",
        tool_id=tool.id,
        sender=ObservedMessengerUser(id="human", connection_id=connection.id),
        recipient=ObservedMessengerUser(id="agent", connection_id=connection.id),
        room=ObservedMessengerRoom(id=f"late-topic-room-{suffix}", kind="direct"),
        text="Prépare le rapport.",
    )
    assert await journal.persist_inbound(
        message, connection_id=connection.id, platform="telegram"
    )
    stored_message = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=message.id,
        direction="inbound",
    )
    assert stored_message is not None
    assert await admit_message(
        stored_message,
        agent_id=owner.id,
        connection_id=connection.id,
        language="fr",
    )
    round_ = await claim_next_round(f"late-topic-worker-{suffix}")
    assert round_ is not None
    task = Task(
        label="Rapport",
        objective="Prépare le rapport.",
        status=TaskStatus.CREATE,
        agent_id=owner.id,
    )
    db.add(task)
    await db.flush()
    db.add(
        ConversationTaskLink(
            round_id=round_.id,
            task_id=task.id,
            action_key=f"late-topic:{suffix}",
        )
    )
    output = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="telegram",
        remote_message_id=f"late-topic-output-{suffix}",
        direction="outbound",
        messenger_room_id=round_.room_id,
        room_id=message.room.id if message.room is not None else None,
        text="Le rapport est lancé.",
    )
    db.add(output)
    await db.flush()
    db.add(
        ConversationRoundMessage(
            round_id=round_.id,
            message_id=output.id,
            role="output",
            sequence=2,
            response_sequence=1,
        )
    )
    topic = Topic(title=f"Rapport {suffix}")
    db.add(topic)
    await db.flush()
    record = await db.scalar(
        select(Message).where(
            Message.connection_id == connection.id,
            Message.remote_message_id == message.id,
        )
    )
    assert record is not None
    record.topic_id = topic.id
    await db.commit()

    await propagate_classified_subject(record)

    await db.refresh(round_)
    await db.refresh(task)
    await db.refresh(output)
    assert round_.topic_id == topic.id
    assert task.topic_id == topic.id
    assert output.topic_id == topic.id


@pytest.mark.asyncio
async def test_task_classifier_leaves_conversation_task_topic_to_its_round(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Conversation topic {suffix}", gender="X")
    tool = Tool(
        code=f"conversation-topic-{suffix}",
        label="Conversation topic messenger",
        description="",
        connection_schema={},
    )
    db.add_all([title, tool])
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Conversation Topic",
        code=f"conversation-topic-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"conversation-topic-room-{suffix}",
        label="Conversation topic room",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, topic_id=None, status="SUCCEEDED")
    task = Task(
        label="Conversation task without topic",
        objective="Respect the round topic.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
    )
    db.add_all([round_, task])
    await db.flush()
    db.add(
        ConversationTaskLink(
            round_id=round_.id,
            task_id=task.id,
            action_key=f"conversation-topic:{suffix}",
        )
    )
    await db.commit()

    assert await task_topic_classification_mechanism.count_pending() == 0
    assert await task_topic_classification_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_task_topic_classifier_replays_success_but_not_terminal_error(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Topic replay {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Topic Replay",
        code=f"topic-replay-{suffix}",
        agent_driver="internal",
    )
    topic = Topic(title=f"Recovered task topic {suffix}")
    db.add_all([owner, topic])
    await db.flush()
    replayed_task = Task(
        label="Recover my topic",
        objective="Use the durable classification checkpoint.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
    )
    failed_task = Task(
        label="Do not retry me",
        objective="The terminal error is not pending work.",
        status=TaskStatus.ERROR,
        agent_id=owner.id,
    )
    proposed_task = Task(
        label="Wait for approval",
        objective="A proposal is not a missing direct assignment.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
    )
    db.add_all([replayed_task, failed_task, proposed_task])
    await db.flush()
    payload = {
        "decision": TopicClassification(
            action="reuse",
            topic_id=topic.id,
        ).model_dump(mode="json"),
        "candidate_ids": [str(topic.id)],
        "candidate_options": [],
        "language": "en",
        "creation_mode": "auto",
    }
    successful = DreamReceipt(
        mechanism_key=task_topic_classification_mechanism.key,
        subject_kind="task",
        subject_id=str(replayed_task.id),
        status="success",
        attempts=5,
        result_count=1,
        prepared_payload=payload,
    )
    terminal_error = DreamReceipt(
        mechanism_key=task_topic_classification_mechanism.key,
        subject_kind="task",
        subject_id=str(failed_task.id),
        status="error",
        attempts=5,
        last_error="Classification failed permanently.",
    )
    proposed = DreamReceipt(
        mechanism_key=task_topic_classification_mechanism.key,
        subject_kind="task",
        subject_id=str(proposed_task.id),
        status="success",
        attempts=1,
        result_count=1,
        prepared_payload={
            "decision": TopicClassification(
                action="create",
                topic_id=uuid4(),
                title="Needs approval",
            ).model_dump(mode="json"),
            "candidate_ids": [],
            "candidate_options": [],
            "language": "en",
            "creation_mode": "propose",
        },
    )
    db.add_all([successful, terminal_error, proposed])
    await db.commit()

    assert await task_topic_classification_mechanism.count_pending() == 1
    claim = await task_topic_classification_mechanism.claim_one()

    assert claim is not None
    assert claim.receipt_id == successful.id
    assert claim.prepared_payload == payload
    assert claim.attempts == 1


@pytest.mark.asyncio
async def test_task_is_classified_before_its_public_topic_memory_is_projected(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    monkeypatch.setattr(
        "app.dream.mechanisms.topic_classification.topic_creation_mode",
        lambda: "auto",
    )
    try:
        title = Title(label=f"Topic classifier {uuid4().hex[:8]}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Classifier",
            code=f"topic-classifier-{uuid4().hex[:8]}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()
        task = Task(
            label="Préparer le potager du balcon",
            objective="Choisir des légumes adaptés à un petit balcon.",
            status=TaskStatus.SUCCESS,
            agent_id=owner.id,
            data={"language": "fr"},
        )
        db.add(task)
        await db.commit()

        async def fake_classify(**kwargs: object) -> tuple[TopicClassification, float]:
            get_db()
            assert kwargs["language"] == "fr"
            return (
                TopicClassification(
                    action="create",
                    title="Potager urbain",
                    description="Choix et entretien de cultures adaptées à la ville.",
                    keywords=["potager", "ville"],
                    confidence=0.91,
                ),
                0.02,
            )

        monkeypatch.setattr(
            "app.dream.mechanisms.topic_classification.classify", fake_classify
        )
        claim = DreamClaim(
            receipt_id=uuid4(),
            lease_token=uuid4(),
            subject_kind="task",
            subject_id=str(task.id),
            attempts=1,
            prepared_payload=None,
        )
        prepared = await task_topic_classification_mechanism.prepare(claim)
        assert prepared.cost == 0.02
        prepared_topic_id = prepared.payload["decision"]["topic_id"]
        assert prepared_topic_id is not None
        assert await task_topic_classification_mechanism.apply(
            claim, prepared.payload
        ) == 1
        assert await task_topic_classification_mechanism.apply(
            claim, prepared.payload
        ) == 0

        await db.refresh(task)
        assert task.topic_id is not None
        topic = await db.get(Topic, task.topic_id)
        assert topic is not None and topic.memory_item_id is not None
        assert str(topic.id) == prepared_topic_id
        topic_memory = await db.get(MemoryItem, topic.memory_item_id)
        assert topic_memory is not None
        assert topic_memory.owner_agent_id is None
        assert topic_memory.visibility == "public"
        assert topic_memory.read_only and topic_memory.source_managed
        assert topic_memory.managed_source_kind == "topic"
    finally:
        reset_storage_registry()


@pytest.mark.asyncio
async def test_proposed_topic_waits_for_the_authorized_user_choice(
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        title = Title(label=f"Topic approver {uuid4().hex[:8]}", gender="X")
        db.add(title)
        await db.flush()
        owner = Agent(
            title_id=title.id,
            first_name="Alice",
            last_name="Approver",
            code=f"topic-approver-{uuid4().hex[:8]}",
            agent_driver="internal",
        )
        db.add(owner)
        await db.flush()
        task = Task(
            label="Installer un composteur",
            objective="Choisir un composteur adapté au balcon.",
            status=TaskStatus.SUCCESS,
            agent_id=owner.id,
            ai=False,
            message_group_id="private-room",
            data={
                "language": "fr",
                "sender.user_id": "alice",
                "message_id": "source-message",
            },
        )
        db.add(task)
        await db.commit()

        async def fake_classify(**_kwargs: object) -> tuple[TopicClassification, float]:
            return (
                TopicClassification(
                    action="create",
                    title="Compostage urbain",
                    description="Composter dans de petits espaces.",
                    keywords=["compost", "balcon"],
                ),
                0.01,
            )

        messenger = _FakeMessenger()

        async def fake_resolve_task_messaging(
            _task: Task,
        ) -> tuple[_FakeMessenger, None]:
            return messenger, None

        monkeypatch.setattr(
            "app.dream.mechanisms.topic_classification.classify", fake_classify
        )
        monkeypatch.setattr(
            "app.dream.mechanisms.topic_classification.resolve_task_messaging",
            fake_resolve_task_messaging,
        )
        monkeypatch.setattr(runtime_settings, "DREAM_TOPIC_CREATION_MODE", "propose")
        claim = DreamClaim(
            receipt_id=uuid4(),
            lease_token=uuid4(),
            subject_kind="task",
            subject_id=str(task.id),
            attempts=1,
            prepared_payload=None,
        )

        prepared = await task_topic_classification_mechanism.prepare(claim)
        assert await task_topic_classification_mechanism.apply(
            claim, prepared.payload
        ) == 1
        await db.refresh(task)
        assert task.topic_id is None
        interaction = await db.scalar(
            select(Interaction).where(
                Interaction.kind == TOPIC_APPROVAL_INTERACTION
            )
        )
        assert interaction is not None and interaction.status == "PENDING"
        assert len(messenger.sent) == 1
        assert "Je propose de créer un nouveau sujet" in messenger.sent[0][1]

        unauthorized = _interaction_answer("mallory", "answer-mallory")
        assert (
            await resolve_from_message(unauthorized, agent_id=owner.id) is None
        )
        authorized = _interaction_answer("alice", "answer-alice")
        resolution = await resolve_from_message(authorized, agent_id=owner.id)
        assert resolution is not None and resolution.option_id == "create"

        await db.refresh(task)
        assert task.topic_id is not None
        topic = await db.get(Topic, task.topic_id)
        assert topic is not None and topic.title == "Compostage urbain"
        await db.refresh(interaction)
        assert interaction.status == "RESOLVED"
    finally:
        reset_storage_registry()
