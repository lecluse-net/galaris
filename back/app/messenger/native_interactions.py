"""Scoped projections and human commands for choices in the internal Chat."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import String, cast, select

from app.connection import Connection
from core.database import get_db
from core.i18n import render_prompt, t

from .contracts import NativeInteractionOption, NativeMessengerInteraction
from .events import message_journaled
from .interactions import ChoiceOption, resolve_pending_choice
from .models import Interaction, Message, MessengerUser, Room


def _snapshot(record: Interaction, *, participant: str | None) -> NativeMessengerInteraction:
    status = record.status
    if status == "PENDING" and record.expires_at <= datetime.now(timezone.utc):
        status = "EXPIRED"
    selected = (record.resolution or {}).get("option_id")
    return NativeMessengerInteraction(
        id=record.id,
        reference=record.reference,
        title=record.title,
        body=record.body,
        options=[NativeInteractionOption.model_validate(option) for option in record.options],
        free_text=record.free_text,
        status=status,
        expires_at=record.expires_at,
        selected_option_id=selected if isinstance(selected, str) else None,
        can_answer=(
            status == "PENDING"
            and participant is not None
            and record.user_id in {None, participant}
        ),
    )


async def message_interactions(
    messages: list[Message],
    *,
    viewer_user_id: int | None,
) -> dict[UUID, NativeMessengerInteraction]:
    """Load choices for a visible page in one query; external transports stay textual."""

    ids = [message.id for message in messages if message.platform == "internal"]
    if not ids:
        return {}
    rows = await get_db().execute(
        select(Message.id, Interaction)
        .join(Interaction, Interaction.prompt_message_id == cast(Message.id, String))
        .join(Connection, Connection.id == Message.connection_id)
        .where(
            Message.id.in_(ids),
            Message.direction == "outbound",
            Interaction.connection_id == Message.connection_id,
            Interaction.tool_id == Message.tool_id,
            Interaction.room_id == cast(Message.messenger_room_id, String),
            Interaction.agent_id == Connection.agent_id,
        )
    )
    participant = f"user:{viewer_user_id}" if viewer_user_id is not None else None
    return {message_id: _snapshot(record, participant=participant) for message_id, record in rows}


async def _scoped_interaction(
    user_id: int,
    room_id: UUID,
    interaction_id: UUID,
    *,
    require_active: bool,
) -> tuple[Interaction, Connection, Room, MessengerUser]:
    from .native_facade import get_internal_room, room_membership

    membership = await room_membership(user_id, room_id)
    if membership is None:
        raise LookupError("Interaction not found.")
    room, _membership, human, connection = membership
    if require_active:
        visible_room = await get_internal_room(user_id, room_id)
        if not connection.active or visible_room is None or not visible_room.agent_active:
            raise PermissionError("The room agent is unavailable.")
    record = await get_db().scalar(
        select(Interaction).where(
            Interaction.id == interaction_id,
            Interaction.connection_id == connection.id,
            Interaction.tool_id == connection.tool_id,
            Interaction.agent_id == connection.agent_id,
            Interaction.room_id == str(room.id),
        )
    )
    if record is None or record.user_id not in {None, human.external_id}:
        raise LookupError("Interaction not found.")
    return record, connection, room, human


async def read_internal_interaction(
    user_id: int,
    room_id: UUID,
    interaction_id: UUID,
) -> NativeMessengerInteraction:
    record, _connection, _room, human = await _scoped_interaction(
        user_id,
        room_id,
        interaction_id,
        require_active=False,
    )
    return _snapshot(record, participant=human.external_id)


async def answer_internal_interaction(
    user_id: int,
    room_id: UUID,
    interaction_id: UUID,
    *,
    option_id: str,
) -> NativeMessengerInteraction:
    """Resolve an exact persisted option without admitting a conversation or a Task."""

    record, connection, room, human = await _scoped_interaction(
        user_id,
        room_id,
        interaction_id,
        require_active=True,
    )
    options = [ChoiceOption.model_validate(option) for option in record.options]
    option = next((option for option in options if option.id == option_id), None)
    if option is None:
        raise ValueError("Unknown interaction option.")
    from .contact_memory import observe_contact

    # Contact continuity uses the same human identity as typed replies. Resolve it
    # before locking the interaction: Memory may commit its own projection.
    contact_id = await observe_contact(
        owner_agent_id=connection.agent_id,
        messaging_id="internal",
        user_id=human.external_id,
        display_name=human.display_name,
        galaris_user_id=user_id,
    )
    captured: Message | None = None

    async def capture_response() -> None:
        nonlocal captured
        # The resolver holds the interaction lock and calls this only for its first
        # valid capture. Keep the answer and decision atomic, including handler failure.
        prompt_external_id = await get_db().scalar(
            select(Message.remote_message_id).where(
                cast(Message.id, String) == record.prompt_message_id,
                Message.connection_id == connection.id,
                Message.messenger_room_id == room.id,
                Message.direction == "outbound",
            )
        )
        captured = Message(
            id=uuid4(),
            connection_id=connection.id,
            tool_id=connection.tool_id,
            platform="internal",
            remote_message_id=f"interaction:{record.id}:answer",
            direction="inbound",
            messenger_room_id=room.id,
            messenger_user_id=human.id,
            sender_messenger_user_id=human.id,
            requester_user_id=user_id,
            room_id=room.external_id,
            user_id=human.external_id,
            contact_memory_item_id=contact_id,
            text=render_prompt(
                t("messenger_interactions.answer"),
                title=record.title,
                reference=record.reference,
                answer=option.label,
            ),
            reply_to=prompt_external_id,
            status="admitted",
            created_at=datetime.now(timezone.utc),
            metadata_={
                "sender_id": human.external_id,
                "sender_display_name": human.display_name,
                "sender_is_ai": False,
                "interaction_reference": record.reference,
                "selected_option_id": option.id,
            },
        )
        get_db().add(captured)
        await get_db().flush()

    await resolve_pending_choice(
        reference=record.reference,
        option_id=option.id,
        response_text=option.label,
        agent_id=connection.agent_id,
        connection_id=connection.id,
        tool_id=connection.tool_id,
        room_id=str(room_id),
        user_id=human.external_id,
        capture_response=capture_response,
    )
    if captured is not None:
        await message_journaled.send_async(captured)
    await get_db().refresh(record)
    return _snapshot(record, participant=human.external_id)
