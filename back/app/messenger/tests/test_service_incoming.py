"""Anchor incoming peer replies below the asker's blocking wait subtask, not at root."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.memory import MessengerContactObservation
from app.messenger import service
from app.messenger.interface import BridgeSpec
from app.messenger.models import (
    Message,
    Room,
    MessengerUser,
)

_ROOM_ID = UUID("00000000-0000-0000-0000-000000000101")
_SENDER_ID = UUID("00000000-0000-0000-0000-000000000102")
_RECIPIENT_ID = UUID("00000000-0000-0000-0000-000000000103")


@pytest_asyncio.fixture(autouse=True)
async def contact_policy(db):
    """Exercise the real policy while the existing workflow ports stay isolated."""
    from core.team.models import Team, TeamUser
    from core.user import UserModel
    from app.agent.models import Agent, Title
    from app.agent import AgentTeamModel as AgentTeam

    human = UserModel(id=8432, email="contact@example.com", hashed_password="unused", is_active=True)
    team = Team(name="Conversation participants")
    title = Title(label="Mx", gender="M")
    db.add_all([human, team, title])
    await db.flush()
    db.add_all([Agent(id=aid, code=f"incoming-{aid}", first_name="Peer", last_name=str(aid), title_id=title.id)
                for aid in (1, 42, 1519)])
    await db.flush()
    db.add(TeamUser(team_id=team.id, user_id=human.id))
    db.add_all([AgentTeam(team_id=team.id, agent_id=aid) for aid in (1, 42, 1519)])
    await db.flush()


def _wire_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_id: int,
    kind: str = "nextcloud_talk",
) -> tuple[AsyncMock, AsyncMock]:
    """Patch ``_process_incoming`` surroundings and return task/contact calls."""
    from app.tools import tool_service
    from app.connection import connection_service
    from app.agent import agent_service
    from app.messenger import contact_memory, interactions, directory, facade, ingest
    from app import conversation
    from app.task import task_service, runner, collab

    tool = SimpleNamespace(
        code="mail" if kind == "mail" else "custom-nextcloud",
        messenger=SimpleNamespace(service=kind),
    )
    connection = SimpleNamespace(id=7, tool_id=3, agent_id=agent_id, active=True)

    monkeypatch.setattr(tool_service, "get_tool_by_id", AsyncMock(return_value=tool))
    monkeypatch.setattr(connection_service, "get_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        connection_service, "get_connections_by_param", AsyncMock(return_value=[connection])
    )
    monkeypatch.setattr(agent_service, "get", AsyncMock(return_value=SimpleNamespace(id=agent_id)))
    monkeypatch.setattr(interactions, "resolve_from_message", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ingest,
        "transcribe_audio_for_conversation",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(directory, "enrich_ai_identity", AsyncMock())
    monkeypatch.setattr(facade, "get_messenger", AsyncMock(side_effect=RuntimeError("no history")))
    monkeypatch.setattr(collab, "open_exchange_await", AsyncMock(return_value=None))
    monkeypatch.setattr(collab, "timed_out_await_for_late_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(runner, "go_next", lambda *a, **k: None)
    monkeypatch.setattr(service, "_lock_inbound_message", AsyncMock())
    monkeypatch.setattr(
        conversation,
        "admit_messenger_input",
        AsyncMock(return_value=True),
    )

    created_task = SimpleNamespace(id=uuid4())
    created = AsyncMock(return_value=(created_task, True))
    monkeypatch.setattr(task_service, "create_from_messenger", created)
    contact_observer = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        contact_memory,
        "observe_messenger_contact",
        contact_observer,
    )
    return created, contact_observer


def _incoming(sender_agent_id: Optional[int]) -> Message:
    message = Message(
        id=uuid4(),
        connection_id=7,
        tool_id=3,
        platform="nextcloud_talk",
        remote_message_id="m1",
        direction="inbound",
        text="How is your day going?",
        created_at=datetime.fromtimestamp(1, tz=timezone.utc),
    )
    message.sender = MessengerUser(
        id=_SENDER_ID,
        tool_id=3,
        external_id="astertest",
        display_name="Aster",
        agent_id=sender_agent_id,
        galaris_user_id=8432 if sender_agent_id is None else None,
        is_ai=sender_agent_id is not None,
    )
    message.recipient = MessengerUser(
        id=_RECIPIENT_ID,
        tool_id=3,
        external_id="orion-demo-test",
        is_ai=True,
    )
    message.room = Room(
        id=_ROOM_ID,
        connection_id=7,
        external_id="kvq7mo8y",
        label="kvq7mo8y",
        kind="group",
        conversation_type="text",
    )
    return message


@pytest.mark.parametrize(
    "platform",
    ["nextcloud_talk", "matrix", "one_bot", "telegram", "whatsapp", "internal"],
)
def test_every_instant_bridge_blocks_messages_older_than_one_hour(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    from app.messenger import facade

    now = datetime.now(timezone.utc)
    message = _incoming(sender_agent_id=None)
    message.platform = platform
    message.created_at = now - timedelta(hours=1, seconds=1)
    monkeypatch.setattr(facade, "get_spec", lambda kind: BridgeSpec(kind=kind))

    assert service.is_stale_instant_message(message, now=now) is True


def test_one_hour_boundary_is_not_stale_and_mail_remains_asynchronous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import facade

    now = datetime.now(timezone.utc)
    message = _incoming(sender_agent_id=None)
    message.created_at = now - timedelta(hours=1)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda kind: BridgeSpec(
            kind=kind,
            inbound_admission="task" if kind == "mail" else "conversation",
        ),
    )

    assert service.is_stale_instant_message(message, now=now) is False
    message.platform = "mail"
    message.created_at = now - timedelta(days=30)
    assert service.is_stale_instant_message(message, now=now) is False


@pytest.mark.asyncio
async def test_incoming_peer_reply_is_anchored_under_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, contact_observer = _wire_common(
        monkeypatch, agent_id=1519
    )  # Orion receives the message.
    await_id = uuid4()
    monkeypatch.setattr(
        collab, "awaited_for_incoming", AsyncMock(return_value=SimpleNamespace(id=await_id))
    )

    await service._process_incoming(_incoming(sender_agent_id=1))  # Message from an AI requester.

    created.assert_awaited_once()
    task_create = created.await_args.args[0]
    assert task_create.messenger_connection_id == 7
    assert task_create.data["messenger_connection_id"] == 7
    assert task_create.message_platform == "nextcloud_talk"
    assert task_create.parent_id == await_id       # Nested below S instead of detached.
    assert task_create.source_task_id == await_id
    assert task_create.data[collab.RESOLVES_KEY] == str(await_id)
    collab.awaited_for_incoming.assert_awaited_once_with(
        sender_agent_id=1,
        connection_id=7,
        platform="nextcloud_talk",
        room_id=str(_ROOM_ID),
        recipient_user_id=str(_RECIPIENT_ID),
    )
    contact_observer.assert_not_awaited()


@pytest.mark.asyncio
async def test_incoming_without_await_stays_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.task import collab

    created, _contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))

    await service._process_incoming(_incoming(sender_agent_id=1))

    created.assert_awaited_once()
    task_create = created.await_args.args[0]
    assert task_create.parent_id is None           # An ordinary message remains at root.
    assert task_create.source_task_id is None
    assert collab.RESOLVES_KEY not in (task_create.data or {})


@pytest.mark.asyncio
async def test_direct_messenger_task_inherits_the_room_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, _contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))
    topic_id = uuid4()
    message = _incoming(sender_agent_id=1)
    assert message.room is not None
    message.room.topic_id = topic_id

    await service._process_incoming(message)

    task_create = created.await_args.args[0]
    assert task_create.topic_id == topic_id


@pytest.mark.asyncio
async def test_incoming_platform_cannot_override_connection_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))
    message = _incoming(sender_agent_id=1)
    message.platform = "telegram"

    await service._process_incoming(message)

    created.assert_awaited_once()
    task_create = created.await_args.args[0]
    assert task_create.message_platform == "nextcloud_talk"
    assert message.platform == "nextcloud_talk"
    contact_observer.assert_not_awaited()


@pytest.mark.asyncio
async def test_incoming_peer_reply_during_open_exchange_is_created_for_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, _contact_observer = _wire_common(
        monkeypatch, agent_id=1
    )  # Aster receives the message.
    await_id = uuid4()
    parent_id = uuid4()
    monkeypatch.setattr(
        collab,
        "open_exchange_await",
        AsyncMock(return_value=SimpleNamespace(id=await_id, parent_id=parent_id)),
    )
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))

    await service._process_incoming(_incoming(sender_agent_id=1519))

    created.assert_awaited_once()
    task_create = created.await_args.args[0]
    assert task_create.parent_id == parent_id
    assert task_create.source_task_id == await_id
    assert task_create.data[collab.OPEN_EXCHANGE_KEY] == str(await_id)
    assert collab.RESOLVES_KEY not in (task_create.data or {})


@pytest.mark.asyncio
async def test_human_sender_is_projected_with_server_owned_bridge_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(
        collab, "awaited_for_incoming", AsyncMock(return_value=None)
    )
    message = _incoming(sender_agent_id=None)
    message.platform = "telegram"

    await service._process_incoming(message)

    created.assert_not_awaited()
    from app import conversation

    conversation.admit_messenger_input.assert_awaited_once_with(
        message,
        agent_id=1519,
        connection_id=7,
    )
    from app.messenger import ingest

    ingest.transcribe_audio_for_conversation.assert_awaited_once_with(
        message,
        agent_id=1519,
    )
    contact_observer.assert_awaited_once_with(
        MessengerContactObservation(
            owner_agent_id=1519,
            messaging_id="nextcloud_talk",
            user_id="astertest",
            display_name="Aster",
            galaris_user_id=8432,
        )
    )
    observation = contact_observer.await_args.args[0]
    assert message.platform == "nextcloud_talk"


@pytest.mark.asyncio
async def test_audio_transcription_failure_does_not_block_conversation_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import conversation
    from app.messenger import ingest
    from app.task import collab

    created, _contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))
    ingest.transcribe_audio_for_conversation.side_effect = RuntimeError("STT offline")
    message = _incoming(sender_agent_id=None)

    await service._process_incoming(message)

    created.assert_not_awaited()
    conversation.admit_messenger_input.assert_awaited_once_with(
        message,
        agent_id=1519,
        connection_id=7,
    )


@pytest.mark.asyncio
async def test_mail_sender_is_admitted_directly_as_task_without_automatic_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import conversation
    from app.task import collab

    created, contact_observer = _wire_common(
        monkeypatch,
        agent_id=1519,
        kind="mail",
    )
    monkeypatch.setattr(collab, "awaited_for_incoming", AsyncMock(return_value=None))
    message = _incoming(sender_agent_id=None)
    message.platform = "mail"
    assert message.sender is not None
    message.sender.external_id = "astertest@example.com"
    message.text = "Read this email with mail_get using reference m1_ref."

    await service._process_incoming(message)

    created.assert_awaited_once()
    task_create = created.await_args.args[0]
    assert task_create.objective == "<p>Read this email with mail_get using reference m1_ref.</p>"
    assert task_create.messenger_connection_id is None
    assert task_create.message_platform is None
    assert task_create.message_group_id is None
    assert task_create.data["messenger_connection_id"] == 7
    conversation.admit_messenger_input.assert_not_awaited()
    contact_observer.assert_awaited_once()


@pytest.mark.asyncio
async def test_interaction_reply_is_projected_before_it_is_consumed(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import Connection
    from app.messenger import interactions
    from app.tools import ToolModel

    resolve_from_message = interactions.resolve_from_message
    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(interactions, "resolve_from_message", resolve_from_message)
    if await db.get(ToolModel, 3) is None:
        db.add(ToolModel(id=3, code="incoming-choice-test", label="Choice test", description="", connection_schema={}))
        await db.flush()
    db.add(Connection(id=7, tool_id=3, agent_id=1519, active=True))
    await db.flush()
    handler = AsyncMock()
    monkeypatch.setitem(interactions._choice_handlers, "incoming-choice-test", handler)
    await interactions.create_choice(
        SimpleNamespace(
            connection_id=7,
            tool_id=3,
            send_to_room=AsyncMock(return_value=SimpleNamespace(id="approval-prompt")),
        ),
        agent_id=1519,
        room_id=str(_ROOM_ID),
        user_id="astertest",
        request=interactions.ChoiceRequest(
            kind="incoming-choice-test",
            title="Autorisation",
            options=[interactions.ChoiceOption(id="create", label="Créer")],
            language="fr",
        ),
    )

    message = _incoming(sender_agent_id=None)
    message.text = "1"
    await service._process_incoming(message)

    contact_observer.assert_awaited_once()
    handler.assert_awaited_once()
    assert handler.await_args.args[1].option_id == "create"
    created.assert_not_awaited()
    from app import conversation

    conversation.admit_messenger_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_failure_does_not_prevent_conversation_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.task import collab

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    contact_observer.side_effect = RuntimeError("memory unavailable")
    monkeypatch.setattr(
        collab, "awaited_for_incoming", AsyncMock(return_value=None)
    )

    await service._process_incoming(_incoming(sender_agent_id=None))

    contact_observer.assert_awaited_once()
    created.assert_not_awaited()
    from app import conversation

    conversation.admit_messenger_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_incoming_handler_propagates_admission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admit = AsyncMock(side_effect=RuntimeError("This transaction is closed"))
    monkeypatch.setattr(service, "admit_incoming", admit)
    message = _incoming(sender_agent_id=None)

    with pytest.raises(RuntimeError, match="transaction is closed"):
        await service.handle_incoming(message)

    admit.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_memory_failure_does_not_prevent_interaction_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import interactions

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    contact_observer.side_effect = RuntimeError("memory unavailable")
    interaction_resolver = AsyncMock(
        return_value=SimpleNamespace(
            interaction_id=uuid4(),
            kind="choice",
        )
    )
    monkeypatch.setattr(
        interactions,
        "resolve_from_message",
        interaction_resolver,
    )

    await service._process_incoming(_incoming(sender_agent_id=None))

    contact_observer.assert_awaited_once()
    interaction_resolver.assert_awaited_once()
    created.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender",
    [None, MessengerUser(id=uuid4(), tool_id=3, external_id="")],
)
async def test_absent_or_empty_sender_is_not_projected(
    monkeypatch: pytest.MonkeyPatch,
    sender: MessengerUser | None,
) -> None:
    from app.task import collab

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    monkeypatch.setattr(
        collab, "awaited_for_incoming", AsyncMock(return_value=None)
    )
    message = _incoming(sender_agent_id=None)
    message.sender = sender

    await service._process_incoming(message)

    contact_observer.assert_not_awaited()
    created.assert_not_awaited()
    from app import conversation

    conversation.admit_messenger_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_sender_enriched_as_ai_is_not_projected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import interactions

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)

    monkeypatch.setattr(
        interactions,
        "resolve_from_message",
        AsyncMock(
            return_value=SimpleNamespace(
                interaction_id=uuid4(),
                kind="choice",
            )
        ),
    )

    await service._process_incoming(_incoming(sender_agent_id=42))

    contact_observer.assert_not_awaited()
    created.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_or_unmapped_sender_is_never_admitted(db, monkeypatch):
    from sqlalchemy import delete
    from app.agent import AgentTeamModel as AgentTeam
    from app import conversation

    created, contact_observer = _wire_common(monkeypatch, agent_id=1519)
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == 1519))
    for peer in (None, 1):
        await service._process_incoming(_incoming(sender_agent_id=peer))
    unmapped = _incoming(sender_agent_id=None)
    unmapped.sender.galaris_user_id = None
    await service._process_incoming(unmapped)
    contact_observer.assert_not_awaited()
    created.assert_not_awaited()
    conversation.admit_messenger_input.assert_not_awaited()
