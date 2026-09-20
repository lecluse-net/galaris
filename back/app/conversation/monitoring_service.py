"""Read-only room/message projections for conversation execution monitoring."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import case, func, or_, select, true
from sqlalchemy.orm import aliased

from app.agent import Agent
from app.agent.contracts import TaskMessage
from app.connection import Connection
from app.messenger import Message, MessengerUser, Room, hydrate_messages
from core.database import get_db

from .models import ConversationRound, ConversationRoundMessage, ConversationTaskLink, ConversationProcessLink
from .schemas import (
    ConversationMessagePage,
    ConversationMessageRead,
    ConversationRoundDetail,
    ConversationStatusOverview,
    ConversationUnknownNotification,
)


def _runtime_status(round_status: Any):
    return case(
        (round_status == "FROZEN", "READY"),
        (round_status.in_(("CLAIMED", "RUNNING")), "RUNNING"),
        else_="IDLE",
    )


def _payload(
    message: Message,
    *,
    sender_external_id: str | None,
    sender_display_name: str | None,
    sender_agent_id: int | None,
    sender_is_ai: bool | None,
) -> dict[str, object]:
    metadata = message.metadata_
    return {
        "id": message.remote_message_id,
        "local_id": str(message.id),
        "platform": message.platform,
        "sender": {
            "local_id": str(message.messenger_user_id or ""),
            "id": str(sender_external_id or metadata.get("sender_id") or ""),
            "display_name": str(
                sender_display_name or metadata.get("sender_display_name") or ""
            ),
            "agent_id": sender_agent_id,
            "is_ai": bool(sender_is_ai),
        },
        "text": message.text,
        "reply_to": message.reply_to,
        "time": int(message.created_at.timestamp()),
    }


async def list_messages(
    *,
    page: int,
    page_size: int,
    agent_id: int | None = None,
    status: str | None = None,
    channel_kind: str | None = None,
    topic_id: UUID | None = None,
    search: str | None = None,
    errors_only: bool = False,
    active: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    agent_ids: Collection[int] | None = None,
) -> ConversationMessagePage:
    """Return one row per canonical inbound message admitted to Conversation."""

    matched = (
        select(
            ConversationRound.id.label("round_id"),
            ConversationRound.status.label("round_status"),
            ConversationRound.language.label("language"),
            ConversationRound.topic_id.label("topic_id"),
            case(
                (ConversationRound.status.in_(("SUCCEEDED", "COMPLETED")), None),
                else_=ConversationRound.last_error,
            ).label("response_error"),
            ConversationRound.finished_at.label("responded_at"),
            ConversationRound.created_at.label("round_created_at"),
            ConversationRoundMessage.sequence.label("input_sequence"),
        )
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.round_id == ConversationRound.id,
        )
        .where(
            ConversationRoundMessage.message_id == Message.id,
            ConversationRoundMessage.role == "input",
        )
        .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
        .limit(1)
        .lateral("matched_conversation_round")
    )
    current = (
        select(ConversationRound.status.label("round_status"))
        .where(
            ConversationRound.room_id == Room.id,
            ConversationRound.voice_session_id.is_(None),
        )
        .order_by(
            case(
                (ConversationRound.status.in_(("CLAIMED", "RUNNING")), 0),
                (ConversationRound.status == "FROZEN", 1),
                else_=2,
            ),
            ConversationRound.created_at.desc(),
            ConversationRound.id.desc(),
        )
        .limit(1)
        .lateral("current_conversation_round")
    )
    outbound = aliased(Message)
    output_text = (
        select(outbound.text)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == outbound.id,
        )
        .where(
            ConversationRoundMessage.round_id == matched.c.round_id,
            ConversationRoundMessage.role == "output",
        )
        .order_by(
            ConversationRoundMessage.response_sequence.desc(),
            ConversationRoundMessage.sequence.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    aggregated_count = (
        select(func.count(ConversationRoundMessage.message_id))
        .where(
            ConversationRoundMessage.round_id == matched.c.round_id,
            ConversationRoundMessage.role == "input",
        )
        .scalar_subquery()
    )
    runtime_status = _runtime_status(current.c.round_status)
    summary_filters: list[Any] = [Message.direction == "inbound"]
    if agent_id is not None:
        summary_filters.append(Connection.agent_id == agent_id)
    if agent_ids is not None:
        summary_filters.append(Connection.agent_id.in_(agent_ids))
    if channel_kind:
        summary_filters.append(Message.platform == channel_kind)
    if topic_id is not None:
        summary_filters.append(
            func.coalesce(matched.c.topic_id, Message.topic_id) == topic_id
        )
    if date_from is not None:
        summary_filters.append(
            Message.created_at
            >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        summary_filters.append(
            Message.created_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        summary_filters.append(
            or_(
                Message.text.ilike(pattern),
                MessengerUser.external_id.ilike(pattern),
                MessengerUser.display_name.ilike(pattern),
                Message.platform.ilike(pattern),
                Room.label.ilike(pattern),
                Room.external_id.ilike(pattern),
                Agent.first_name.ilike(pattern),
                Agent.last_name.ilike(pattern),
                Agent.code.ilike(pattern),
            )
        )
    filters = list(summary_filters)
    if status:
        filters.append(runtime_status == status)
    if active is not None:
        is_running = runtime_status == "RUNNING"
        filters.append(is_running if active else ~is_running)
    if errors_only:
        filters.append(matched.c.round_status == "ERROR_RESOLVED")

    base = (
        select(Message)
        .select_from(Message)
        .join(matched, true())
        .join(Room, Room.id == Message.messenger_room_id)
        .join(current, true())
        .join(Connection, Connection.id == Room.connection_id)
        .join(Agent, Agent.id == Connection.agent_id)
        .outerjoin(MessengerUser, MessengerUser.id == Message.messenger_user_id)
        .where(*filters)
    )
    total = int(
        await get_db().scalar(
            select(func.count()).select_from(base.order_by(None).subquery())
        )
        or 0
    )
    idle, ready, running, errors = (
        await get_db().execute(
            select(
                func.count(func.distinct(Message.messenger_room_id)).filter(
                    runtime_status == "IDLE"
                ),
                func.count(func.distinct(Message.messenger_room_id)).filter(
                    runtime_status == "READY"
                ),
                func.count(func.distinct(Message.messenger_room_id)).filter(
                    runtime_status == "RUNNING"
                ),
                func.count(func.distinct(Message.messenger_room_id)).filter(
                    matched.c.round_status == "ERROR_RESOLVED"
                ),
            )
            .select_from(Message)
            .join(matched, true())
            .join(Room, Room.id == Message.messenger_room_id)
            .join(current, true())
            .join(Connection, Connection.id == Room.connection_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .outerjoin(MessengerUser, MessengerUser.id == Message.messenger_user_id)
            .where(*summary_filters)
        )
    ).one()
    rows = (
        await get_db().execute(
            select(
                Message,
                Room,
                Agent.id,
                Agent.first_name,
                Agent.last_name,
                Agent.code,
                MessengerUser.external_id,
                MessengerUser.display_name,
                MessengerUser.agent_id,
                MessengerUser.is_ai,
                matched.c.round_id,
                matched.c.round_status,
                matched.c.language,
                func.coalesce(matched.c.topic_id, Message.topic_id),
                output_text,
                matched.c.response_error,
                matched.c.responded_at,
                matched.c.input_sequence,
                aggregated_count,
            )
            .select_from(Message)
            .join(matched, true())
            .join(Room, Room.id == Message.messenger_room_id)
            .join(current, true())
            .join(Connection, Connection.id == Room.connection_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .outerjoin(MessengerUser, MessengerUser.id == Message.messenger_user_id)
            .where(*filters)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ConversationMessagePage(
        items=[
            ConversationMessageRead(
                id=message.id,
                room_id=room.id,
                sequence=int(sequence),
                agent_id=int(row_agent_id),
                agent_name=f"{first_name or ''} {last_name or ''}".strip() or None,
                agent_code=agent_code,
                channel_kind=message.platform,
                connection_id=room.connection_id,
                participant_key=str(message.messenger_user_id or ""),
                language=str(language),
                topic_id=topic_id,
                payload=_payload(
                    message,
                    sender_external_id=sender_external_id,
                    sender_display_name=sender_display_name,
                    sender_agent_id=sender_agent_id,
                    sender_is_ai=sender_is_ai,
                ),
                created_at=message.created_at,
                round_id=round_id,
                round_status=round_status,
                response_text=response_text,
                response_error=response_error,
                responded_at=responded_at,
                aggregated_message_count=int(message_count or 0),
            )
            for (
                message,
                room,
                row_agent_id,
                first_name,
                last_name,
                agent_code,
                sender_external_id,
                sender_display_name,
                sender_agent_id,
                sender_is_ai,
                round_id,
                round_status,
                language,
                topic_id,
                response_text,
                response_error,
                responded_at,
                sequence,
                message_count,
            ) in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        summary=ConversationStatusOverview(
            idle=int(idle),
            ready=int(ready),
            running=int(running),
            errors=int(errors),
        ),
    )


async def get_round(round_id: UUID) -> ConversationRoundDetail | None:
    row = (
        await get_db().execute(
            select(
                ConversationRound,
                Room,
                Connection,
                Agent.first_name,
                Agent.last_name,
            )
            .join(Room, Room.id == ConversationRound.room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .where(ConversationRound.id == round_id)
        )
    ).one_or_none()
    if row is None:
        return None
    round_, room, connection, first_name, last_name = row
    messages = await hydrate_messages(
        list(
            (
                await get_db().scalars(
                    select(Message)
                    .join(
                        ConversationRoundMessage,
                        ConversationRoundMessage.message_id == Message.id,
                    )
                    .where(
                        ConversationRoundMessage.round_id == round_.id,
                        ConversationRoundMessage.role == "input",
                    )
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )
    )
    rendered = [
        cast(dict[str, object], TaskMessage.from_messenger(message).model_dump(mode="json"))
        for message in messages
    ]
    output = aliased(Message)
    response_text = await get_db().scalar(
        select(output.text)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == output.id,
        )
        .where(
            ConversationRoundMessage.round_id == round_.id,
            ConversationRoundMessage.role == "output",
        )
        .order_by(ConversationRoundMessage.sequence.desc())
        .limit(1)
    )
    newest = messages[-1] if messages else None
    notifications: list[ConversationUnknownNotification] = []
    task_links = list((await get_db().scalars(select(ConversationTaskLink).where(
        ConversationTaskLink.round_id == round_id,
    ).order_by(ConversationTaskLink.created_at, ConversationTaskLink.id))).all())
    notifications.extend(ConversationUnknownNotification(
        kind="task", link_id=link.id, target_id=link.task_id,
        attempt_number=link.notification_attempt_count, error=link.notification_error,
    ) for link in task_links if link.notification_state == "UNKNOWN")
    from app.task import task_startup_timings

    timings = await task_startup_timings([link.task_id for link in task_links], agent_id=connection.agent_id)
    process_links = await get_db().scalars(select(ConversationProcessLink).where(
        ConversationProcessLink.round_id == round_id, ConversationProcessLink.notification_state == "UNKNOWN",
    ).order_by(ConversationProcessLink.created_at, ConversationProcessLink.id))
    notifications.extend(ConversationUnknownNotification(
        kind="process", link_id=link.id, target_id=link.process_run_id,
        attempt_number=link.notification_attempt_count, error=link.notification_error,
    ) for link in process_links)
    return ConversationRoundDetail(
        id=round_.id,
        task_startup_timings=timings,
        topic_id=round_.topic_id,
        agent_id=connection.agent_id,
        agent_name=f"{first_name or ''} {last_name or ''}".strip() or None,
        channel_kind=newest.platform if newest is not None else "messenger",
        connection_id=room.connection_id,
        room_id=room.id,
        participant_key=str(newest.user_id or "") if newest is not None else "",
        language=round_.language,
        status=round_.status,
        rendered_input=rendered,
        response_text=response_text,
        execution_result=round_.execution_result,
        delivery_state=round_.delivery_state,
        effect_started=round_.effect_started,
        attempt_count=round_.attempt_count,
        last_error=None if round_.status in {"SUCCEEDED", "COMPLETED"} else round_.last_error,
        created_at=cast(datetime, round_.created_at),
        finished_at=round_.finished_at,
        unknown_notifications=notifications,
    )


__all__ = ["get_round", "list_messages"]
