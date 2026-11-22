"""Scoped projections and human commands for choices in the internal Chat."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Select, String, and_, cast, func, or_, select, tuple_

from app.connection import Connection
from app.services import ServiceModel as Service
from core.database import get_db
from core.i18n import current_language, is_supported, render_prompt, t

from .contracts import NativeInteractionAnswer, NativeInteractionOption, NativeMessengerInteraction
from .events import message_journaled
from .facade import enabled_specs
from .interactions import ChoiceOption, choice_authorized, choice_body_html, choice_is_authorization, resolve_pending_choice
from .models import Interaction, Message, MessengerUser, Room, RoomUser


async def _can_answer(record: Interaction, user_id: int | None) -> bool:
    return await choice_authorized(record.kind, user_id)


def _pending_questions() -> Select[tuple[UUID, UUID, str, datetime]]:
    return (
        select(RoomUser.room_id, RoomUser.user_id, Interaction.kind, Interaction.expires_at)
        .select_from(RoomUser)
        .join(Room, Room.id == RoomUser.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .join(Interaction, Interaction.connection_id == Connection.id)
        .join(Message, Message.messenger_room_id == Room.id)
        .where(
            Connection.active.is_(True),
            Room.deleted_at.is_(None),
            MessengerUser.is_ai.is_(False),
            MessengerUser.deleted_at.is_(None),
            MessengerUser.service_id == Connection.service_id,
            Interaction.agent_id == Connection.agent_id,
            Interaction.service_id == Connection.service_id,
            or_(Interaction.room_id == cast(Room.id, String), Interaction.room_id == Room.external_id),
            or_(Interaction.user_id.is_(None), Interaction.user_id == MessengerUser.external_id),
            Interaction.status == "PENDING",
            Interaction.expires_at > datetime.now(timezone.utc),
            Message.connection_id == Connection.id,
            Message.platform.in_([spec.kind for spec in enabled_specs()]),
            Message.direction == "outbound",
            Message.deleted_at.is_(None),
            cast(Message.id, String) == Interaction.prompt_message_id,
        )
    )


async def pending_room_question_deadlines(
    memberships: Sequence[tuple[UUID, UUID]],
    *,
    viewer_user_id: int,
) -> dict[tuple[UUID, UUID], datetime]:
    """Find published questions the viewer can answer in each room."""
    if not memberships:
        return {}
    rows = (await get_db().execute(
        _pending_questions().with_only_columns(
            RoomUser.room_id, RoomUser.user_id, Interaction.kind, func.max(Interaction.expires_at),
        ).where(tuple_(RoomUser.room_id, RoomUser.user_id).in_(memberships))
        .group_by(RoomUser.room_id, RoomUser.user_id, Interaction.kind)
    )).all()
    kinds = {kind for _, _, kind, _ in rows}
    answerable_kinds = {kind for kind in kinds if await choice_authorized(kind, viewer_user_id)}
    deadlines: dict[tuple[UUID, UUID], datetime] = {}
    for room_id, user_id, kind, deadline in rows:
        if kind not in answerable_kinds:
            continue
        key = (room_id, user_id)
        previous = deadlines.get(key)
        if previous is None or deadline > previous:
            deadlines[key] = deadline
    return deadlines


async def chat_pending_question_summary(user_id: int) -> tuple[int, datetime | None]:
    """Count questions the viewer can answer across Chat rooms and find the next expiry."""
    from .native_facade import CHAT_TOOL_CODE, MAIL_TOOL_CODE, human_external_id

    rows = await get_db().execute(
        _pending_questions().with_only_columns(
            Interaction.kind, func.count(func.distinct(Interaction.id)), func.min(Interaction.expires_at),
        ).join(Service, Service.id == Connection.service_id).where(
            Room.conversation_type == "text",
            Service.code != MAIL_TOOL_CODE,
            or_(
                MessengerUser.galaris_user_id == user_id,
                and_(Service.code == CHAT_TOOL_CODE, MessengerUser.external_id == human_external_id(user_id)),
            ),
        ).group_by(Interaction.kind)
    )
    questions = [(count, expiry) for kind, count, expiry in rows if await choice_authorized(kind, user_id)]
    return sum(count for count, _ in questions), min((expiry for _, expiry in questions), default=None)


def _snapshot(record: Interaction, *, participant: str | None, authorized: bool) -> NativeMessengerInteraction:
    status = record.status
    if status == "PENDING" and record.expires_at <= datetime.now(timezone.utc):
        status = "EXPIRED"
    selected = (record.resolution or {}).get("option_id")
    recipient_authorized = authorized and participant is not None and record.user_id in {None, participant}
    return NativeMessengerInteraction(
        id=record.id,
        reference=record.reference,
        title=record.title,
        body=record.body,
        body_html=choice_body_html(record) if recipient_authorized else None,
        options=[NativeInteractionOption.model_validate(option) for option in record.options],
        free_text=record.free_text,
        status=status,
        expires_at=record.expires_at,
        selected_option_id=selected if isinstance(selected, str) else None,
        can_answer=recipient_authorized and status == "PENDING",
        is_authorization=choice_is_authorization(record.kind),
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
            Interaction.service_id == Message.service_id,
            Interaction.room_id == cast(Message.messenger_room_id, String),
            Interaction.agent_id == Connection.agent_id,
        )
    )
    participant = f"user:{viewer_user_id}" if viewer_user_id is not None else None
    return {message_id: _snapshot(record, participant=participant, authorized=await _can_answer(record, viewer_user_id)) for message_id, record in rows}


async def message_interaction_answers(
    messages: list[Message],
) -> dict[UUID, NativeInteractionAnswer]:
    """Project display variables in one scoped query, including previously recorded answers."""

    answers = {
        message.id: message for message in messages
        if message.platform == "internal"
        and message.direction == "inbound"
        and isinstance(message.metadata_.get("interaction_reference"), str)
        and isinstance(message.metadata_.get("selected_option_id"), str)
    }
    if not answers:
        return {}
    rows = await get_db().execute(
        select(Message.id, Interaction)
        .join(Interaction, Interaction.reference == Message.metadata_["interaction_reference"].as_string())
        .join(Connection, Connection.id == Message.connection_id)
        .where(
            Message.id.in_(answers),
            Interaction.connection_id == Message.connection_id,
            Interaction.service_id == Message.service_id,
            Interaction.room_id == cast(Message.messenger_room_id, String),
            Interaction.agent_id == Connection.agent_id,
        )
    )
    result: dict[UUID, NativeInteractionAnswer] = {}
    for message_id, record in rows:
        selected = answers[message_id].metadata_["selected_option_id"]
        option = next((option for option in record.options if option.get("id") == selected), None)
        if option is not None and isinstance(option.get("label"), str):
            result[message_id] = NativeInteractionAnswer(
                title=record.title, reference=record.reference, answer=option["label"],
            )
    return result


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
            Interaction.service_id == connection.service_id,
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
    return _snapshot(record, participant=human.external_id, authorized=await _can_answer(record, user_id))


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
    if not await _can_answer(record, user_id):
        raise PermissionError("Permission decision access is required.")
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
    stored_language = str((record.metadata_ or {}).get("language") or "")
    language = stored_language if is_supported(stored_language) else await current_language(user_id=user_id)

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
            service_id=connection.service_id,
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
                t("messenger_interactions.answer", language),
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
        service_id=connection.service_id,
        room_id=str(room_id),
        user_id=human.external_id,
        capture_response=capture_response,
    )
    if captured is not None:
        await message_journaled.send_async(captured)
    await get_db().refresh(record)
    return _snapshot(record, participant=human.external_id, authorized=await _can_answer(record, user_id))
