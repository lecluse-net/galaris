from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.messenger import facade, journal
from app.messenger.interface import Messenger
from app.messenger._observations import (
    ObservedMessengerFile as ObservedFile,
    ObservedMessengerMessage as Message,
    ObservedMessengerRoom as Room,
    ObservedMessengerUser as User,
)
from app.messenger import session as session_module
from app.messenger.models import Room as PersistedRoom
from app.messenger.models import MessengerUser as PersistedUser
from app.messenger.session import ConversationSessionSnapshot, build_conversation_session
from app.tools.models import Tool


async def _connection(db: AsyncSession) -> tuple[Connection, Agent]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Session {suffix}", gender="X")
    tool = Tool(
        code=f"session-messenger-{suffix}",
        label="Session messenger",
        description="",
        connection_schema={},
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Session",
        last_name="Agent",
        code=f"session-agent-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    return connection, agent


class _FakeMessenger(Messenger):
    kind = "telegram"

    def __init__(self, tool_id: int, connection_id: int, agent_id: int) -> None:
        self.tool_id = tool_id
        self._connection_id = connection_id
        self._agent_id = agent_id
        self._counter = 0

    async def send_to_room(
        self, room_id: str, text: str, reply_to: str | None = None
    ) -> Message:
        self._counter += 1
        return Message(
            id=f"out-{self._counter}",
            platform=self.kind,
            tool_id=self.tool_id,
            sender=User(
                id="bot",
                connection_id=self._connection_id,
                agent_id=self._agent_id,
            ),
            room=Room(id=room_id),
            text=text,
            reply_to=reply_to,
            time=200,
        )

    async def send_to_user(self, user_id: str, text: str) -> Message:
        return await self.send_to_room(user_id, text)

    async def history(self, room_id: str, limit: int = 20) -> list[Message]:
        del room_id, limit
        return []


def test_conversation_history_budget_preserves_complete_latest_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        session_module.runtime_settings,
        "MESSENGER_SESSION_MAX_MESSAGES",
        10,
    )
    monkeypatch.setattr(
        session_module.runtime_settings,
        "MESSENGER_SESSION_MAX_CHARS",
        1_000,
    )
    older_text = "a" * 600
    latest_text = "w" * 600
    messages = (
        {"id": "older", "text": older_text},
        {"id": "latest", "text": latest_text},
    )

    bounded, truncated = session_module._bounded_messages(  # pyright: ignore[reportPrivateUsage]
        messages,
        preserve_complete_messages=True,
    )

    assert bounded == ({"id": "latest", "text": latest_text},)
    assert truncated


@pytest.mark.parametrize(
    "identity_field",
    ["external_message_id", "id", "message_id", "messenger_message_id"],
)
def test_fallback_history_excludes_current_message_by_every_stable_identity(
    identity_field: str,
) -> None:
    current_id = str(uuid4())
    raw = {
        identity_field: current_id,
        "text": "Current message",
        "timestamp": 1_700_000_000,
    }

    assert (
        session_module._fallback_message(  # pyright: ignore[reportPrivateUsage]
            raw,
            agent_id=1,
            current_id=current_id,
        )
        is None
    )


class _Resolver:
    def __init__(self, messenger: Messenger) -> None:
        self.messenger = messenger

    async def messenger_for_connection(self, connection_id: int) -> Messenger:
        del connection_id
        return self.messenger

    async def messenger_for(self, tool_id: int, self_id: str) -> Messenger:
        del tool_id, self_id
        return self.messenger

    async def default_messenger(self) -> Messenger:
        return self.messenger


@pytest.mark.asyncio
async def test_outbound_delivery_populates_bounded_canonical_session(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, agent = await _connection(db)
    room_id = "room-42"
    inbound = Message(
        id="in-1",
        platform="telegram",
        tool_id=connection.tool_id,
        sender=User(
            id="human",
            display_name="Nicolas",
            connection_id=connection.id,
        ),
        room=Room(id=room_id),
        text="Bonsoir",
        attachments=[
            ObservedFile(
                id="provider-file-1",
                name="village.html",
                mime="text/html",
                size=123,
            )
        ],
        time=100,
    )
    current = inbound.model_copy(
        update={"id": "in-current", "text": "Message déclencheur", "time": 300}
    )
    assert await journal.persist_inbound(
        inbound, connection_id=connection.id, platform="telegram"
    )
    # The external sender is linked by the server to the agent's human manager.
    await db.execute(update(PersistedUser).where(
        PersistedUser.tool_id == connection.tool_id, PersistedUser.external_id == "human",
    ).values(galaris_user_id=agent.user_id))

    original_resolver = facade._resolver  # pyright: ignore[reportPrivateUsage]
    try:
        delegate = _FakeMessenger(connection.tool_id, connection.id, agent.id)
        facade.set_resolver(_Resolver(delegate))
        messenger = await facade.get_messenger(connection.id)
        sent = await messenger.send_to_room(room_id, "Bonsoir Nicolas")
        assert sent.remote_message_id == "out-1"
    finally:
        facade._resolver = original_resolver  # pyright: ignore[reportPrivateUsage]

    assert await journal.persist_inbound(
        current, connection_id=connection.id, platform="telegram"
    )
    future = current.model_copy(
        update={"id": "in-future", "text": "Message suivant", "time": 400}
    )
    assert await journal.persist_inbound(
        future, connection_id=connection.id, platform="telegram"
    )
    snapshot = await build_conversation_session(
        connection_id=connection.id,
        agent_id=agent.id,
        platform="telegram",
        room_id=room_id,
        current_message_id="in-current",
        fallback_history=(
            {
                "id": "in-1",
                "text": "stale duplicate",
                "time": 1,
                "sender": {"id": "human"},
            },
            {
                "text": "anonymous runtime duplicate",
                "time": 2,
                "sender": {"id": "human"},
            },
        ),
    )

    assert snapshot.scope == f"messenger:{connection.id}:{room_id}"
    assert [(row["id"], row["role"], row["text"]) for row in snapshot.messages] == [
        ("in-1", "user", "Bonsoir"),
        ("out-1", "assistant", "Bonsoir Nicolas"),
    ]
    assert cast(dict[str, object], snapshot.messages[0]["sender"])["display_name"] == "Nicolas"
    assert snapshot.messages[0]["messenger_message_id"]
    assert snapshot.messages[0]["room_id"]
    assert len(cast(list[object], snapshot.messages[0]["file_ids"])) == 1
    assert cast(list[dict[str, object]], snapshot.messages[0]["attachments"])[0][
        "local_id"
    ]
    assert cast(list[dict[str, object]], snapshot.messages[0]["attachments"])[0][
        "uri"
    ] == (
        f"{snapshot.messages[0]['tool_code']}://{snapshot.messages[0]['room_external_id']}/"
        f"{cast(list[object], snapshot.messages[0]['file_ids'])[0]}"
    )
    assert snapshot.messages[1]["sender_display_name"] == "Agent"
    assert all(row["id"] != "in-current" for row in snapshot.messages)
    assert all(row["id"] != "in-future" for row in snapshot.messages)

    from app.memory import MessengerContactObservation, observe_messenger_contact
    from app.messenger.models import Message as PersistedMessage

    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="telegram",
            user_id="human",
            display_name="Nicolas",
        )
    )
    other_contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="telegram",
            user_id="other-human",
            display_name="Other",
        )
    )
    await db.execute(
        update(PersistedMessage)
        .where(PersistedMessage.remote_message_id.in_(["in-1", "out-1"]))
        .values(contact_memory_item_id=contact_id)
    )
    other = inbound.model_copy(
        update={
            "id": "in-other",
            "text": "Other person's private context",
            "time": 150,
            "sender": User(
                id="other-human",
                display_name="Other",
                connection_id=connection.id,
            ),
        }
    )
    assert await journal.persist_inbound(
        other, connection_id=connection.id, platform="telegram"
    )
    await db.execute(
        update(PersistedMessage)
        .where(PersistedMessage.remote_message_id == "in-other")
        .values(contact_memory_item_id=other_contact_id)
    )
    cross_room = inbound.model_copy(
        update={
            "id": "in-cross-room",
            "room": Room(id="other-room"),
            "text": "Same person in another room",
            "time": 50,
        }
    )
    assert await journal.persist_inbound(
        cross_room, connection_id=connection.id, platform="telegram"
    )
    await db.execute(
        update(PersistedMessage)
        .where(PersistedMessage.remote_message_id == "in-cross-room")
        .values(contact_memory_item_id=contact_id)
    )
    await db.commit()
    exact_contact = await build_conversation_session(
        connection_id=connection.id,
        agent_id=agent.id,
        platform="telegram",
        room_id=room_id,
        current_message_id="in-current",
        contact_memory_item_id=contact_id,
    )
    assert [row["id"] for row in exact_contact.messages] == [
        "in-cross-room",
        "in-1",
        "out-1",
    ]
    assert all("private context" not in str(row["text"]) for row in exact_contact.messages)

    persisted_room = await db.scalar(
        select(PersistedRoom).where(
            PersistedRoom.connection_id == connection.id,
            PersistedRoom.external_id == room_id,
        )
    )
    assert persisted_room is not None
    canonical = await build_conversation_session(
        connection_id=connection.id,
        agent_id=agent.id,
        platform="telegram",
        room_id=str(persisted_room.id),
        current_message_id="in-current",
    )
    assert [(row["id"], row["text"]) for row in canonical.messages] == [
        ("in-1", "Bonsoir"),
        ("in-other", "Other person's private context"),
        ("out-1", "Bonsoir Nicolas"),
    ]

    monkeypatch.setattr(
        "app.messenger.session.runtime_settings.MESSENGER_SESSION_MAX_MESSAGES", 1
    )
    bounded = await build_conversation_session(
        connection_id=connection.id,
        agent_id=agent.id,
        platform="telegram",
        room_id=room_id,
        current_message_id="in-current",
    )
    assert len(bounded.messages) == 1
    assert bounded.messages[0]["id"] == "out-1"
    assert bounded.truncated


@pytest.mark.asyncio
async def test_canonical_session_keeps_persisted_file_only_message(
    db: AsyncSession,
) -> None:
    connection, agent = await _connection(db)
    external_room_id = "files-only-room"
    file_message = Message(
        id="file-only",
        platform="telegram",
        tool_id=connection.tool_id,
        sender=User(
            id="human",
            display_name="Nicolas",
            connection_id=connection.id,
        ),
        room=Room(id=external_room_id),
        text="",
        attachments=[
            ObservedFile(
                id="provider-file-only",
                name="rapport.pdf",
                mime="application/pdf",
                size=42,
            )
        ],
        time=100,
    )
    current = file_message.model_copy(
        update={
            "id": "current",
            "text": "Lis le rapport",
            "attachments": [],
            "time": 200,
        }
    )
    assert await journal.persist_inbound(
        file_message,
        connection_id=connection.id,
        platform="telegram",
    )
    assert await journal.persist_inbound(
        current,
        connection_id=connection.id,
        platform="telegram",
    )

    snapshot = await build_conversation_session(
        connection_id=connection.id,
        agent_id=agent.id,
        platform="telegram",
        room_id=external_room_id,
        current_message_id="current",
    )

    assert len(snapshot.messages) == 1
    historical = snapshot.messages[0]
    assert historical["text"] == ""
    attachments = cast(list[dict[str, object]], historical["attachments"])
    assert len(attachments) == 1
    assert attachments[0]["uri"] == (
        f"{historical['tool_code']}://{historical['room_external_id']}/"
        f"{attachments[0]['id']}"
    )


@pytest.mark.asyncio
async def test_session_provider_keeps_connection_scope_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = ConversationSessionSnapshot(
        scope="messenger:73:room-42",
        connection_id=73,
        platform="matrix",
        room_id="room-42",
        cursor="internal-cursor",
        messages=(),
    )
    monkeypatch.setattr(
        session_module,
        "build_conversation_session",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        session_module,
        "_resolve_connection_id",
        AsyncMock(return_value=73),
    )
    request = AgentContextRequest(
        task_id=None,
        agent=AgentSnapshot(
            id=7,
            code="session-agent",
            first_name="Session",
            last_name="Agent",
            driver_code="internal",
        ),
        objective="Reply",
        messenger_connection_id=73,
        message_platform="matrix",
        message_group_id="room-42",
        task_data={"sender_is_ai": True},
    )

    contribution = await session_module.session_context_provider(request)

    assert contribution.messaging_context["platform"] == "matrix"
    assert contribution.messaging_context["room_id"] == "room-42"
    assert "session_scope" not in contribution.messaging_context
    assert "session_cursor" not in contribution.messaging_context
    assert contribution.metadata["session_memory_scope"] == "messenger:73:room-42"


@pytest.mark.asyncio
async def test_session_provider_keeps_file_only_message_only_in_native_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    file_id = uuid4()
    snapshot = ConversationSessionSnapshot(
        scope=f"messenger:73:{room_id}",
        connection_id=73,
        platform="matrix",
        room_id=str(room_id),
        cursor="file-message",
        messages=(
            {
                "id": "file-message",
                "role": "user",
                "text": "",
                "attachments": [
                    {
                        "id": str(file_id),
                        "name": "rapport.pdf",
                        "uri": f"matrix-primary://!room:test/{file_id}",
                    }
                ],
            },
        ),
    )
    monkeypatch.setattr(
        session_module,
        "build_conversation_session",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        session_module,
        "_resolve_connection_id",
        AsyncMock(return_value=73),
    )
    request = AgentContextRequest(
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=7,
            code="session-agent",
            first_name="Session",
            last_name="Agent",
            driver_code="internal",
        ),
        objective="Inspect the file",
        messenger_connection_id=73,
        message_platform="matrix",
        message_group_id=str(room_id),
        task_data={"sender_is_ai": True},
    )

    contribution = await session_module.session_context_provider(request)

    assert contribution.conversation_history == snapshot.messages
    assert contribution.candidates == ()


@pytest.mark.asyncio
async def test_voice_context_keeps_answered_history_without_repeating_pending_input(
    db: AsyncSession,
) -> None:
    from app.memory import MessengerContactObservation, observe_messenger_contact
    from app.messenger.models import Message as PersistedMessage

    connection, agent = await _connection(db)
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="voice:test",
            user_id="caller",
            display_name="Caller",
        )
    )
    ids: list[str] = []
    # Repeating the same words in a later turn is legitimate. Exclusion must
    # follow message identity, never text equality.
    for index, text in enumerate(("Bonjour", "Bonjour", "Et demain ?", "Après")):
        row = await journal.persist_inbound(
            Message(
                id=f"voice-input-{index}",
                platform="voice:test",
                tool_id=connection.tool_id,
                sender=User(id="caller", connection_id=connection.id),
                room=Room(id="voice-room"),
                text=text,
                time=100 + index,
            ),
            connection_id=connection.id,
            platform="voice:test",
        )
        assert row
        message_id = await db.scalar(
            select(PersistedMessage.id).where(
                PersistedMessage.connection_id == connection.id,
                PersistedMessage.remote_message_id == f"voice-input-{index}",
            )
        )
        assert message_id is not None
        ids.append(str(message_id))
        await db.commit()
    await db.execute(
        update(PersistedMessage)
        .where(PersistedMessage.connection_id == connection.id)
        .values(contact_memory_item_id=contact_id)
    )
    await db.commit()
    contribution = await session_module.session_context_provider(
        AgentContextRequest(
            task_id=None,
            agent=AgentSnapshot(
                id=agent.id, code=agent.code,
                first_name=agent.first_name, last_name=agent.last_name,
                driver_code="internal",
            ),
            objective="Bonjour\n\nEt demain ?",
            messenger_connection_id=connection.id,
            message_platform="voice:test",
            message_group_id="voice-room",
            contact_memory_item_id=contact_id,
            task_data={
                "voice_call": True,
                "message_id": ids[2],
                "excluded_message_ids": ids[1:3],
            },
        )
    )
    assert [row["text"] for row in contribution.conversation_history or ()] == [
        "Bonjour",
    ]


@pytest.mark.asyncio
async def test_session_provider_excludes_conversation_trigger_from_fallback_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = ConversationSessionSnapshot(
        scope="messenger:73:room-42",
        connection_id=73,
        platform="matrix",
        room_id="room-42",
        cursor="cursor",
        messages=({"id": "older", "role": "user", "text": "3D HTML"},),
    )
    build = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(session_module, "build_conversation_session", build)
    monkeypatch.setattr(
        session_module,
        "_resolve_connection_id",
        AsyncMock(return_value=73),
    )
    request = AgentContextRequest(
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=7,
            code="session-agent",
            first_name="Session",
            last_name="Agent",
            driver_code="internal",
        ),
        objective="Build the Eiffel Tower",
        messenger_connection_id=73,
        message_platform="matrix",
        message_group_id="room-42",
        task_data={"origin": "conversation", "sender_is_ai": True},
        fallback_history=(
            {
                "external_message_id": "current-remote-id",
                "text": "Build the Eiffel Tower",
            },
        ),
    )

    contribution = await session_module.session_context_provider(request)

    assert contribution.conversation_history == snapshot.messages
    assert build.await_args.kwargs["current_message_id"] == "current-remote-id"


@pytest.mark.asyncio
async def test_session_provider_rejects_foreign_connection_before_history_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import connection_service

    monkeypatch.setattr(
        connection_service,
        "get_connection",
        AsyncMock(return_value=type("Connection", (), {"agent_id": 99})()),
    )
    build = AsyncMock()
    monkeypatch.setattr(session_module, "build_conversation_session", build)
    request = AgentContextRequest(
        task_id=None,
        agent=AgentSnapshot(
            id=7,
            code="session-agent",
            first_name="Session",
            last_name="Agent",
            driver_code="internal",
        ),
        objective="Reply",
        messenger_connection_id=73,
        message_platform="matrix",
        message_group_id="room-42",
    )

    contribution = await session_module.session_context_provider(request)

    assert contribution.conversation_history is None
    assert contribution.messaging_context == {}
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_provider_does_not_guess_connection_from_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = AsyncMock()
    monkeypatch.setattr(session_module, "build_conversation_session", build)
    request = AgentContextRequest(
        task_id=None,
        agent=AgentSnapshot(
            id=7,
            code="session-agent",
            first_name="Session",
            last_name="Agent",
            driver_code="internal",
        ),
        objective="Reply",
        message_platform="matrix",
        message_group_id="room-42",
    )

    contribution = await session_module.session_context_provider(request)

    assert contribution.conversation_history is None
    build.assert_not_awaited()
