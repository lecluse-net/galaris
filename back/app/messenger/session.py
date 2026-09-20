"""Canonical, bounded conversation-session memory built from the message journal."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.agent.contracts import (
    AgentContextContribution,
    AgentContextRequest,
)
from core.database import get_db
from core.params import runtime_settings

from .models import Attachment, Message, Room
from .resource_reference import attachment_resource_uri


@dataclass(frozen=True)
class ConversationSessionSnapshot:
    """Stable driver-neutral view of one room's recent conversation."""

    scope: str
    connection_id: int
    platform: str
    room_id: str
    cursor: str | None
    messages: tuple[Mapping[str, Any], ...]
    truncated: bool = False


def _fallback_message(
    raw: Mapping[str, Any], *, agent_id: int, current_id: str
) -> dict[str, Any] | None:
    identities = {
        str(value)
        for value in (
            raw.get("external_message_id"),
            raw.get("id"),
            raw.get("message_id"),
            raw.get("messenger_message_id"),
        )
        if value
    }
    message_id = str(
        raw.get("external_message_id")
        or raw.get("id")
        or raw.get("message_id")
        or raw.get("messenger_message_id")
        or ""
    )
    if current_id and current_id in identities:
        return None
    text = str(raw.get("text") or raw.get("message") or "").strip()
    raw_attachments = raw.get("attachments")
    attachments = (
        [
            dict(cast(Mapping[str, Any], item))
            for item in cast(Sequence[Any], raw_attachments)
            if isinstance(item, Mapping)
        ]
        if isinstance(raw_attachments, Sequence)
        and not isinstance(raw_attachments, (str, bytes))
        else []
    )
    tool_code = str(raw.get("tool_code") or "").strip()
    room_id = str(
        raw.get("room_external_id") or raw.get("room_id") or ""
    ).strip()
    for item in attachments:
        local_id = str(item.get("local_id") or item.get("id") or "").strip()
        if local_id and room_id and not item.get("uri"):
            try:
                item["uri"] = attachment_resource_uri(
                    tool_code,
                    room_id,
                    local_id,
                )
            except ValueError:
                pass
    if not text and not attachments:
        return None
    sender_raw = raw.get("sender")
    sender: Mapping[str, Any] = (
        cast(Mapping[str, Any], sender_raw)
        if isinstance(sender_raw, Mapping)
        else cast(Mapping[str, Any], {})
    )
    role = str(raw.get("role") or "")
    is_ai = bool(
        sender.get("agent_id") is not None
        or raw.get("sender_is_ai")
        or raw.get("sender_agent_id") is not None
        or raw.get("is_ai")
        or role == "assistant"
    )
    timestamp = int(raw.get("timestamp") or raw.get("time") or 0)
    sender_external_id = str(
        raw.get("sender_external_id") or sender.get("id") or ""
    )
    sender_display_name = str(
        raw.get("sender_display_name") or sender.get("display_name") or ""
    )
    return {
        "id": message_id,
        "role": "assistant" if is_ai else "user",
        "text": text,
        "platform": str(raw.get("platform") or ""),
        "tool_code": tool_code,
        "room_external_id": room_id,
        "sender": {
            "id": sender_external_id,
            "display_name": sender_display_name,
            "agent_id": (
                agent_id
                if is_ai
                else raw.get("sender_agent_id") or sender.get("agent_id")
            ),
        },
        "time": timestamp,
        "attachments": attachments,
    }


def _record_message(
    row: Message,
    *,
    agent_id: int,
    tool_code: str,
    file_ids: Sequence[UUID] = (),
) -> dict[str, Any]:
    """Serialize one journal row without discarding its canonical identities."""

    metadata = dict(row.metadata_)
    assistant = row.direction == "outbound"
    timestamp = row.created_at
    sender_display_name = (
        str(metadata.get("sender_display_name") or "")
        if not assistant
        else str(metadata.get("sender_display_name") or "Agent")
    )
    attachments: list[dict[str, Any]] = []
    for position, raw in enumerate(row.attachments):
        item = dict(raw)
        if position < len(file_ids):
            file_id = file_ids[position]
            item["external_identifier"] = item.get("id") or None
            item["id"] = str(file_id)
            item["local_id"] = str(file_id)
            if row.messenger_room_id is not None:
                item["uri"] = attachment_resource_uri(
                    tool_code,
                    row.room_id or "",
                    file_id,
                )
        attachments.append(item)
    return {
        # Flat TaskMessage-compatible fields preserve the canonical snapshot when a
        # conversation admits a durable Task.
        "messenger_message_id": str(row.id),
        "external_message_id": row.remote_message_id,
        "id": row.remote_message_id,
        "role": "assistant" if assistant else "user",
        "text": row.conversation_text,
        "platform": row.platform,
        "tool_id": row.tool_id,
        "tool_code": tool_code,
        "sender_external_id": "" if assistant else (row.user_id or ""),
        "sender_display_name": sender_display_name,
        "sender_agent_id": agent_id if assistant else metadata.get("sender_agent_id"),
        "sender_is_ai": assistant or bool(metadata.get("sender_is_ai")),
        "room_id": str(row.messenger_room_id) if row.messenger_room_id else None,
        "room_external_id": row.room_id or "",
        "file_ids": [str(file_id) for file_id in file_ids],
        "reply_to_external_id": row.reply_to,
        "timestamp": int(timestamp.timestamp()),
        "sender": {
            "id": "" if assistant else (row.user_id or ""),
            "display_name": sender_display_name,
            "agent_id": agent_id if assistant else metadata.get("sender_agent_id"),
        },
        "room": {
            "local_id": str(row.messenger_room_id) if row.messenger_room_id else None,
            "id": row.room_id or "",
        },
        "time": int(timestamp.timestamp()),
        "attachments": attachments,
        "reply_to": row.reply_to,
    }


def _bounded_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    preserve_complete_messages: bool = False,
) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    max_messages = runtime_settings.MESSENGER_SESSION_MAX_MESSAGES
    max_chars = runtime_settings.MESSENGER_SESSION_MAX_CHARS
    selected_reversed: list[Mapping[str, Any]] = []
    consumed = 0
    truncated = False
    for message in reversed(messages):
        text = str(message.get("text") or "")
        if len(selected_reversed) >= max_messages:
            truncated = True
            break
        remaining = max_chars - consumed
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            if preserve_complete_messages:
                # Conversation control prefers a soft overflow to silently cutting a
                # historical modification in half. The latest complete message wins.
                if not selected_reversed:
                    selected_reversed.append(message)
                    consumed += len(text)
                truncated = True
                break
            copied = dict(message)
            copied["text"] = text[: max(0, remaining - 1)].rstrip() + "…"
            message = copied
            truncated = True
        selected_reversed.append(message)
        consumed += min(len(text), remaining)
    selected_reversed.reverse()
    return tuple(selected_reversed), truncated or len(selected_reversed) < len(messages)


async def build_conversation_session(
    *,
    connection_id: int,
    agent_id: int,
    platform: str,
    room_id: str,
    current_message_id: str = "",
    excluded_message_ids: Collection[str] = (),
    fallback_history: Sequence[Mapping[str, Any]] = (),
    preserve_complete_messages: bool = False,
    contact_memory_item_id: UUID | None = None,
) -> ConversationSessionSnapshot:
    """Merge task fallback history with authoritative journal rows and bound it."""

    safe_limit = min(max(runtime_settings.MESSENGER_SESSION_MAX_MESSAGES * 3, 50), 500)
    canonical_room_id = None
    external_room_id = room_id
    try:
        parsed_room_id = UUID(room_id)
    except ValueError:
        parsed_room_id = None
    if parsed_room_id is not None:
        room = await get_db().scalar(
            Room.histo_filter(
                select(Room).where(
                    Room.id == parsed_room_id,
                    Room.connection_id == connection_id,
                )
            )
        )
        if room is not None:
            canonical_room_id = room.id
            external_room_id = room.external_id
    if canonical_room_id is None:
        room = await get_db().scalar(
            Room.histo_filter(
                select(Room).where(
                    Room.connection_id == connection_id,
                    Room.external_id == room_id,
                )
            )
        )
        if room is not None:
            canonical_room_id = room.id
            external_room_id = room.external_id
    room_filters = [Message.room_id == external_room_id]
    if canonical_room_id is not None:
        room_filters.append(Message.messenger_room_id == canonical_room_id)
    current = None
    if current_message_id:
        current_identity_filters = [
            Message.remote_message_id == current_message_id
        ]
        try:
            current_canonical_id = UUID(current_message_id)
        except ValueError:
            current_canonical_id = None
        if current_canonical_id is not None:
            current_identity_filters.append(Message.id == current_canonical_id)
        current = await get_db().scalar(
            select(Message)
            .where(
                Message.connection_id == connection_id,
                or_(*room_filters),
                or_(*current_identity_filters),
                Message.direction == "inbound",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
    # Once the canonical contact is known, continuity follows that identity
    # across rooms and connections. The current message is still resolved in
    # the triggering room above, so it remains the temporal cursor.
    history_filters = (
        [Message.contact_memory_item_id == contact_memory_item_id]
        if contact_memory_item_id is not None
        else [Message.connection_id == connection_id, or_(*room_filters)]
    )
    if current is not None:
        # Freeze the session at the triggering inbound message. A Task may start
        # later, after acknowledgements, progress notices, or a newer user turn
        # were journaled; none of those future rows belong to this request.
        history_filters.append(
            or_(
                Message.created_at < current.created_at,
                and_(
                    Message.created_at == current.created_at,
                    Message.id < current.id,
                ),
            )
        )
    result = await get_db().execute(
        select(Message)
        .where(*history_filters)
        .order_by(Message.created_at.desc())
        .limit(safe_limit)
    )
    rows = list(reversed(result.scalars().all()))
    attachment_ids: dict[UUID, list[UUID]] = {}
    if rows:
        links = (
            await get_db().execute(
                select(Attachment)
                .where(Attachment.message_id.in_([row.id for row in rows]))
                .order_by(Attachment.message_id, Attachment.position)
            )
        ).scalars().all()
        for link in links:
            attachment_ids.setdefault(link.message_id, []).append(link.file_id)
    from app.tools import tool_service

    tool_codes: dict[int, str] = {}
    for tool_id in {row.tool_id for row in rows if row.tool_id is not None}:
        tool = await tool_service.get_tool_by_id(int(tool_id))
        if tool is not None:
            tool_codes[int(tool_id)] = str(tool.code)

    excluded_ids = frozenset(
        message_id for message_id in excluded_message_ids if message_id
    )
    if current_message_id:
        excluded_ids = excluded_ids | {current_message_id}
    merged: dict[str, Mapping[str, Any]] = {}
    if not rows and contact_memory_item_id is None:
        anonymous = 0
        for raw in fallback_history:
            normalized = _fallback_message(
                raw, agent_id=agent_id, current_id=current_message_id
            )
            if normalized is None:
                continue
            key = str(normalized.get("id") or "")
            if key and key in excluded_ids:
                continue
            if not key:
                anonymous += 1
                key = f"fallback:{anonymous}"
            else:
                direction = (
                    "outbound"
                    if normalized.get("role") == "assistant"
                    else "inbound"
                )
                key = f"remote:{key}:{direction}"
            merged[key] = normalized
    cursor: str | None = None
    for row in rows:
        cursor = str(row.id)
        if row.remote_message_id in excluded_ids or str(row.id) in excluded_ids:
            continue
        merged[f"remote:{row.remote_message_id}:{row.direction}"] = _record_message(
            row,
            agent_id=agent_id,
            tool_code=tool_codes.get(int(row.tool_id or 0), ""),
            file_ids=attachment_ids.get(row.id, ()),
        )
    ordered = sorted(
        merged.values(),
        key=lambda message: (
            int(message.get("time") or 0),
            str(message.get("id") or ""),
        ),
    )
    bounded, truncated = _bounded_messages(
        ordered,
        preserve_complete_messages=preserve_complete_messages,
    )
    return ConversationSessionSnapshot(
        scope=(
            f"contact:{contact_memory_item_id}"
            if contact_memory_item_id is not None
            else f"messenger:{connection_id}:{room_id}"
        ),
        connection_id=connection_id,
        platform=platform,
        room_id=room_id,
        cursor=cursor,
        messages=bounded,
        truncated=truncated,
    )


async def _resolve_connection_id(request: AgentContextRequest) -> int | None:
    raw: object = request.messenger_connection_id
    if raw is None:
        raw = request.task_data.get("messenger_connection_id")
    if raw is None:
        raw = request.task_data.get("connection_id")
    try:
        connection_id = int(raw) if isinstance(raw, (int, str)) else 0
    except ValueError:
        connection_id = 0
    if connection_id > 0:
        from app.connection import connection_service

        connection = await connection_service.get_connection(connection_id)
        if (
            connection is None
            or int(connection.agent_id) != request.agent.id
        ):
            return None
        return connection_id
    # The upgrade backfills only unambiguous historical Tasks. Inferring at runtime
    # could bind an old room to a replacement account of the same bridge kind.
    return None


async def session_context_provider(
    request: AgentContextRequest,
) -> AgentContextContribution:
    room_id = (request.message_group_id or "").strip()
    if not room_id:
        return AgentContextContribution()
    if not request.include_historical_context:
        return AgentContextContribution(
            messaging_context={
                "platform": request.message_platform or "messenger",
                "room_id": room_id,
            },
            metadata={"session_memory_scope": "standalone_objective"},
        )
    if request.frozen_capsule is not None:
        return AgentContextContribution(
            messaging_context={
                "platform": request.message_platform or "messenger",
                "room_id": room_id,
            }
        )
    connection_id = await _resolve_connection_id(request)
    if connection_id is None:
        return AgentContextContribution()
    current_id = str(
        request.task_data.get("id")
        or request.task_data.get("message_id")
        or ""
    )
    if (
        not current_id
        and request.task_data.get("origin") in {"conversation", "voice_conversation"}
        and request.fallback_history
    ):
        latest = request.fallback_history[-1]
        current_id = str(
            latest.get("external_message_id")
            or latest.get("id")
            or ""
        )
    # A human Messenger task without a proven canonical contact must not inherit
    # room-wide history: group rooms may contain several unrelated people.
    human_messenger = not bool(request.task_data.get("sender_is_ai"))
    if human_messenger and request.contact_memory_item_id is None:
        return AgentContextContribution(
            conversation_history=(),
            metadata={"session_memory_scope": "contact:unresolved"},
        )
    snapshot = await build_conversation_session(
        connection_id=connection_id,
        agent_id=request.agent.id,
        platform=request.message_platform or "messenger",
        room_id=room_id,
        current_message_id=current_id,
        excluded_message_ids=tuple(
            str(item) for item in request.task_data.get("excluded_message_ids", ())
        ),
        fallback_history=request.fallback_history,
        contact_memory_item_id=request.contact_memory_item_id,
    )
    return AgentContextContribution(
        conversation_history=snapshot.messages,
        messaging_context={
            "platform": snapshot.platform,
            "room_id": snapshot.room_id,
            "session_truncated": snapshot.truncated,
            "session_message_count": len(snapshot.messages),
        },
        metadata={
            "session_memory_scope": snapshot.scope,
            "session_memory_cursor": snapshot.cursor,
            "session_memory_truncated": snapshot.truncated,
        },
    )


__all__ = [
    "ConversationSessionSnapshot",
    "build_conversation_session",
    "session_context_provider",
]
