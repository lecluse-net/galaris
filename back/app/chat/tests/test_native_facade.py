from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.agent.models import Title
from app.connection import Connection
from app.connection.models import ConnectionParam
from app.messenger import (
    CONVERSATION_OUTPUT_PENDING_METADATA_KEY,
    CONVERSATION_ROUND_METADATA_KEY,
    TASK_REQUESTED_METADATA_KEY,
    TASK_REASONING_EFFORT_METADATA_KEY,
    Capability,
    create_internal_room,
    get_internal_room,
    reconcile_internal_admissions,
)
from app.messenger import inbound, journal, native_facade
from app.messenger._observations import ObservedMessengerMessage
from app.messenger.interface import HistoryPage
from app.messenger.models import Message, MessengerUser, Room, RoomUser
from app.chat.provider import InternalMessenger
from app.conversation.models import ConversationRoundMessage
from app.topic import Topic
from app.tools import ToolModel as Tool
from core.database import get_db, get_db_session
from core.user import UserModel as User


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_request", [False, True])
async def test_room_list_survives_stalled_and_offline_providers(db, monkeypatch, cancel_request):
    agent, owner, _ = await _scope(db)
    tools = [Tool(code=f"slow-{uuid4().hex[:10]}", label="Slow provider", description="",
                  connection_schema={}, messenger_config={"service": "nextcloud_talk"}) for _ in range(7)]
    db.add_all(tools)
    await db.flush()
    connections = [Connection(tool_id=tool.id, agent_id=agent.id, active=True) for tool in tools]
    db.add_all(connections)
    await db.flush()
    rooms = [Room(connection_id=conn.id, external_id=f"slow-{i}", label=f"Room {i}",
                  kind="direct", conversation_type="text") for i, conn in enumerate(connections)]
    db.add_all(rooms)
    await db.flush()
    identities = [MessengerUser(tool_id=tool.id, external_id="agent", agent_id=agent.id,
                                is_ai=True) for tool in tools]
    db.add_all(identities)
    await db.flush()
    db.add_all([RoomUser(room_id=room.id, user_id=identity.id)
                for room, identity in zip(rooms, identities)])
    await db.flush()
    active = 0
    maximum = 0
    entered = asyncio.Event()
    cancelled = set()
    closed = set()
    clients = {}

    async def unread(index, room_ids):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            if index == 0:
                return {str(rooms[0].id): 7}
            if index == 1:
                raise ConnectionError("Provider offline")
            entered.set()
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.add(index)
            raise
        finally:
            active -= 1

    async def close(index):
        closed.add(index)
        if index >= 2:
            await asyncio.Future()  # The cleanup itself must also be bounded.

    for index, connection in enumerate(connections):
        async def read_counts(room_ids, index=index):
            return await unread(index, room_ids)

        async def close_client(index=index):
            await close(index)

        clients[connection.id] = SimpleNamespace(
            supports=lambda capability: capability == Capability.UNREAD,
            unread_counts=read_counts, close=close_client,
        )
    monkeypatch.setattr(native_facade, "get_messenger", AsyncMock(side_effect=lambda cid: clients[cid]))
    request = asyncio.create_task(native_facade.list_chat_rooms(owner.id, agent_id=agent.id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        if cancel_request:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, timeout=4)
        else:
            page = await asyncio.wait_for(request, timeout=12)
            assert {item.id for item in page.items} == {room.id for room in rooms}
            counts = {item.id: item.unread_count for item in page.items}
            assert counts[rooms[0].id] == 7
            assert counts[rooms[1].id] == 0
        assert maximum <= 4
        assert active == 0
        assert cancelled
        assert cancelled <= closed
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)


async def _scope(db: AsyncSession) -> tuple[Agent, User, User]:
    suffix = uuid4().hex[:10]
    tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
    if tool is None:
        tool = Tool(
            code="chat",
            label="Chat",
            description="",
            connection_schema={},
            messenger_config={"service": "internal"},
        )
        db.add(tool)
        await db.flush()
    owner = User(
        email=f"owner-{suffix}@example.test",
        display_name="Owner",
        hashed_password="unused",
        is_active=True,
    )
    member = User(
        email=f"member-{suffix}@example.test",
        display_name="Member",
        hashed_password="unused",
        is_active=True,
    )
    db.add_all([owner, member])
    await db.flush()
    title = Title(label=f"Internal {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        user_id=owner.id,
        title_id=title.id,
        first_name="Native",
        last_name="Agent",
        code=f"native-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    db.add(Connection(tool_id=tool.id, agent_id=agent.id, active=True))
    await db.flush()
    return agent, owner, member


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_mode", ["button", "text"])
@pytest.mark.parametrize("selected_option, selected_label", [("create", "Créer"), ("reject", "Refuser")])
async def test_internal_choices_reload_and_resolve_once_in_the_exact_human_scope(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, answer_mode: str,
    selected_option: str, selected_label: str,
) -> None:
    from app.messenger import (
        ChoiceOption, ChoiceRequest, MessengerFacade, create_choice,
        answer_internal_interaction, read_internal_interaction, resolve_from_message,
    )
    from app.messenger import interactions
    from app.messenger.models import Interaction

    agent, owner, other = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    another_room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None and another_room is not None
    messenger = MessengerFacade(await InternalMessenger.from_connection_id(room.connection_id), room.connection_id)
    handler = AsyncMock()
    monkeypatch.setitem(interactions._choice_handlers, "internal-choice-test", handler)
    from app.chat import events

    emitted = AsyncMock()
    monkeypatch.setattr(events.websocket, "emit", emitted)
    interactions.interaction_changed.connect(events._publish_interaction, required=False)
    pending = await create_choice(
        messenger, agent_id=agent.id, room_id=str(room.id), user_id=f"user:{owner.id}",
        request=ChoiceRequest(
            kind="internal-choice-test", title="Créer le dossier ?", body="Description conservée.",
            options=[ChoiceOption(id="create", label="Créer"), ChoiceOption(id="reject", label="Refuser")],
            language="fr", metadata={"private_domain_payload": "not-for-the-client"},
        ),
    )
    page = await native_facade.list_chat_messages(owner.id, room.id)
    assert page is not None and len(page.items) == 1
    message = page.items[0]
    assert "1. Créer" in message.text  # Canonical text remains usable by text-only readers.
    assert message.interaction is not None and message.interaction.can_answer
    assert "private_domain_payload" not in message.model_dump_json()
    assert message.interaction.options[0].id == "create"
    assert any(
        event.args[:2] == ("chat", "message")
        and event.args[2] == {"room_id": str(room.id), "message_id": str(message.id), "is_new": False}
        for event in emitted.await_args_list
    )
    emitted.reset_mock()
    impersonated = await native_facade.list_chat_messages(owner.id, room.id, agent_id=agent.id)
    assert impersonated is not None and impersonated.items[0].interaction is not None
    assert not impersonated.items[0].interaction.can_answer
    for actor, target_room in [(other.id, room.id), (owner.id, another_room.id)]:
        with pytest.raises(LookupError):
            await answer_internal_interaction(actor, target_room, pending.id, option_id="create")
    with pytest.raises(ValueError):
        await answer_internal_interaction(owner.id, room.id, pending.id, option_id="invented")
    handler.assert_not_awaited()
    assert await db.scalar(select(Message).where(Message.direction == "inbound")) is None
    if answer_mode == "button":
        result = await answer_internal_interaction(owner.id, room.id, pending.id, option_id=selected_option)
        assert result.status == "RESOLVED" and result.selected_option_id == selected_option
        await answer_internal_interaction(owner.id, room.id, pending.id, option_id=selected_option)
    else:
        incoming = Message(connection_id=room.connection_id, tool_id=messenger.tool_id, text=selected_label, direction="inbound")
        incoming.room = await db.get(Room, room.id)
        incoming.sender = await db.scalar(select(MessengerUser).where(MessengerUser.tool_id == messenger.tool_id, MessengerUser.external_id == f"user:{owner.id}"))
        assert await resolve_from_message(incoming, agent_id=agent.id) is not None
    handler.assert_awaited_once()
    if answer_mode == "button":
        from app.messenger.session import build_conversation_session

        history = await build_conversation_session(
            connection_id=room.connection_id,
            agent_id=agent.id,
            platform="internal",
            room_id=str(room.id),
        )
        answers = [entry for entry in history.messages if entry["role"] == "user"]
        assert len(answers) == 1
        assert selected_label in answers[0]["text"]
        assert pending.reference in answers[0]["text"]
        assert "Créer le dossier ?" in answers[0]["text"]
        assert answers[0]["sender_external_id"] == f"user:{owner.id}"
        assert answers[0]["reply_to"] == message.external_id
        assert "private_domain_payload" not in str(answers)
        stored_answer = await db.get(Message, UUID(answers[0]["messenger_message_id"]))
        assert stored_answer is not None and stored_answer.status == "admitted"
        assert stored_answer.requester_user_id == owner.id
        assert stored_answer.contact_memory_item_id is not None
        contact_history = await build_conversation_session(
            connection_id=room.connection_id, agent_id=agent.id, platform="internal",
            room_id=str(room.id), contact_memory_item_id=stored_answer.contact_memory_item_id,
        )
        assert [entry["text"] for entry in contact_history.messages] == [answers[0]["text"]]
    assert len([
        event for event in emitted.await_args_list
        if event.args[:2] == ("chat", "message") and event.args[2].get("is_new") is False
    ]) == 2  # Capture and completion invalidate the prompt, including textual replies.
    assert await db.scalar(select(ConversationRoundMessage)) is None
    other_option = "reject" if selected_option == "create" else "create"
    with pytest.raises(ValueError):
        await answer_internal_interaction(owner.id, room.id, pending.id, option_id=other_option)
    reloaded = await native_facade.list_chat_messages(owner.id, room.id)
    assert reloaded is not None
    choice = next(item.interaction for item in reloaded.items if item.id == message.id)
    assert choice is not None and choice.status == "RESOLVED" and not choice.can_answer
    assert choice.selected_option_id == selected_option

    expired = await create_choice(
        messenger, agent_id=agent.id, room_id=str(room.id), user_id=f"user:{owner.id}",
        request=ChoiceRequest(kind="internal-choice-test", title="Ancienne demande", options=[ChoiceOption(id="yes", label="Oui")]),
    )
    record = await db.get(Interaction, expired.id)
    assert record is not None
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert (await read_internal_interaction(owner.id, room.id, expired.id)).status == "EXPIRED"
    with pytest.raises(ValueError):
        await answer_internal_interaction(owner.id, room.id, expired.id, option_id="yes")
    handler.assert_awaited_once()
    persisted_answers = (await db.scalars(select(Message).where(Message.direction == "inbound"))).all()
    assert len(persisted_answers) == (1 if answer_mode == "button" else 0)


@pytest.mark.asyncio
async def test_button_answer_is_journaled_before_handler_and_survives_its_retry(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import (
        ChoiceOption, ChoiceRequest, MessengerFacade, answer_internal_interaction, create_choice,
    )
    from app.messenger import interactions
    from app.messenger.models import Interaction
    from app.messenger.session import build_conversation_session

    agent, owner, _other = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    messenger = MessengerFacade(await InternalMessenger.from_connection_id(room.connection_id), room.connection_id)
    histories = []

    async def handler(choice, resolution):
        snapshot = await build_conversation_session(
            connection_id=room.connection_id, agent_id=agent.id,
            platform="internal", room_id=str(room.id),
        )
        histories.append([entry for entry in snapshot.messages if entry["role"] == "user"])
        if len(histories) == 1:
            raise RuntimeError("Temporary handler failure")

    monkeypatch.setitem(interactions._choice_handlers, "button-retry-test", handler)
    pending = await create_choice(
        messenger, agent_id=agent.id, room_id=str(room.id), user_id=f"user:{owner.id}",
        request=ChoiceRequest(
            kind="button-retry-test", title="Autoriser la publication ?",
            options=[ChoiceOption(id="once", label="Autoriser une fois")],
        ),
    )
    result = await answer_internal_interaction(owner.id, room.id, pending.id, option_id="once")
    assert result.status == "PROCESSING"
    assert len(histories) == 1 and len(histories[0]) == 1
    assert "Autoriser une fois" in histories[0][0]["text"]
    assert pending.reference in histories[0][0]["text"]

    await answer_internal_interaction(owner.id, room.id, pending.id, option_id="once")
    record = await db.get(Interaction, pending.id)
    assert record is not None
    record.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await interactions.retry_pending_interactions()
    await db.refresh(record)
    assert record.status == "RESOLVED"
    assert histories == [histories[0], histories[0]]
    assert await db.scalar(select(ConversationRoundMessage)) is None


@pytest.mark.asyncio
async def test_room_creation_creates_distinct_threads_with_numbered_labels(
    db: AsyncSession,
) -> None:
    agent, owner, member = await _scope(db)
    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert room is not None
    agent_id = agent.id
    owner_id = owner.id
    member_id = member.id
    room_id = room.id
    second_room = await create_internal_room(
        actor_user_id=owner_id,
        agent_id=agent_id,
    )
    third_room = await create_internal_room(
        actor_user_id=owner_id,
        agent_id=agent_id,
    )

    assert second_room is not None
    assert third_room is not None
    assert len({room.id, second_room.id, third_room.id}) == 3
    external_ids = {
        room.external_id,
        second_room.external_id,
        third_room.external_id,
    }
    assert len(external_ids) == 3
    assert room.kind == second_room.kind == third_room.kind == "direct"
    assert [room.label, second_room.label, third_room.label] == [
        "Native Agent",
        "Native Agent (2)",
        "Native Agent (3)",
    ]
    assert third_room.topic_id is None

    # HTTP request sessions do not auto-commit: the facade must make the room
    # and both memberships durable before the following authorized requests.
    await db.rollback()
    persisted = await get_internal_room(owner_id, room_id)
    assert persisted is not None

    tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
    assert tool is not None
    legacy_member = MessengerUser(
        tool_id=tool.id,
        external_id=f"user:{member_id}",
        display_name="Member",
        is_ai=False,
    )
    db.add(legacy_member)
    await db.flush()
    db.add(RoomUser(room_id=room_id, user_id=legacy_member.id, role="member"))
    await db.flush()

    persisted = await get_internal_room(owner_id, room_id)
    assert persisted is not None
    assert {item.external_id for item in persisted.members} == {
        f"agent:{agent_id}",
        f"user:{owner_id}",
    }
    assert await get_internal_room(member_id, room_id) is None


@pytest.mark.asyncio
async def test_room_creation_persists_label_topic_and_private_preview(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    topic = Topic(title="Création", description="", keywords=[])
    db.add(topic)
    await db.flush()

    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
        label="Conversation confidentielle",
        topic_id=topic.id,
        show_last_message=False,
    )

    assert room is not None
    assert room.label == "Conversation confidentielle"
    assert room.topic_id == topic.id
    assert room.show_last_message is False
    stored = await db.get(Room, room.id)
    assert stored is not None
    assert stored.label == "Conversation confidentielle"
    assert stored.topic_id == topic.id
    owner_membership = await db.scalar(
        select(RoomUser)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(
            RoomUser.room_id == room.id,
            MessengerUser.galaris_user_id == owner.id,
        )
    )
    assert owner_membership is not None
    assert owner_membership.show_last_message is False


@pytest.mark.asyncio
async def test_archived_chat_rooms_are_hidden_by_default_and_can_be_restored(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert room is not None
    assert room.archived is False

    archived = await native_facade.set_chat_room_archived(
        owner.id,
        room.id,
        True,
    )

    assert archived is not None
    assert archived.archived is True
    assert (await native_facade.list_chat_rooms(owner.id)).items == []
    archived_page = await native_facade.list_chat_rooms(
        owner.id,
        include_archived=True,
    )
    assert [item.id for item in archived_page.items] == [room.id]
    assert archived_page.items[0].archived is True

    restored = await native_facade.set_chat_room_archived(
        owner.id,
        room.id,
        False,
    )

    assert restored is not None
    assert restored.archived is False
    assert [
        item.id for item in (await native_facade.list_chat_rooms(owner.id)).items
    ] == [room.id]


@pytest.mark.asyncio
async def test_room_creation_refuses_an_inactive_agent_connection(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    connection = await db.scalar(
        select(Connection).where(Connection.agent_id == agent.id)
    )
    assert connection is not None
    connection.active = False
    await db.flush()

    assert await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    ) is None


@pytest.mark.asyncio
async def test_chat_rooms_expose_the_effective_messenger_state(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert room is not None
    monkeypatch.setattr(
        native_facade,
        "is_kind_enabled",
        lambda kind: kind == "internal",
    )

    active_page = await native_facade.list_chat_rooms(owner.id)

    assert active_page.items[0].messenger_label == "Chat"
    assert active_page.items[0].messenger_active is True

    connection = await db.scalar(
        select(Connection).where(Connection.id == room.connection_id)
    )
    assert connection is not None
    connection.active = False
    await db.flush()

    inactive_page = await native_facade.list_chat_rooms(owner.id)

    assert inactive_page.items[0].id == room.id
    assert inactive_page.items[0].messenger_active is False


@pytest.mark.asyncio
async def test_internal_messenger_lists_humans_and_reuses_the_latest_direct_room(
    db: AsyncSession,
) -> None:
    agent, owner, member = await _scope(db)
    first_room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    second_room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert first_room is not None
    assert second_room is not None

    first_record = await db.get(Room, first_room.id)
    second_record = await db.get(Room, second_room.id)
    assert first_record is not None
    assert second_record is not None
    first_record.updated_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    second_record.updated_at = datetime.now(timezone.utc)
    await db.commit()

    connection = await db.scalar(
        select(Connection).where(Connection.agent_id == agent.id)
    )
    assert connection is not None
    messenger = await InternalMessenger.from_connection_id(connection.id)

    contacts = await messenger.search_users("own")

    assert [(contact.id, contact.display_name) for contact in contacts] == [
        (f"user:{owner.id}", "Owner")
    ]
    assert await messenger.search_users(member.email) == []
    assert Capability.SEARCH_USERS in messenger.capabilities

    resolved_room = await messenger.ensure_direct_room(f"user:{owner.id}")
    assert resolved_room.local_id == second_room.id
    with pytest.raises(LookupError, match="No direct Chat room"):
        await messenger.ensure_direct_room(f"user:{member.id}")


@pytest.mark.asyncio
async def test_chat_filters_external_rooms_by_linked_identity_and_agent_view(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, owner, _member = await _scope(db)
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"talk-{suffix}",
        label="Nextcloud Talk",
        description="",
        connection_schema={},
        messenger_config={"service": "nextcloud_talk"},
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    nicolas = MessengerUser(
        tool_id=tool.id,
        external_id="nicolas",
        display_name="Nicolas",
        is_ai=False,
    )
    other = MessengerUser(
        tool_id=tool.id,
        external_id="someone-else",
        display_name="Someone else",
        is_ai=False,
    )
    bot = MessengerUser(
        tool_id=tool.id,
        external_id="aster",
        display_name="Aster",
        agent_id=agent.id,
        is_ai=True,
    )
    db.add_all([nicolas, other, bot])
    await db.flush()
    own_room = Room(
        connection_id=connection.id,
        external_id=f"own-{suffix}",
        label="Nicolas",
        kind="direct",
        conversation_type="text",
    )
    other_room = Room(
        connection_id=connection.id,
        external_id=f"other-{suffix}",
        label="Someone else",
        kind="direct",
        conversation_type="text",
    )
    audio_room = Room(
        connection_id=connection.id,
        external_id=f"nextcloud_talk:call:{suffix}",
        label="Nextcloud Talk audio",
        kind="direct",
        conversation_type="audio",
    )
    db.add_all([own_room, other_room, audio_room])
    await db.flush()
    db.add_all(
        [
            RoomUser(room_id=own_room.id, user_id=nicolas.id),
            RoomUser(room_id=own_room.id, user_id=bot.id),
            RoomUser(room_id=other_room.id, user_id=other.id),
            RoomUser(room_id=other_room.id, user_id=bot.id),
            RoomUser(room_id=audio_room.id, user_id=nicolas.id),
            RoomUser(room_id=audio_room.id, user_id=bot.id),
        ]
    )
    await db.flush()
    db.add(
        Message(
            connection_id=connection.id,
            tool_id=tool.id,
            platform="nextcloud_talk",
            remote_message_id=f"private-preview-{suffix}",
            direction="inbound",
            messenger_room_id=own_room.id,
            messenger_user_id=nicolas.id,
            sender_messenger_user_id=nicolas.id,
            room_id=own_room.external_id,
            user_id=nicolas.external_id,
            text="Message confidentiel",
        )
    )
    await db.flush()

    assert (await native_facade.list_chat_rooms(owner.id)).items == []
    mapping = await native_facade.set_chat_identity_mapping(
        owner.id,
        tool.id,
        "nicolas",
    )
    assert mapping is not None
    assert mapping.source == "nextcloud_talk"

    provider = SimpleNamespace(
        supports=lambda capability: capability == Capability.UNREAD,
        unread_counts=AsyncMock(
            side_effect=[
                {str(own_room.id): 0},
                {str(own_room.id): 7},
                {str(own_room.id): 0},
                {str(own_room.id): 0},
                {str(own_room.id): 0},
            ]
        ),
        mark_read=AsyncMock(),
        close=AsyncMock(),
    )
    get_provider = AsyncMock(return_value=provider)
    monkeypatch.setattr(native_facade, "get_messenger", get_provider)

    page = await native_facade.list_chat_rooms(owner.id)
    assert [room.id for room in page.items] == [own_room.id]
    assert page.items[0].source == "nextcloud_talk"
    assert page.items[0].writable is False
    assert page.items[0].agent_id == agent.id
    assert page.items[0].agent_name == "Native Agent"
    assert page.items[0].last_message is not None
    assert page.items[0].last_message.text == "Message confidentiel"
    assert page.items[0].unread_count == 0
    received = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="nextcloud_talk",
        remote_message_id=f"private-reply-{suffix}",
        direction="outbound",
        messenger_room_id=own_room.id,
        messenger_user_id=None,
        sender_messenger_user_id=bot.id,
        room_id=own_room.external_id,
        user_id=None,
        text="Réponse de Aster",
        metadata_={"sender_id": bot.external_id},
        created_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    db.add(received)
    await db.flush()
    unread_page = await native_facade.list_chat_rooms(owner.id)
    assert unread_page.items[0].unread_count == 7

    latest_received = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="nextcloud_talk",
        remote_message_id=f"private-latest-reply-{suffix}",
        direction="outbound",
        messenger_room_id=own_room.id,
        messenger_user_id=None,
        sender_messenger_user_id=bot.id,
        room_id=own_room.external_id,
        user_id=None,
        text="Nouvelle réponse de Aster",
        metadata_={"sender_id": bot.external_id},
        created_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    db.add(latest_received)
    await db.flush()
    locally_unread_page = await native_facade.list_chat_rooms(owner.id)
    assert locally_unread_page.items[0].unread_count == 2

    assert await native_facade.mark_chat_room_read(
        owner.id,
        own_room.id,
        latest_received.id,
    )
    read_page = await native_facade.list_chat_rooms(owner.id)
    assert read_page.items[0].unread_count == 0
    provider.mark_read.assert_awaited_once_with(
        own_room.id,
        latest_received.remote_message_id,
    )
    internal_only_page = await native_facade.list_chat_rooms(
        owner.id,
        include_external=False,
    )
    assert internal_only_page.items == []
    assert internal_only_page.total == 0

    customized = await native_facade.update_chat_room_preferences(
        owner.id,
        own_room.id,
        label="Projet privé",
        show_last_message=False,
    )
    assert customized is not None
    assert customized.label == "Projet privé"
    assert customized.show_last_message is False
    assert customized.last_message is not None
    assert customized.last_message.text == "Nouvelle réponse de Aster"
    await db.refresh(own_room)
    assert own_room.label == "Nicolas"
    assert [
        room.id
        for room in (
            await native_facade.list_chat_rooms(owner.id, search="Projet privé")
        ).items
    ] == [own_room.id]

    provider = SimpleNamespace(
        history_page=AsyncMock(
            side_effect=[
                HistoryPage(messages=[], has_more=True, next_cursor="older"),
                HistoryPage(messages=[], has_more=False, next_cursor=None),
            ]
        ),
        close=AsyncMock(),
    )
    get_messenger = AsyncMock(return_value=provider)
    monkeypatch.setattr(native_facade, "get_messenger", get_messenger)

    first_history = await native_facade.list_chat_messages(owner.id, own_room.id)
    second_history = await native_facade.list_chat_messages(
        owner.id,
        own_room.id,
        page=2,
        history_cursor="older",
    )

    assert first_history is not None and first_history.total == 3
    assert second_history is not None and second_history.total == 3
    assert first_history.provider_history is True
    assert first_history.history_has_more is True
    assert first_history.history_next_cursor == "older"
    assert second_history.provider_history is True
    assert second_history.history_has_more is False
    assert second_history.history_next_cursor is None
    assert get_messenger.await_count == 2
    assert all(call.args == (connection.id,) for call in get_messenger.await_args_list)
    assert provider.history_page.await_args_list[0].kwargs == {
        "limit": 50,
        "cursor": None,
    }
    assert provider.history_page.await_args_list[1].kwargs == {
        "limit": 50,
        "cursor": "older",
    }
    assert provider.close.await_count == 2

    agent_page = await native_facade.list_chat_rooms(owner.id, agent_id=agent.id)
    assert {room.id for room in agent_page.items} == {own_room.id, other_room.id}
    assert not await native_facade.has_chat_room_access(owner.id, audio_room.id)
    assert not await native_facade.has_agent_chat_room_access(agent.id, audio_room.id)
    assert not await native_facade.has_ai_chat_room_access(audio_room.id)
    assert await native_facade.get_chat_room(owner.id, audio_room.id) is None
    assert await native_facade.get_agent_chat_room(agent.id, audio_room.id) is None

    assert await native_facade.clear_chat_identity_mapping(owner.id, tool.id)
    assert (await native_facade.list_chat_rooms(owner.id)).items == []


@pytest.mark.asyncio
async def test_chat_excludes_mail_rooms_without_deleting_them(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    discussion = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert discussion is not None

    suffix = uuid4().hex[:10]
    mail_tool = await db.scalar(select(Tool).where(Tool.code == "mail"))
    if mail_tool is None:
        mail_tool = Tool(
            code="mail",
            label="Mail",
            description="",
            connection_schema={},
            messenger_config={"service": "mail"},
        )
        db.add(mail_tool)
        await db.flush()
    connection = Connection(tool_id=mail_tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    sender = MessengerUser(
        tool_id=mail_tool.id,
        external_id=f"sender-{suffix}@example.test",
        display_name="Mail sender",
        galaris_user_id=owner.id,
        is_ai=False,
    )
    recipient = MessengerUser(
        tool_id=mail_tool.id,
        external_id=f"mailbox-{suffix}@example.test",
        display_name="Agent mailbox",
        agent_id=agent.id,
        is_ai=True,
    )
    db.add_all([sender, recipient])
    await db.flush()
    mail_room = Room(
        connection_id=connection.id,
        external_id=f"INBOX:{suffix}",
        label="One incoming email",
        kind="direct",
        conversation_type="text",
    )
    db.add(mail_room)
    await db.flush()
    db.add_all(
        [
            RoomUser(room_id=mail_room.id, user_id=sender.id),
            RoomUser(room_id=mail_room.id, user_id=recipient.id),
        ]
    )
    await db.flush()

    user_page = await native_facade.list_chat_rooms(owner.id)
    agent_page = await native_facade.list_chat_rooms(owner.id, agent_id=agent.id)
    internal_only_page = await native_facade.list_chat_rooms(
        owner.id,
        include_external=False,
    )

    assert [room.id for room in user_page.items] == [discussion.id]
    assert [room.id for room in agent_page.items] == [discussion.id]
    assert [room.id for room in internal_only_page.items] == [discussion.id]
    assert await db.get(Room, mail_room.id) is mail_room


@pytest.mark.asyncio
async def test_chat_hides_legacy_internal_call_rooms(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    discussion = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert discussion is not None
    owner_identity = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    agent_identity = await db.scalar(
        select(MessengerUser).where(MessengerUser.agent_id == agent.id)
    )
    assert owner_identity is not None
    assert agent_identity is not None
    legacy_call = Room(
        connection_id=discussion.connection_id,
        external_id=f"webrtc:call:{uuid4()}",
        label=f"webrtc audio — {discussion.external_id}",
        kind="direct",
        conversation_type="audio",
    )
    db.add(legacy_call)
    await db.flush()
    db.add_all(
        [
            RoomUser(room_id=legacy_call.id, user_id=owner_identity.id, role="owner"),
            RoomUser(room_id=legacy_call.id, user_id=agent_identity.id, role="member"),
        ]
    )
    await db.flush()

    page = await native_facade.list_chat_rooms(owner.id)

    assert [room.id for room in page.items] == [discussion.id]


@pytest.mark.asyncio
async def test_chat_history_uses_pages_of_fifty_latest_messages(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    sender = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    assert sender is not None
    history_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add_all(
        [
            Message(
                connection_id=room.connection_id,
                tool_id=sender.tool_id,
                platform="internal",
                remote_message_id=f"history-{index}-{uuid4()}",
                direction="inbound",
                messenger_room_id=room.id,
                messenger_user_id=sender.id,
                room_id=room.external_id,
                user_id=sender.external_id,
                text=f"Message {index}",
                created_at=history_start + timedelta(seconds=index),
            )
            for index in range(105)
        ]
    )
    await db.flush()

    newest = await native_facade.list_chat_messages(owner.id, room.id)
    older = await native_facade.list_chat_messages(owner.id, room.id, page=2)
    oldest = await native_facade.list_chat_messages(owner.id, room.id, page=3)

    assert newest is not None and older is not None and oldest is not None
    assert newest.page_size == 50
    assert len(newest.items) == 50
    assert len(older.items) == 50
    assert len(oldest.items) == 5
    assert [message.text for message in newest.items] == [
        f"Message {index}" for index in range(55, 105)
    ]
    assert [message.text for message in older.items] == [
        f"Message {index}" for index in range(5, 55)
    ]
    assert [message.text for message in oldest.items] == [
        f"Message {index}" for index in range(5)
    ]
    assert all(message.is_mine for message in newest.items + older.items + oldest.items)
    exact = await native_facade.get_chat_message(
        owner.id,
        room.id,
        older.items[0].id,
    )
    assert exact is not None
    assert exact.id == older.items[0].id
    assert exact.text == older.items[0].text
    assert await native_facade.get_chat_message(
        owner.id,
        room.id,
        uuid4(),
    ) is None


@pytest.mark.asyncio
async def test_chat_history_hides_conversation_output_until_round_link_commit(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    sender = await db.scalar(
        select(MessengerUser).where(MessengerUser.agent_id == agent.id)
    )
    assert sender is not None
    round_id = uuid4()
    pending = Message(
        connection_id=room.connection_id,
        tool_id=sender.tool_id,
        platform="internal",
        remote_message_id=f"pending-output-{uuid4()}",
        direction="outbound",
        messenger_room_id=room.id,
        room_id=room.external_id,
        text="Réponse atomique",
        metadata_={
            "sender_id": sender.external_id,
            CONVERSATION_OUTPUT_PENDING_METADATA_KEY: True,
            CONVERSATION_ROUND_METADATA_KEY: str(round_id),
        },
    )
    db.add(pending)
    await db.flush()

    hidden = await native_facade.list_chat_messages(owner.id, room.id)

    assert hidden is not None
    assert hidden.total == 0
    assert hidden.items == []

    pending.metadata_ = {
        "sender_id": sender.external_id,
        CONVERSATION_ROUND_METADATA_KEY: str(round_id),
    }
    await db.flush()

    visible = await native_facade.list_chat_messages(owner.id, room.id)

    assert visible is not None
    assert visible.total == 1
    assert [message.id for message in visible.items] == [pending.id]


@pytest.mark.asyncio
async def test_chat_message_agent_ids_follow_authors_not_filtered_room_members(
    db: AsyncSession,
) -> None:
    primary_agent, owner, _member = await _scope(db)
    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=primary_agent.id,
    )
    assert room is not None
    tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
    primary_identity = await db.scalar(
        select(MessengerUser).where(MessengerUser.agent_id == primary_agent.id)
    )
    human_identity = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    assert tool is not None and primary_identity is not None and human_identity is not None

    secondary_title = Title(label=f"Secondary {uuid4().hex[:10]}", gender="X")
    db.add(secondary_title)
    await db.flush()
    secondary_agent = Agent(
        user_id=owner.id,
        title_id=secondary_title.id,
        first_name="Orion",
        last_name="Test",
        code=f"orion-{uuid4().hex[:10]}",
        agent_driver="internal",
    )
    db.add(secondary_agent)
    await db.flush()
    secondary_identity = MessengerUser(
        tool_id=tool.id,
        agent_id=secondary_agent.id,
        external_id=f"agent:{secondary_agent.id}",
        display_name="Orion Test",
        is_ai=True,
    )
    db.add(secondary_identity)
    await db.flush()
    db.add(
        RoomUser(
            room_id=room.id,
            user_id=secondary_identity.id,
            role="member",
        )
    )
    for sender, direction, text in (
        (primary_identity, "outbound", "Aster"),
        (secondary_identity, "inbound", "Orion"),
        (human_identity, "inbound", "Humain"),
    ):
        db.add(
            Message(
                connection_id=room.connection_id,
                tool_id=tool.id,
                platform="internal",
                remote_message_id=f"speech-author-{uuid4()}",
                direction=direction,
                messenger_room_id=room.id,
                messenger_user_id=(sender.id if direction == "inbound" else None),
                room_id=room.external_id,
                user_id=(sender.external_id if direction == "inbound" else None),
                text=text,
                metadata_={
                    "sender_id": sender.external_id,
                    "sender_is_ai": sender.is_ai,
                    "sender_agent_id": sender.agent_id,
                },
            )
        )
    await db.flush()

    projected_room = await native_facade.get_chat_room(owner.id, room.id)
    assert projected_room is not None
    assert secondary_agent.id not in {
        member.agent_id for member in projected_room.members
    }

    author_ids = await native_facade.list_chat_message_agent_ids(owner.id, room.id)

    assert author_ids == sorted([primary_agent.id, secondary_agent.id])


@pytest.mark.asyncio
async def test_nextcloud_message_authors_resolve_agents_from_login_connections(
    db: AsyncSession,
) -> None:
    primary_agent, owner, _member = await _scope(db)
    suffix = uuid4().hex[:10]
    tool = Tool(
        code=f"nextcloud-authors-{suffix}",
        label="Nextcloud Talk",
        description="",
        connection_schema={
            "params": {
                "nextcloud_login": {"type": "string"},
                "nextcloud_password": {"type": "password"},
            }
        },
        messenger_config={
            "service": "nextcloud_talk",
            "settings": {"base_url": "https://cloud.example.test"},
            "param_map": {
                "login": "nextcloud_login",
                "password": "nextcloud_password",
            },
        },
    )
    db.add(tool)
    await db.flush()
    primary_connection = Connection(
        tool_id=tool.id,
        agent_id=primary_agent.id,
        active=True,
    )
    db.add(primary_connection)
    await db.flush()
    db.add(
        ConnectionParam(
            connection_id=primary_connection.id,
            param_name="nextcloud_login",
            param_value="astertest",
        )
    )

    secondary_title = Title(label=f"Orion {suffix}", gender="X")
    db.add(secondary_title)
    await db.flush()
    secondary_agent = Agent(
        user_id=owner.id,
        title_id=secondary_title.id,
        first_name="Orion",
        last_name="Test",
        code=f"orion-nextcloud-{suffix}",
        agent_driver="internal",
    )
    db.add(secondary_agent)
    await db.flush()
    secondary_connection = Connection(
        tool_id=tool.id,
        agent_id=secondary_agent.id,
        active=True,
    )
    db.add(secondary_connection)
    await db.flush()
    db.add(
        ConnectionParam(
            connection_id=secondary_connection.id,
            param_name="nextcloud_login",
            param_value="orion-demo-test",
        )
    )

    primary_identity = MessengerUser(
        tool_id=tool.id,
        external_id="astertest",
        display_name="Aster Test",
        agent_id=primary_agent.id,
        is_ai=True,
    )
    secondary_identity = MessengerUser(
        tool_id=tool.id,
        external_id="orion-demo-test",
        display_name="Orion Test",
        agent_id=None,
        is_ai=False,
    )
    db.add_all([primary_identity, secondary_identity])
    await db.flush()
    room = Room(
        connection_id=primary_connection.id,
        external_id=f"talk-{suffix}",
        label="Aster et Orion",
        kind="group",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    db.add_all(
        [
            RoomUser(room_id=room.id, user_id=primary_identity.id),
            RoomUser(room_id=room.id, user_id=secondary_identity.id),
            Message(
                connection_id=primary_connection.id,
                tool_id=tool.id,
                platform="nextcloud_talk",
                remote_message_id=f"aster-{suffix}",
                direction="outbound",
                messenger_room_id=room.id,
                messenger_user_id=None,
                room_id=room.external_id,
                user_id=None,
                text="Message de Aster",
                metadata_={"sender_id": "astertest"},
            ),
            Message(
                connection_id=primary_connection.id,
                tool_id=tool.id,
                platform="nextcloud_talk",
                remote_message_id=f"orion-{suffix}",
                direction="inbound",
                messenger_room_id=room.id,
                messenger_user_id=secondary_identity.id,
                room_id=room.external_id,
                user_id="orion-demo-test",
                text="Message de Orion",
                metadata_={"sender_id": "orion-demo-test"},
            ),
        ]
    )
    await db.flush()

    page = await native_facade.list_chat_messages(
        owner.id,
        room.id,
        agent_id=primary_agent.id,
    )
    projected_room = await native_facade.get_agent_chat_room(
        primary_agent.id,
        room.id,
    )
    author_ids = await native_facade.list_chat_message_agent_ids(
        owner.id,
        room.id,
        agent_id=primary_agent.id,
    )

    assert page is not None
    assert projected_room is not None
    assert {
        member.external_id: member.agent_id
        for member in projected_room.members
    } == {
        "astertest": primary_agent.id,
        "orion-demo-test": secondary_agent.id,
    }
    assert {
        message.text: message.sender.agent_id
        for message in page.items
        if message.sender is not None
    } == {
        "Message de Aster": primary_agent.id,
        "Message de Orion": secondary_agent.id,
    }
    assert author_ids == sorted([primary_agent.id, secondary_agent.id])


@pytest.mark.asyncio
async def test_message_topic_reassignment_can_include_later_messages_of_same_topic(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    sender = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    assert sender is not None
    original_topic = Topic(title="Sujet d'origine", description="", keywords=[])
    other_topic = Topic(title="Autre sujet", description="", keywords=[])
    target_topic = Topic(title="Sujet corrigé", description="", keywords=[])
    db.add_all([original_topic, other_topic, target_topic])
    await db.flush()
    created_at = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)

    def message(index: int, topic: Topic) -> Message:
        return Message(
            connection_id=room.connection_id,
            tool_id=sender.tool_id,
            platform="internal",
            remote_message_id=f"topic-update-{index}-{uuid4()}",
            direction="inbound",
            messenger_room_id=room.id,
            messenger_user_id=sender.id,
            room_id=room.external_id,
            user_id=sender.external_id,
            text=f"Message {index}",
            topic_id=topic.id,
            created_at=created_at + timedelta(minutes=index),
        )

    earlier = message(0, original_topic)
    anchor = message(1, original_topic)
    intervening = message(2, other_topic)
    later_same_topic = message(3, original_topic)
    db.add_all([earlier, anchor, intervening, later_same_topic])
    await db.flush()

    updated = await native_facade.reassign_chat_message_topic(
        room.id,
        anchor.id,
        target_topic.id,
        include_following_same_topic=True,
    )

    assert updated == 2
    await db.rollback()
    persisted = {
        row.id: row.topic_id
        for row in (
            await db.scalars(
                select(Message).where(
                    Message.id.in_(
                        [earlier.id, anchor.id, intervening.id, later_same_topic.id]
                    )
                )
            )
        ).all()
    }
    assert persisted == {
        earlier.id: original_topic.id,
        anchor.id: target_topic.id,
        intervening.id: other_topic.id,
        later_same_topic.id: target_topic.id,
    }


@pytest.mark.asyncio
async def test_room_topic_is_the_dynamic_default_without_overwriting_message_overrides(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    sender = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    assert sender is not None
    first_default = Topic(title="Topic de conversation", description="", keywords=[])
    second_default = Topic(title="Nouveau topic de conversation", description="", keywords=[])
    explicit = Topic(title="Surcharge explicite", description="", keywords=[])
    db.add_all([first_default, second_default, explicit])
    await db.flush()

    updated_room = await native_facade.update_chat_room_topic(
        owner.id,
        room.id,
        topic_id=first_default.id,
    )
    assert updated_room is not None
    assert updated_room.topic_id == first_default.id
    inherited = Message(
        connection_id=room.connection_id,
        tool_id=sender.tool_id,
        platform="internal",
        remote_message_id=f"room-default-{uuid4()}",
        direction="inbound",
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        user_id=sender.external_id,
        text="Message hérité",
    )
    overridden = Message(
        connection_id=room.connection_id,
        tool_id=sender.tool_id,
        platform="internal",
        remote_message_id=f"room-override-{uuid4()}",
        direction="inbound",
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        user_id=sender.external_id,
        text="Message surchargé",
        topic_id=explicit.id,
        topic_overridden=True,
    )
    db.add_all([inherited, overridden])
    await db.commit()

    first_page = await native_facade.list_chat_messages(owner.id, room.id)
    first_topics = {item.id: item.topic_id for item in first_page.items}
    assert first_topics[inherited.id] == first_default.id
    assert first_topics[overridden.id] == explicit.id

    await native_facade.update_chat_room_topic(
        owner.id,
        room.id,
        topic_id=second_default.id,
    )
    second_page = await native_facade.list_chat_messages(owner.id, room.id)
    second_topics = {item.id: item.topic_id for item in second_page.items}
    assert second_topics[inherited.id] == second_default.id
    assert second_topics[overridden.id] == explicit.id
    await db.refresh(inherited)
    assert inherited.topic_id is None
    assert inherited.topic_overridden is False


@pytest.mark.asyncio
async def test_message_topic_reassignment_single_scope_and_missing_anchor(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    sender = await db.scalar(
        select(MessengerUser).where(MessengerUser.galaris_user_id == owner.id)
    )
    assert sender is not None
    original_topic = Topic(title="Sujet simple", description="", keywords=[])
    target_topic = Topic(title="Sujet simple corrigé", description="", keywords=[])
    db.add_all([original_topic, target_topic])
    await db.flush()
    first = Message(
        connection_id=room.connection_id,
        tool_id=sender.tool_id,
        platform="internal",
        remote_message_id=f"topic-single-first-{uuid4()}",
        direction="inbound",
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        user_id=sender.external_id,
        text="Premier message",
        topic_id=original_topic.id,
    )
    second = Message(
        connection_id=room.connection_id,
        tool_id=sender.tool_id,
        platform="internal",
        remote_message_id=f"topic-single-second-{uuid4()}",
        direction="inbound",
        messenger_room_id=room.id,
        messenger_user_id=sender.id,
        room_id=room.external_id,
        user_id=sender.external_id,
        text="Second message",
        topic_id=original_topic.id,
    )
    db.add_all([first, second])
    await db.flush()

    assert await native_facade.reassign_chat_message_topic(
        room.id,
        first.id,
        target_topic.id,
    ) == 1
    assert await native_facade.reassign_chat_message_topic(
        room.id,
        uuid4(),
        target_topic.id,
    ) is None
    await db.refresh(first)
    await db.refresh(second)
    assert first.topic_id == target_topic.id
    assert second.topic_id == original_topic.id


@pytest.mark.asyncio
async def test_room_without_its_unique_agent_is_read_only(
    db: AsyncSession,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(
        actor_user_id=owner.id,
        agent_id=agent.id,
    )
    assert room is not None
    agent_identity = await db.scalar(
        select(MessengerUser).where(MessengerUser.agent_id == agent.id)
    )
    assert agent_identity is not None
    relation = await db.get(
        RoomUser,
        {"room_id": room.id, "user_id": agent_identity.id},
    )
    assert relation is not None
    await db.delete(relation)
    await db.flush()

    unavailable = await get_internal_room(owner.id, room.id)
    assert unavailable is not None
    assert unavailable.agent_active is False


@pytest.mark.asyncio
async def test_message_publish_does_not_lock_room_before_durable_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission session must be able to lock the room without waiting on HTTP."""

    class AdmissionReached(RuntimeError):
        pass

    async def room_membership_without_lock(
        _user_id: int,
        _room_id: object,
        *,
        lock: bool = False,
    ) -> None:
        assert lock is False
        raise AdmissionReached

    monkeypatch.setattr(
        native_facade,
        "room_membership",
        room_membership_without_lock,
    )

    with pytest.raises(AdmissionReached):
        await native_facade.publish_internal_message(
            user_id=1,
            room_id=uuid4(),
            client_message_id=uuid4(),
            text="Salut",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("displayed_document_id", [None, UUID("12345678-1234-4234-8234-123456789abc")])
async def test_message_publish_preserves_an_explicit_topic(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    displayed_document_id: UUID | None,
) -> None:
    from app.messenger.contracts import DocumentFocus

    focus = DocumentFocus.model_validate({
        "revision": 7, "surface": "rendered",
        "cursor": {"offset": 3, "before": "abc", "after": "def"},
    })
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    topic = Topic(title="Sujet forcé", description="", keywords=[])
    db.add(topic)
    await db.flush()

    async def persist_without_admission(
        observation: ObservedMessengerMessage,
        *,
        metadata: dict[str, object] | None = None,
    ) -> bool:
        assert observation.room is not None
        assert observation.room.connection_id is not None
        assert observation.time == 0
        return await journal.persist_inbound(
            observation,
            connection_id=observation.room.connection_id,
            platform="internal",
            metadata=metadata,
        )

    monkeypatch.setattr(inbound, "dispatch_incoming", persist_without_admission)
    published = await native_facade.publish_internal_message(
        user_id=owner.id,
        room_id=room.id,
        client_message_id=uuid4(),
        text="@eff @effort Message classé manuellement",
        topic_id=topic.id,
        reasoning_effort_override="xhigh",
        displayed_document_id=displayed_document_id,
        document_focus=focus,
        language="fr-CA",
    )

    assert published is not None
    assert published.is_mine is True
    assert published.topic_id == topic.id
    assert published.text == "Message classé manuellement"
    stored = await journal.stored_message(
        connection_id=room.connection_id,
        remote_message_id=published.external_id,
        direction="inbound",
    )
    assert stored is not None
    assert stored.text == "@eff @effort Message classé manuellement"
    assert stored.topic_id == topic.id
    assert stored.topic_overridden is True
    assert stored.metadata_[TASK_REQUESTED_METADATA_KEY] is True
    assert stored.metadata_[TASK_REASONING_EFFORT_METADATA_KEY] == "xhigh"
    assert stored.metadata_["language"] == "fr"
    if displayed_document_id is None:
        assert "displayed_document_uri" not in stored.metadata_
        assert "document_focus" not in stored.metadata_
    else:
        assert stored.metadata_["displayed_document_uri"] == f"document://{displayed_document_id}"
        assert stored.metadata_["document_focus"] == focus.model_dump(mode="json")

    outbound = await native_facade.internal_outbound_observation(
        room.connection_id,
        room.external_id,
        "Réponse précise",
    )
    assert outbound.time == 0


@pytest.mark.asyncio
async def test_interrupted_native_message_is_admitted_on_reconciliation(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, owner, _member = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None

    async def persist_without_admission(observation: ObservedMessengerMessage) -> bool:
        assert observation.room is not None
        assert observation.room.connection_id is not None
        return await journal.persist_inbound(
            observation,
            connection_id=observation.room.connection_id,
            platform="internal",
        )

    monkeypatch.setattr(inbound, "dispatch_incoming", persist_without_admission)
    published = await native_facade.publish_internal_message(
        user_id=owner.id,
        room_id=room.id,
        client_message_id=uuid4(),
        text="Message interrupted before admission",
    )
    assert published is not None
    owner.avatar = b"\x89PNG\r\n\x1a\nchat-avatar"
    owner.avatar_mime_type = "image/png"
    owner.avatar_key = uuid4()
    await db.flush()
    page = await native_facade.list_internal_messages(owner.id, room.id)
    assert page is not None
    assert page.items[-1].sender is not None
    assert page.items[-1].sender.avatar_url == owner.avatar_url
    stored = await journal.stored_message(
        connection_id=room.connection_id,
        remote_message_id=published.external_id,
        direction="inbound",
    )
    assert stored is not None
    assert stored.status == "received"
    async with get_db_session():
        assert await get_db().scalar(
            select(ConversationRoundMessage).where(
                ConversationRoundMessage.message_id == stored.id,
            )
        ) is None

    assert await reconcile_internal_admissions() == 1
    stored = await journal.stored_message(
        connection_id=room.connection_id,
        remote_message_id=published.external_id,
        direction="inbound",
    )
    assert stored is not None
    assert stored.status == "admitted"
    async with get_db_session():
        assert await get_db().scalar(
            select(ConversationRoundMessage).where(
                ConversationRoundMessage.message_id == stored.id,
                ConversationRoundMessage.role == "input",
            )
        ) is not None


@pytest.mark.asyncio
async def test_room_list_query_count_does_not_grow_per_room(db):
    from sqlalchemy import event
    from core.database import engine

    agent, owner, _ = await _scope(db)
    for index in range(500):
        await create_internal_room(actor_user_id=owner.id, agent_id=agent.id, label=f"Query budget {index}")
    await db.commit()
    counts = []
    statements = []
    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        for page_size in (10, 50, 500):
            statements.clear()
            page = await native_facade.list_internal_rooms(owner.id, page_size=page_size)
            assert len(page.items) == page_size
            assert all(item.writable for item in page.items)
            counts.append(len(statements))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert max(counts) <= counts[0] + 1
