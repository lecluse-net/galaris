from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation.models import ConversationRoundMessage
from app.dream.dbadmin import _reconcile_topic_assignments, register_dbadmin
from app.dream.mechanisms.sequential_topic_classification import (
    message_topic_classification_mechanism,
)
from app.dream.mechanisms.topic_classification import topic_classification_payload
from app.dream.models import DreamReceipt
from app.messenger import facade, inbound, journal, service
from app.messenger.events import Signal
from app.messenger.interface import BridgeSpec
from app.messenger._observations import (
    ObservedMessengerMessage as Message,
    ObservedMessengerRoom as Room,
    ObservedMessengerUser as User,
)
from app.messenger.models import (
    AUDIO_TRANSCRIPT_METADATA_KEY,
    File as FileModel,
    Message as MessageModel,
    MessengerUser,
)
from app.messenger._observations import ObservedMessengerFile
from app.task import task_service
from app.task.models import Task
from app.task.schemas import TaskCreate
from app.topic import Topic, TopicClassification
from app.tools.models import Tool
from core.dbadmin import DbAdminRegistry
from core.user.models import User as GalarisUser


async def _connection(db: AsyncSession) -> Connection:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Title {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Bridge",
        last_name="Test",
        code=f"bridge-{suffix}",
        agent_driver="internal",
    )
    tool = Tool(
        code=f"messenger-{suffix}",
        label="Messenger test",
        description="",
        connection_schema={},
    )
    db.add_all([agent, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    return connection


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["accepted", "denied", "provider_error"])
async def test_private_message_search_and_delivery_keep_a_durable_receipt(
    committed_database, monkeypatch, delivery,
):
    import asyncio
    from app.messenger import mcp, events
    from app.messenger.models import Capability
    from app.tools.mcp_loader import McpToolContext
    from core.database import get_db_session

    async with get_db_session() as db:
        owner = GalarisUser(email=f"sender-{uuid4().hex}@example.test", hashed_password="synthetic")
        recipient = GalarisUser(email=f"recipient-{uuid4().hex}@example.test", hashed_password="synthetic")
        db.add_all([owner, recipient])
        await db.flush()
        title = Title(label="Synthetic messenger", gender="X")
        db.add(title)
        await db.flush()
        agent = Agent(user_id=owner.id if delivery == "denied" else recipient.id,
                      title_id=title.id, first_name="Test", last_name="Sender",
                      code=f"receipt-{uuid4().hex}", agent_driver="internal")
        tool = Tool(code=f"receipt-{uuid4().hex}", label="Synthetic messenger",
                    description="", connection_schema={})
        db.add_all([agent, tool])
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        db.add(MessengerUser(tool_id=tool.id, external_id="human", display_name="Old name",
                             galaris_user_id=recipient.id))
        agent_id, tool_id, connection_id = agent.id, tool.id, connection.id

    class Provider:
        kind = "telegram"
        self_id = "bot"
        users_snapshot_complete = False
        sent = 0

        def supports(self, capability):
            return capability in {Capability.SEND, Capability.SEARCH_USERS}

        async def search_users(self, query):
            return [User(id="human", display_name="Synthetic recipient", tool_id=tool_id)]

        async def send_to_user(self, user_id, message):
            if delivery == "provider_error":
                raise ConnectionError("Synthetic provider unavailable")
            self.sent += 1
            return Message(id="accepted-message", platform=self.kind, tool_id=tool_id,
                           recipient=User(id=user_id, tool_id=tool_id),
                           room=Room(id="direct-room", kind="direct"), text=message)

    provider = Provider()
    provider.tool_id = tool_id
    messenger = facade.MessengerFacade(provider, connection_id)
    monkeypatch.setattr(mcp, "_resolve_context_messenger", AsyncMock(return_value=messenger))
    monkeypatch.setattr(events, "message_sent", Signal("synthetic_outbound"))
    async with get_db_session():
        call = mcp.mcp_send_message_to_user(
            McpToolContext(agent_id=agent_id, runtime="internal"),
            "Synthetic recipient", "Synthetic message",
        )
        if delivery == "accepted":
            await asyncio.wait_for(call, 3)
        else:
            with pytest.raises(RuntimeError, match="not authorized|Synthetic provider unavailable"):
                await asyncio.wait_for(call, 3)

    async with get_db_session() as db:
        receipts = list(await db.scalars(select(MessageModel).where(
            MessageModel.connection_id == connection_id,
            MessageModel.direction == "outbound",
        )))
        assert len(receipts) == provider.sent == (1 if delivery == "accepted" else 0)
        if receipts:
            assert receipts[0].remote_message_id == "accepted-message"
            assert receipts[0].text == "Synthetic message"


@pytest.mark.asyncio
async def test_journal_deduplicates_and_returns_chronological_history(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    message = Message(
        id="chat:7",
        platform="telegram",
        tool_id=connection.tool_id,
        sender=User(id="42", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="chat"),
        text="hello",
        time=100,
    )

    assert await journal.persist_inbound(
        message, connection_id=connection.id, platform="telegram"
    )
    assert not await journal.persist_inbound(
        message, connection_id=connection.id, platform="telegram"
    )

    rows = await journal.history(connection.id, "chat", 20)
    assert [(item.remote_message_id, item.text, item.platform) for item in rows] == [
        ("chat:7", "hello", "telegram")
    ]
    count = len(
        list(
            (
                await db.scalars(
                    select(MessageModel).where(
                        MessageModel.connection_id == connection.id
                    )
                )
            ).all()
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_journal_resolves_message_identities_in_stable_order(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _connection(db)
    observed_order: list[str] = []
    resolve_observed_user = journal.resolve_observed_user

    async def record_resolution(*, tool_id: int, user: User):
        observed_order.append(user.id)
        return await resolve_observed_user(tool_id=tool_id, user=user)

    monkeypatch.setattr(journal, "resolve_observed_user", record_resolution)
    message = Message(
        id="chat:stable-identity-lock-order",
        platform="nextcloud_talk",
        tool_id=connection.tool_id,
        sender=User(id="z-sender", connection_id=connection.id),
        recipient=User(id="a-recipient", connection_id=connection.id),
        room=Room(id="chat"),
        text="Avoid reverse unique-key lock acquisition.",
        time=100,
    )

    assert await journal.persist_inbound(
        message,
        connection_id=connection.id,
        platform="nextcloud_talk",
    )
    assert observed_order == ["a-recipient", "z-sender"]


@pytest.mark.asyncio
async def test_journal_redelivery_preserves_server_audio_transcription_metadata(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    observed = Message(
        id="chat:audio-redelivery",
        platform="telegram",
        tool_id=connection.tool_id,
        sender=User(id="42", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="chat"),
        text="",
        time=100,
    )
    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="telegram",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    transcripts = {str(uuid4()): "Transcription durable"}
    await db.execute(
        update(MessageModel)
        .where(MessageModel.id == stored.id)
        .values(metadata_={AUDIO_TRANSCRIPT_METADATA_KEY: transcripts})
    )
    await db.commit()

    assert not await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="telegram",
    )

    refreshed = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert refreshed is not None
    assert refreshed.metadata_[AUDIO_TRANSCRIPT_METADATA_KEY] == transcripts


@pytest.mark.asyncio
async def test_journal_redelivery_preserves_server_owned_topic(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    observed = Message(
        id="chat:topic-redelivery",
        platform="nextcloud_talk",
        tool_id=connection.tool_id,
        sender=User(id="42", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="chat"),
        text="Keep my canonical topic.",
        time=100,
    )
    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="nextcloud_talk",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    topic = Topic(title="Durable redelivery topic")
    db.add(topic)
    await db.flush()
    await db.execute(
        update(MessageModel)
        .where(MessageModel.id == stored.id)
        .values(topic_id=topic.id)
    )
    await db.commit()

    assert not await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="nextcloud_talk",
    )

    refreshed = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert refreshed is not None
    assert refreshed.topic_id == topic.id


@pytest.mark.asyncio
async def test_message_topic_classifier_replays_only_a_lost_successful_assignment(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    topic = Topic(title="Recovered classification")
    db.add(topic)
    await db.flush()
    messages: list[MessageModel] = []
    for remote_id in ("lost-success", "terminal-error"):
        observed = Message(
            id=remote_id,
            platform="nextcloud_talk",
            tool_id=connection.tool_id,
            sender=User(id="42", connection_id=connection.id),
            recipient=User(id="bot", connection_id=connection.id),
            room=Room(id="dream-recovery"),
            text=f"Classify {remote_id}.",
            time=100,
        )
        assert await journal.persist_inbound(
            observed,
            connection_id=connection.id,
            platform="nextcloud_talk",
        )
        stored = await journal.stored_message(
            connection_id=connection.id,
            remote_message_id=remote_id,
            direction="inbound",
        )
        assert stored is not None
        messages.append(stored)
    payload = topic_classification_payload(
        TopicClassification(action="reuse", topic_id=topic.id),
        [],
        language="en",
        creation_mode="auto",
    )
    successful = DreamReceipt(
        mechanism_key=message_topic_classification_mechanism.key,
        subject_kind="message",
        subject_id=str(messages[0].id),
        status="success",
        attempts=5,
        result_count=1,
        prepared_payload=payload,
    )
    terminal_error = DreamReceipt(
        mechanism_key=message_topic_classification_mechanism.key,
        subject_kind="message",
        subject_id=str(messages[1].id),
        status="error",
        attempts=5,
        last_error="Classification failed permanently.",
    )
    db.add_all([successful, terminal_error])
    await db.commit()

    assert await message_topic_classification_mechanism.count_pending() == 1
    claim = await message_topic_classification_mechanism.claim_one()

    assert claim is not None
    assert claim.receipt_id == successful.id
    assert claim.prepared_payload == payload
    assert claim.attempts == 1
    assert await message_topic_classification_mechanism.apply(claim, payload) == 1
    recovered = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id="lost-success",
        direction="inbound",
    )
    assert recovered is not None
    assert recovered.topic_id == topic.id
    assert await message_topic_classification_mechanism.count_pending() == 0
    assert await message_topic_classification_mechanism.claim_one() is None


@pytest.mark.asyncio
async def test_dream_dbadmin_restores_checkpointed_message_topic_idempotently(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    topic = Topic(title="DbAdmin recovered classification")
    db.add(topic)
    await db.flush()
    observed = Message(
        id="dbadmin-lost-topic",
        platform="nextcloud_talk",
        tool_id=connection.tool_id,
        sender=User(id="42", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="dream-dbadmin-recovery"),
        text="Restore my Topic during the production update.",
        time=100,
    )
    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="nextcloud_talk",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    payload = topic_classification_payload(
        TopicClassification(action="reuse", topic_id=topic.id),
        [],
        language="en",
        creation_mode="auto",
    )
    db.add(
        DreamReceipt(
            mechanism_key=message_topic_classification_mechanism.key,
            subject_kind="message",
            subject_id=str(stored.id),
            status="success",
            attempts=1,
            result_count=1,
            prepared_payload=payload,
        )
    )
    await db.commit()

    await _reconcile_topic_assignments(db)
    await db.commit()
    await _reconcile_topic_assignments(db)
    await db.commit()

    recovered = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert recovered is not None
    assert recovered.topic_id == topic.id


def test_dream_registers_topic_assignment_reconciler() -> None:
    registry = DbAdminRegistry()

    register_dbadmin(registry)

    assert [item.key for item in registry.reconcilers] == [
        "app.dream.topic_approval_recipients",
        "app.dream.topic_assignments"
    ]


@pytest.mark.asyncio
async def test_task_admission_is_idempotent_after_effect_commit(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash before the journal receipt cannot create a second Task on redelivery."""

    connection = await _connection(db)
    observed = Message(
        id="chat:durable-effect",
        platform="mail",
        tool_id=connection.tool_id,
        sender=User(id="human", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="mailbox"),
        text="Create exactly one Task.",
        time=100,
    )
    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="mail",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())

    first, first_created = await task_service.create_from_messenger(
        TaskCreate(label="Mail admission", objective=observed.text),
        stored.id,
    )
    first_id = first.id
    original_objective = first.objective
    db.expunge(first)
    # Simulate a process crash here: Message.status is deliberately still ``received``.
    # Re-delivery must return the durable Task, not overwrite it with a new draft.
    second, second_created = await task_service.create_from_messenger(
        TaskCreate(label="Replayed draft", objective="Must not replace the admitted work."),
        stored.id,
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first_id
    assert second.label == "Mail admission"
    assert second.objective == original_objective
    rows = list(
        (
            await db.scalars(
                select(Task).where(Task.messenger_message_id == stored.id)
            )
        ).all()
    )
    assert [row.id for row in rows] == [first_id]


@pytest.mark.asyncio
async def test_inbound_requester_is_frozen_and_propagated_to_the_task(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _connection(db)
    owner = GalarisUser(
        email=f"owner-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    other = GalarisUser(
        email=f"other-{uuid4().hex}@example.test",
        hashed_password="not-used",
        is_active=True,
    )
    db.add_all([owner, other])
    await db.flush()
    observed = Message(
        id="chat:requester-snapshot",
        platform="telegram",
        tool_id=connection.tool_id,
        sender=User(id="linked-human", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="chat"),
        text="Use my subscription.",
        time=100,
    )
    # Resolve the canonical identity first, then link it exactly as My profile does.
    await journal.persist_inbound(
        Message.model_validate(
            {**observed.model_dump(), "id": "chat:identity-bootstrap"}
        ),
        connection_id=connection.id,
        platform="telegram",
    )
    identity = await db.scalar(
        select(MessengerUser).where(
            MessengerUser.tool_id == connection.tool_id,
            MessengerUser.external_id == "linked-human",
        )
    )
    assert identity is not None
    identity.galaris_user_id = owner.id
    await db.commit()

    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="telegram",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    assert stored.requester_user_id == owner.id

    identity.galaris_user_id = other.id
    await db.commit()
    assert not await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="telegram",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    assert stored.requester_user_id == owner.id

    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    task, created = await task_service.create_from_messenger(
        TaskCreate(label="Frozen requester"),
        stored.id,
    )
    assert created is True
    assert task.requester_user_id == owner.id


@pytest.mark.asyncio
async def test_stale_instant_message_is_journalled_for_dream_without_run(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _connection(db)
    now = datetime.now(timezone.utc)
    observed = Message(
        id="historical-room-message",
        platform="nextcloud_talk",
        tool_id=connection.tool_id,
        sender=User(id="human", connection_id=connection.id),
        recipient=User(id="bot", connection_id=connection.id),
        room=Room(id="historical-room", kind="group"),
        text="This history must be classified but never answered.",
        time=int((now - timedelta(days=30)).timestamp()),
    )
    assert await journal.persist_inbound(
        observed,
        connection_id=connection.id,
        platform="nextcloud_talk",
    )
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert stored is not None
    process = AsyncMock()
    monkeypatch.setattr(service, "_process_incoming", process)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="nextcloud_talk"),
    )

    assert await service.admit_incoming(stored) is False

    process.assert_not_awaited()
    refreshed = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=observed.id,
        direction="inbound",
    )
    assert refreshed is not None
    assert refreshed.status == "admitted"
    assert refreshed.metadata_["inbound_admission"]["disposition"] == "dream_only"
    assert (
        refreshed.metadata_["inbound_admission"]["reason"]
        == "instant_message_older_than_one_hour"
    )
    assert await db.scalar(
        select(ConversationRoundMessage).where(
            ConversationRoundMessage.message_id == refreshed.id
        )
    ) is None
    assert await db.scalar(
        select(Task).where(Task.messenger_message_id == refreshed.id)
    ) is None

    # Dream consumes canonical messages directly; it does not require a ConversationRound.
    claim = await message_topic_classification_mechanism.claim_one()
    assert claim is not None
    assert claim.subject_kind == "message"
    assert claim.subject_id == str(refreshed.id)


@pytest.mark.asyncio
async def test_recent_user_room_uses_latest_inbound_room_and_contact_id(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    sender = User(
        id="human-42",
        display_name="Nicolas",
        connection_id=connection.id,
    )
    recipient = User(id="bot", connection_id=connection.id)
    for message_id, room_id, timestamp in (
        ("old", "room-old", 100),
        ("latest", "room-latest", 300),
    ):
        assert await journal.persist_inbound(
            Message(
                id=message_id,
                platform="internal",
                tool_id=connection.tool_id,
                sender=sender,
                recipient=recipient,
                room=Room(id=room_id),
                text=message_id,
                time=timestamp,
            ),
            connection_id=connection.id,
            platform="internal",
        )

    from app.memory import MessengerContactObservation, observe_messenger_contact

    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=connection.agent_id,
            messaging_id="internal",
            user_id="human-42",
            display_name="Nicolas",
        )
    )
    await db.execute(
        update(MessageModel)
        .where(MessageModel.remote_message_id.in_(["old", "latest"]))
        .values(contact_memory_item_id=contact_id)
    )
    await db.flush()

    by_name = await service.recent_user_room(connection.agent_id, "Nicolas")
    by_contact = await service.recent_user_room(
        connection.agent_id, str(contact_id)
    )

    assert by_name is not None
    assert by_contact is not None
    assert by_name.room_id == "room-latest"
    assert by_contact == by_name


@pytest.mark.asyncio
async def test_journal_preserves_native_attachment_uuid(db: AsyncSession) -> None:
    connection = await _connection(db)
    file_id = uuid4()
    message = Message(
        id="native-file-message",
        platform="internal",
        tool_id=connection.tool_id,
        sender=User(id="human", connection_id=connection.id),
        recipient=User(id="agent", connection_id=connection.id),
        room=Room(id="native-room"),
        attachments=[
            ObservedMessengerFile(
                id=str(file_id),
                local_id=file_id,
                name="document.txt",
                mime="text/plain",
                size=4,
                kind="document",
            )
        ],
        time=100,
    )

    assert await journal.persist_inbound(
        message, connection_id=connection.id, platform="internal"
    )

    stored = await db.get(FileModel, file_id)
    assert stored is not None
    assert stored.name == "document.txt"


@pytest.mark.asyncio
async def test_journal_history_pages_are_stable_complete_and_room_scoped(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    room_id = "large-room"
    for index in range(5):
        assert await journal.persist_inbound(
            Message(
                id=f"message-{index}",
                platform="telegram",
                tool_id=connection.tool_id,
                sender=User(
                    id="42",
                    display_name="Alice",
                    connection_id=connection.id,
                ),
                recipient=User(id="bot", connection_id=connection.id),
                room=Room(id=room_id),
                text=f"text-{index}",
                time=100 + index,
            ),
            connection_id=connection.id,
            platform="telegram",
        )

    rows = list(
        (
            await db.scalars(
                select(MessageModel)
                .where(MessageModel.connection_id == connection.id)
                .order_by(MessageModel.remote_message_id)
            )
        ).all()
    )
    baseline = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, row in enumerate(rows):
        row.created_at = baseline + timedelta(seconds=index)
    await db.flush()

    first = await journal.history_page(connection.id, room_id, limit=2)
    assert [message.remote_message_id for message in first.messages] == [
        "message-3",
        "message-4",
    ]
    assert [message.sender.display_name for message in first.messages if message.sender] == [
        "Alice",
        "Alice",
    ]
    assert first.has_more
    assert first.next_cursor is not None

    second = await journal.history_page(
        connection.id,
        room_id,
        limit=2,
        cursor=first.next_cursor,
    )
    assert [message.remote_message_id for message in second.messages] == [
        "message-1",
        "message-2",
    ]
    assert second.has_more
    assert second.next_cursor is not None

    third = await journal.history_page(
        connection.id,
        room_id,
        limit=2,
        cursor=second.next_cursor,
    )
    assert [message.remote_message_id for message in third.messages] == ["message-0"]
    assert not third.has_more
    assert third.next_cursor is None

    with pytest.raises(ValueError, match="out-of-scope"):
        await journal.history_page(
            connection.id,
            "another-room",
            limit=2,
            cursor=first.next_cursor,
        )


@pytest.mark.asyncio
async def test_journal_updates_delivery_status_and_listener_cursor(
    db: AsyncSession,
) -> None:
    connection = await _connection(db)
    outbound = Message(
        id="wamid.out",
        platform="whatsapp",
        tool_id=connection.tool_id,
        sender=User(id="business", connection_id=connection.id),
        recipient=User(id="331234", connection_id=connection.id),
        room=Room(id="331234", kind="direct"),
        text="bonjour",
    )
    assert await journal.persist_outbound(
        outbound,
        connection_id=connection.id,
        platform="whatsapp",
    )
    assert await journal.update_delivery_status(
        connection_id=connection.id,
        remote_message_id="wamid.out",
        status="read",
    )
    assert not await journal.update_delivery_status(
        connection_id=connection.id,
        remote_message_id="wamid.out",
        status="sent",
    )
    assert not await journal.update_delivery_status(
        connection_id=connection.id,
        remote_message_id="wamid.out",
        status="unknown-future-status",
    )
    await journal.update_listener_state(
        connection.id,
        "telegram",
        cursor="123",
        available=True,
        event_received=True,
    )
    assert await journal.listener_cursor(connection.id) == "123"

    record = await db.scalar(
        select(MessageModel).where(
            MessageModel.remote_message_id == "wamid.out"
        )
    )
    assert record is not None
    await db.refresh(record)
    assert record.status == "read"


def test_in_memory_deduplication_is_scoped_to_connection() -> None:
    inbound._reset_dedup_for_tests()  # pyright: ignore[reportPrivateUsage]
    message = MessageModel(
        connection_id=10,
        tool_id=3,
        platform="test",
        remote_message_id="same-remote-id",
        direction="inbound",
    )

    assert not inbound._already_seen(message)  # pyright: ignore[reportPrivateUsage]
    assert inbound._already_seen(message)  # pyright: ignore[reportPrivateUsage]
    message.connection_id = 11
    assert not inbound._already_seen(message)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_durable_redelivery_is_not_emitted_twice(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _connection(db)
    message = Message(
        id="matrix:$redelivered",
        platform="matrix",
        tool_id=connection.tool_id,
        sender=User(id="@alice:test", connection_id=connection.id),
        recipient=User(id="@bot:test", connection_id=connection.id),
        room=Room(id="!room:test"),
        text="Une seule livraison métier",
        time=int(datetime.now(timezone.utc).timestamp()),
    )
    received: list[str] = []

    async def receive(item: MessageModel) -> None:
        received.append(item.remote_message_id)

    signal = Signal("test_message_received")
    signal.connect(receive)
    monkeypatch.setattr(inbound, "message_received", signal)
    inbound._reset_dedup_for_tests()  # pyright: ignore[reportPrivateUsage]

    assert await inbound.dispatch_incoming(message)
    assert not await inbound.dispatch_incoming(message)
    assert received == ["matrix:$redelivered"]
