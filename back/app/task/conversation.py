"""Public conversation chronology consumed by background task observers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db

from .models import Task


@dataclass(frozen=True, slots=True)
class ConversationFollowup:
    """The immediate Task following another Task in one logical conversation."""

    task_id: UUID
    objective: str
    created_at: datetime
    sender_is_ai: bool = False


@dataclass(frozen=True, slots=True)
class ConversationPredecessor:
    """The previous root Task and opaque scope of one logical conversation."""

    task_id: UUID
    created_at: datetime
    scope_hash: str


@dataclass(frozen=True, slots=True)
class ConversationScope:
    """Opaque stable identity safe to expose across domain boundaries."""

    kind: str
    channel: str
    scope_hash: str


def _api_conversation_id(task: Task) -> str | None:
    data = task.data if isinstance(task.data, dict) else {}
    value = str(data.get("conversation_id") or "").strip()
    return value or None


def _scope_parts(
    task: Task,
) -> tuple[dict[str, object], ColumnElement[bool]] | None:
    if task.agent_id is None or task.parent_id is not None:
        return None
    platform = str(task.message_platform or "").strip()
    platform_filter = (
        Task.message_platform.is_(None)
        if task.message_platform is None
        else Task.message_platform == task.message_platform
    )
    room_id = str(task.message_group_id or "").strip()
    if room_id:
        connection_filter = (
            Task.messenger_connection_id.is_(None)
            if task.messenger_connection_id is None
            else Task.messenger_connection_id == task.messenger_connection_id
        )
        return (
            {
                "kind": "messenger",
                "agent_id": task.agent_id,
                "connection_id": task.messenger_connection_id,
                "platform": platform,
                "room_id": room_id,
            },
            and_(
                platform_filter,
                connection_filter,
                Task.message_group_id == room_id,
            ),
        )
    conversation_id = _api_conversation_id(task)
    if conversation_id is None:
        return None
    return (
        {
            "kind": "api",
            "agent_id": task.agent_id,
            "platform": platform,
            "conversation_id": conversation_id,
        },
        and_(
            platform_filter,
            Task.message_group_id.is_(None),
            Task.data["conversation_id"].as_string() == conversation_id,
        ),
    )


def get_conversation_scope(task: Task) -> ConversationScope | None:
    """Return a hash, never the connection, room, or external conversation id."""

    parts = _scope_parts(task)
    if parts is None:
        return None
    scope_data, _scope_filter = parts
    serialized_scope = json.dumps(
        scope_data,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ConversationScope(
        kind=str(scope_data["kind"]),
        channel=str(scope_data.get("platform") or scope_data["kind"]),
        scope_hash=hashlib.sha256(
            serialized_scope.encode("utf-8")
        ).hexdigest(),
    )


async def get_conversation_followup(task: Task) -> ConversationFollowup | None:
    """Return the immediate chronological successor in the same conversation.

    Messaging conversations use the exact server-owned connection and room. API
    conversations without a room use their persisted ``conversation_id``. Tasks
    without either stable scope deliberately have no conversational successor.
    """

    if task.agent_id is None:
        return None

    platform_filter = (
        Task.message_platform.is_(None)
        if task.message_platform is None
        else Task.message_platform == task.message_platform
    )
    room_id = str(task.message_group_id or "").strip()
    if room_id:
        connection_filter = (
            Task.messenger_connection_id.is_(None)
            if task.messenger_connection_id is None
            else Task.messenger_connection_id == task.messenger_connection_id
        )
        scope_filter = and_(
            connection_filter,
            Task.message_group_id == room_id,
        )
    else:
        conversation_id = _api_conversation_id(task)
        if conversation_id is None:
            return None
        scope_filter = and_(
            Task.message_group_id.is_(None),
            Task.data["conversation_id"].as_string() == conversation_id,
        )

    next_task = await get_db().scalar(
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.agent_id == task.agent_id,
            platform_filter,
            scope_filter,
            or_(
                Task.created_at > task.created_at,
                and_(Task.created_at == task.created_at, Task.id > task.id),
            ),
        )
        .order_by(Task.created_at, Task.id)
        .limit(1)
    )
    if next_task is None:
        return None
    return ConversationFollowup(
        task_id=next_task.id,
        objective=str(next_task.objective or "").strip(),
        created_at=next_task.created_at,
        sender_is_ai=bool(
            next_task.ai
            or (
                isinstance(next_task.data, dict)
                and next_task.data.get("sender_is_ai")
            )
        ),
    )


async def get_conversation_predecessor(
    task: Task,
) -> ConversationPredecessor | None:
    """Return the previous root Task in the same stable conversation scope."""

    parts = _scope_parts(task)
    scope = get_conversation_scope(task)
    if parts is None or scope is None or task.agent_id is None:
        return None
    _scope_data, scope_filter = parts

    previous = await get_db().scalar(
        select(Task)
        .where(
            Task.deleted_at.is_(None),
            Task.agent_id == task.agent_id,
            Task.parent_id.is_(None),
            scope_filter,
            or_(
                Task.created_at < task.created_at,
                and_(Task.created_at == task.created_at, Task.id < task.id),
            ),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(1)
    )
    if previous is None:
        return None
    return ConversationPredecessor(
        task_id=previous.id,
        created_at=previous.created_at,
        scope_hash=scope.scope_hash,
    )


__all__ = [
    "ConversationFollowup",
    "ConversationPredecessor",
    "ConversationScope",
    "get_conversation_followup",
    "get_conversation_predecessor",
    "get_conversation_scope",
]
