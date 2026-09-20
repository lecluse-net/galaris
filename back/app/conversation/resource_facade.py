"""Read-only Conversation projections for the Galaris resource namespace."""

from __future__ import annotations

from typing import Any, Literal, cast as typing_cast
from uuid import UUID

from sqlalchemy import String, cast, exists, or_, select

from app.connection import Connection
from app.messenger import Message, Room
from core.database import get_db

from .inspection_service import inspect_round
from .models import ConversationRound, ConversationRoundMessage


ConversationResourceMedium = Literal["text", "voice"]


def _medium_filter(medium: ConversationResourceMedium) -> Any:
    return (
        ConversationRound.voice_session_id.is_not(None)
        if medium == "voice"
        else ConversationRound.voice_session_id.is_(None)
    )


async def read_conversation_round_resource(
    round_id: UUID,
    *,
    actor_agent_id: int,
    medium: ConversationResourceMedium = "text",
) -> dict[str, Any] | None:
    """Return a complete round only through its owning agent's connection."""

    payload = await inspect_round(round_id, actor_agent_id=actor_agent_id)
    if payload is None:
        return None
    round_payload = payload.get("round")
    if not isinstance(round_payload, dict):
        return None
    typed_round_payload = typing_cast(dict[str, Any], round_payload)
    actual_medium: ConversationResourceMedium = (
        "voice"
        if typed_round_payload.get("voice_session_id") is not None
        else "text"
    )
    if actual_medium != medium:
        return None
    payload["medium"] = medium
    payload["resource_uri"] = f"galaris://{medium}/{round_id}"
    return payload


async def list_conversation_round_resources(
    *,
    actor_agent_id: int,
    medium: ConversationResourceMedium = "text",
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return bounded summaries of rounds owned by one agent."""

    statement = (
        select(
            ConversationRound.id,
            ConversationRound.room_id,
            ConversationRound.status,
            ConversationRound.language,
            ConversationRound.attempt_count,
            ConversationRound.created_at,
            ConversationRound.finished_at,
            Room.label.label("room_label"),
            Room.kind.label("room_kind"),
        )
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(
            Connection.agent_id == actor_agent_id,
            _medium_filter(medium),
        )
    )
    normalized_query = query.strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        matching_message = exists(
            select(1)
            .select_from(ConversationRoundMessage)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .where(
                ConversationRoundMessage.round_id == ConversationRound.id,
                Message.text.ilike(pattern),
            )
        )
        statement = statement.where(
            or_(
                Room.label.ilike(pattern),
                ConversationRound.status.ilike(pattern),
                cast(ConversationRound.id, String).ilike(pattern),
                matching_message,
            )
        )
    rows = (
        await get_db().execute(
            statement
            .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
            .offset(max(0, offset))
            # The resource provider requests one look-ahead row after its public page of 500.
            .limit(max(1, min(limit, 501)))
        )
    ).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "room_id": str(row["room_id"]),
            "room_label": str(row["room_label"] or ""),
            "room_kind": str(row["room_kind"] or ""),
            "medium": medium,
            "status": str(row["status"]),
            "language": str(row["language"]),
            "attempt_count": int(row["attempt_count"] or 0),
            "created_at": row["created_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            "resource_uri": f"galaris://{medium}/{row['id']}",
        }
        for row in rows
    ]


__all__ = [
    "ConversationResourceMedium",
    "list_conversation_round_resources",
    "read_conversation_round_resource",
]
