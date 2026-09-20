"""Canonical persistence facade for Galaris' Chat application.

Chat owns product policy and internal binary storage. This module keeps every ORM
read/write in the Messenger domain and returns stable DTOs to that application.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import and_, case, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_db, get_db_session
from core.i18n import normalize_language
from core.user import UserModel as User

from app.agent import Agent
from app.connection import Connection
from app.tools import ToolModel as Tool

from . import journal
from ._observations import (
    ObservedMessengerFile,
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from .contracts import (
    ChatViewerAgent,
    NativeMessengerAgent,
    NativeMessengerConnection,
    NativeMessengerFile,
    NativeMessengerFileAccess,
    NativeMessengerIdentityMapping,
    NativeMessengerMember,
    NativeMessengerMessage,
    NativeMessengerInteraction,
    NativeMessengerMessagePage,
    NativeMessengerRoom,
    NativeMessengerRoomPage,
    resolve_effective_topic_id,
)
from .interface import HistoryPage
from .models import (
    CONVERSATION_OUTPUT_PENDING_METADATA_KEY,
    TASK_REQUESTED_METADATA_KEY,
    DISPLAYED_DOCUMENT_METADATA_KEY,
    TASK_REASONING_EFFORT_METADATA_KEY,
    Attachment,
    Capability,
    File,
    Message,
    MessengerUser,
    Room,
    RoomUser,
)
from .resource_reference import attachment_resource_uri
from .user_service import enrich_messenger_users, resolve_messenger_user
from .native_interactions import message_interactions
from .facade import get_messenger, get_spec, is_kind_enabled, kind_for_tool
from .ingest import fetch_bytes


CHAT_TOOL_CODE = "chat"
INTERNAL_PLATFORM = "internal"
MAIL_TOOL_CODE = "mail"
_nextcloud_history_sync_locks: dict[UUID, asyncio.Lock] = {}
_VISIBLE_TASK_CONTROL_DIRECTIVE_RE = re.compile(
    r"(?<!\w)@(?:task|eff(?:ort)?)\b(?:[ \t]+)?",
    re.IGNORECASE,
)


def human_external_id(user_id: int) -> str:
    return f"user:{user_id}"


def agent_external_id(agent_id: int) -> str:
    return f"agent:{agent_id}"


def _visible_message_text(value: str) -> str:
    """Hide persisted Task controls only when projecting a message to Chat."""

    return _VISIBLE_TASK_CONTROL_DIRECTIVE_RE.sub("", value).strip()


async def _internal_tool() -> Tool | None:
    return await get_db().scalar(select(Tool).where(Tool.code == CHAT_TOOL_CODE))


async def internal_connection(connection_id: int) -> NativeMessengerConnection | None:
    row = (
        await get_db().execute(
            select(Connection, Tool, Agent)
            .join(Tool, Tool.id == Connection.tool_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .where(
                Connection.id == connection_id,
                Tool.code == CHAT_TOOL_CODE,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    connection, tool, agent = row
    name = " ".join(
        part for part in (agent.first_name, agent.last_name) if part
    ).strip() or agent.code
    return NativeMessengerConnection(
        connection_id=connection.id,
        tool_id=tool.id,
        tool_code=tool.code,
        agent_id=agent.id,
        agent_code=agent.code,
        agent_name=name,
        active=bool(connection.active),
    )


async def search_internal_users(
    connection_id: int,
    query: str,
) -> list[ObservedMessengerUser]:
    """Return active humans who already share an internal Chat room with the agent."""

    filters = [
        Room.connection_id == connection_id,
        Room.kind == "direct",
        MessengerUser.is_ai.is_(False),
        MessengerUser.galaris_user_id.is_not(None),
        User.is_active.is_(True),
    ]
    value = query.strip()[:200]
    if value:
        pattern = f"%{value}%"
        filters.append(
            or_(
                MessengerUser.display_name.ilike(pattern),
                MessengerUser.external_id.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    users = list(
        (
            await get_db().scalars(
                select(MessengerUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .join(Room, Room.id == RoomUser.room_id)
                .join(User, User.id == MessengerUser.galaris_user_id)
                .where(*filters)
                .distinct()
                .order_by(MessengerUser.display_name, MessengerUser.external_id)
            )
        ).all()
    )
    return [
        ObservedMessengerUser(
            id=user.external_id,
            display_name=user.display_name,
            is_ai=False,
            connection_id=connection_id,
            tool_id=user.tool_id,
        )
        for user in users
    ]


async def internal_direct_room_observation(
    connection_id: int,
    user_external_id: str,
) -> ObservedMessengerRoom | None:
    """Resolve the most recently active direct Chat room for one human."""

    room = await get_db().scalar(
        select(Room)
        .join(RoomUser, RoomUser.room_id == Room.id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .join(User, User.id == MessengerUser.galaris_user_id)
        .where(
            Room.connection_id == connection_id,
            Room.kind == "direct",
            MessengerUser.external_id == user_external_id,
            MessengerUser.is_ai.is_(False),
            User.is_active.is_(True),
        )
        .order_by(
            func.coalesce(Room.updated_at, Room.created_at).desc(),
            Room.id.desc(),
        )
        .limit(1)
    )
    if room is None:
        return None
    return ObservedMessengerRoom(
        id=room.external_id,
        local_id=room.id,
        label=room.label,
        kind="direct",
        conversation_type=cast(Literal["audio", "text"], room.conversation_type),
        connection_id=connection_id,
    )


async def list_internal_agents(
    *,
    agent_ids: Collection[int] | None = None,
) -> list[NativeMessengerAgent]:
    query = (
        select(Connection, Agent)
            .join(Tool, Tool.id == Connection.tool_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .where(Tool.code == CHAT_TOOL_CODE)
            .order_by(Agent.first_name, Agent.last_name, Agent.id)
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    rows = (await get_db().execute(query)).all()
    return [
        NativeMessengerAgent(
            agent_id=agent.id,
            connection_id=connection.id,
            code=agent.code,
            display_name=(
                " ".join(
                    part for part in (agent.first_name, agent.last_name) if part
                ).strip()
                or agent.code
            ),
            active=bool(connection.active),
        )
        for connection, agent in rows
    ]


def _tool_source(tool: Tool) -> str:
    config = tool.messenger_config or {}
    return str(config.get("service") or tool.code).strip().lower()


async def list_chat_identity_mappings(user_id: int) -> list[NativeMessengerIdentityMapping]:
    """List the current user's external identity for each messaging Tool."""

    rows = (
        await get_db().execute(
            select(Tool, MessengerUser)
            .outerjoin(
                MessengerUser,
                and_(
                    MessengerUser.tool_id == Tool.id,
                    MessengerUser.galaris_user_id == user_id,
                ),
            )
            .where(
                Tool.messenger_config.is_not(None),
                Tool.code != CHAT_TOOL_CODE,
            )
            .order_by(Tool.label, Tool.id)
        )
    ).all()
    return [
        NativeMessengerIdentityMapping(
            tool_id=tool.id,
            tool_code=tool.code,
            tool_label=tool.label,
            source=_tool_source(tool),
            external_id=identity.external_id if identity is not None else None,
            display_name=identity.display_name if identity is not None else None,
        )
        for tool, identity in rows
    ]


async def list_chat_viewer_agents(
    *,
    agent_ids: Collection[int] | None = None,
) -> list[ChatViewerAgent]:
    query = (
        select(Agent)
            .join(MessengerUser, MessengerUser.agent_id == Agent.id)
            .join(RoomUser, RoomUser.user_id == MessengerUser.id)
            .distinct()
            .order_by(Agent.first_name, Agent.last_name, Agent.id)
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    rows = (await get_db().execute(query)).scalars().all()
    return [
        ChatViewerAgent(
            agent_id=agent.id,
            code=agent.code,
            display_name=(
                " ".join(
                    part for part in (agent.first_name, agent.last_name) if part
                ).strip()
                or agent.code
            ),
        )
        for agent in rows
    ]


async def set_chat_identity_mapping(
    user_id: int,
    tool_id: int,
    external_id: str,
) -> NativeMessengerIdentityMapping | None:
    """Link one exact remote identity to the authenticated Galaris user."""

    normalized = external_id[:512].strip()
    if not normalized:
        raise ValueError("An external Messenger identity is required.")
    tool = await get_db().get(Tool, tool_id)
    if (
        tool is None
        or tool.code == CHAT_TOOL_CODE
        or tool.messenger_config is None
    ):
        return None
    target = await get_db().scalar(
        select(MessengerUser)
        .where(
            MessengerUser.tool_id == tool_id,
            MessengerUser.external_id == normalized,
        )
        .with_for_update()
    )
    if target is not None and target.galaris_user_id not in {None, user_id}:
        raise PermissionError("This external identity is already linked to another user.")
    await get_db().execute(
        update(MessengerUser)
        .where(
            MessengerUser.tool_id == tool_id,
            MessengerUser.galaris_user_id == user_id,
            MessengerUser.external_id != normalized,
        )
        .values(galaris_user_id=None)
    )
    if target is None:
        identity_id = await resolve_messenger_user(
            tool_id=tool_id,
            external_id=normalized,
            display_name=normalized,
            galaris_user_id=user_id,
        )
        target = await get_db().get(MessengerUser, identity_id)
    elif target.galaris_user_id != user_id:
        target.galaris_user_id = user_id
    await get_db().commit()
    if target is None:
        return None
    return NativeMessengerIdentityMapping(
        tool_id=tool.id,
        tool_code=tool.code,
        tool_label=tool.label,
        source=_tool_source(tool),
        external_id=target.external_id,
        display_name=target.display_name,
    )


async def clear_chat_identity_mapping(user_id: int, tool_id: int) -> bool:
    cleared_id = await get_db().scalar(
        update(MessengerUser)
        .where(
            MessengerUser.tool_id == tool_id,
            MessengerUser.galaris_user_id == user_id,
        )
        .values(galaris_user_id=None)
        .returning(MessengerUser.id)
    )
    await get_db().commit()
    return cleared_id is not None


async def internal_agent_avatar(agent_id: int) -> bytes | None:
    """Return the avatar of an agent displayed by the unified Chat application."""

    return await get_db().scalar(
        select(Agent.avatar).where(Agent.id == agent_id)
    )


async def _ensure_human(tool_id: int, user: User) -> UUID:
    return await resolve_messenger_user(
        tool_id=tool_id,
        external_id=human_external_id(user.id),
        display_name=user.display_name or user.email,
        galaris_user_id=user.id,
        is_ai=False,
    )


async def _ensure_agent(tool_id: int, agent: Agent) -> UUID:
    display_name = " ".join(
        part for part in (agent.first_name, agent.last_name) if part
    ).strip() or agent.code
    return await resolve_messenger_user(
        tool_id=tool_id,
        external_id=agent_external_id(agent.id),
        display_name=display_name,
        agent_id=agent.id,
        is_ai=True,
    )


def _next_internal_room_label(
    base_label: str,
    existing_labels: Collection[str],
) -> str:
    normalized_base = base_label.strip()[:500]
    if normalized_base not in existing_labels:
        return normalized_base
    suffix_number = 2
    while True:
        suffix = f" ({suffix_number})"
        candidate = f"{normalized_base[: 500 - len(suffix)].rstrip()}{suffix}"
        if candidate not in existing_labels:
            return candidate
        suffix_number += 1


async def _human_identity(user_id: int) -> tuple[Tool, MessengerUser] | None:
    tool = await _internal_tool()
    if tool is None:
        return None
    user = await get_db().scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        return None
    identity_id = await _ensure_human(tool.id, user)
    identity = await get_db().get(MessengerUser, identity_id)
    return (tool, identity) if identity is not None else None


async def create_internal_room(
    *,
    actor_user_id: int,
    agent_id: int,
    label: str | None = None,
    topic_id: UUID | None = None,
    show_last_message: bool = True,
) -> NativeMessengerRoom | None:
    identity = await _human_identity(actor_user_id)
    if identity is None:
        return None
    tool, _actor = identity
    row = (
        await get_db().execute(
            select(Connection, Agent)
            .join(Agent, Agent.id == Connection.agent_id)
            .where(
                Connection.tool_id == tool.id,
                Connection.agent_id == agent_id,
                Connection.active.is_(True),
            )
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        return None
    connection, agent = row
    agent_label = (
        " ".join(
            part for part in (agent.first_name, agent.last_name) if part
        ).strip()
        or agent.code
    )
    existing_labels = set(
        (
            await get_db().scalars(
                select(Room.label)
                .join(RoomUser, RoomUser.room_id == Room.id)
                .where(
                    Room.connection_id == connection.id,
                    Room.kind == "direct",
                    Room.conversation_type == "text",
                    RoomUser.user_id == _actor.id,
                    RoomUser.role == "owner",
                )
            )
        ).all()
    )
    normalized_label = label.strip()[:500] if label is not None else ""
    room_id = uuid4()
    room = Room(
        id=room_id,
        connection_id=connection.id,
        external_id=f"chat:direct:{agent_id}:{actor_user_id}:{room_id}",
        label=(
            normalized_label
            or _next_internal_room_label(agent_label, existing_labels)
        ),
        kind="direct",
        conversation_type="text",
        topic_id=topic_id,
    )
    get_db().add(room)
    await get_db().flush()
    agent_identity_id = await _ensure_agent(tool.id, agent)
    await _upsert_membership(room.id, agent_identity_id, role="member")
    await _upsert_membership(room.id, _actor.id, role="owner")
    await get_db().execute(
        update(RoomUser)
        .where(
            RoomUser.room_id == room.id,
            RoomUser.user_id == _actor.id,
        )
        .values(show_last_message=show_last_message)
    )
    await get_db().commit()
    return await get_internal_room(actor_user_id, room.id)


async def _upsert_membership(room_id: UUID, user_id: UUID, *, role: str) -> None:
    await get_db().execute(
        pg_insert(RoomUser)
        .values(room_id=room_id, user_id=user_id, role=role)
        .on_conflict_do_update(
            index_elements=[RoomUser.room_id, RoomUser.user_id],
            set_={"role": role},
        )
    )


async def room_membership(
    user_id: int,
    room_id: UUID,
    *,
    lock: bool = False,
) -> tuple[Room, RoomUser, MessengerUser, Connection] | None:
    statement = (
        select(Room, RoomUser, MessengerUser, Connection)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Tool, Tool.id == Connection.tool_id)
        .join(RoomUser, RoomUser.room_id == Room.id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(
            Room.id == room_id,
            Room.kind == "direct",
            Tool.code == CHAT_TOOL_CODE,
            MessengerUser.external_id == human_external_id(user_id),
            RoomUser.role == "owner",
        )
    )
    if lock:
        statement = statement.with_for_update(of=RoomUser)
    row = (await get_db().execute(statement)).one_or_none()
    return cast(tuple[Room, RoomUser, MessengerUser, Connection] | None, row)


async def has_room_access(user_id: int, room_id: UUID) -> bool:
    return await room_membership(user_id, room_id) is not None


async def chat_room_membership(
    user_id: int,
    room_id: UUID,
    *,
    lock: bool = False,
) -> tuple[Room, RoomUser, MessengerUser, Connection, Tool] | None:
    statement = (
        select(Room, RoomUser, MessengerUser, Connection, Tool)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Tool, Tool.id == Connection.tool_id)
        .join(RoomUser, RoomUser.room_id == Room.id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(
            Room.id == room_id,
            Room.conversation_type == "text",
            or_(
                MessengerUser.galaris_user_id == user_id,
                and_(
                    Tool.code == CHAT_TOOL_CODE,
                    MessengerUser.external_id == human_external_id(user_id),
                ),
            ),
        )
    )
    if lock:
        statement = statement.with_for_update(of=RoomUser)
    row = (await get_db().execute(statement)).one_or_none()
    return cast(
        tuple[Room, RoomUser, MessengerUser, Connection, Tool] | None,
        row,
    )


async def has_chat_room_access(user_id: int, room_id: UUID) -> bool:
    """Authorize Chat only through a linked canonical Messenger identity."""

    return await chat_room_membership(user_id, room_id) is not None


async def has_agent_chat_room_access(agent_id: int, room_id: UUID) -> bool:
    return (
        await get_db().scalar(
            select(RoomUser.room_id)
            .join(Room, Room.id == RoomUser.room_id)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(
                RoomUser.room_id == room_id,
                Room.conversation_type == "text",
                MessengerUser.agent_id == agent_id,
                MessengerUser.is_ai.is_(True),
            )
        )
        is not None
    )


async def has_ai_chat_room_access(room_id: UUID) -> bool:
    return (
        await get_db().scalar(
            select(RoomUser.room_id)
            .join(Room, Room.id == RoomUser.room_id)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(
                RoomUser.room_id == room_id,
                Room.conversation_type == "text",
                MessengerUser.agent_id.is_not(None),
                MessengerUser.is_ai.is_(True),
            )
        )
        is not None
    )


async def _room_has_expected_agent(room_id: UUID, agent_id: int) -> bool:
    ai_agent_ids = list(
        (
            await get_db().scalars(
                select(MessengerUser.agent_id)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == room_id, MessengerUser.is_ai.is_(True))
            )
        ).all()
    )
    return ai_agent_ids == [agent_id]


async def _member_dto(user: MessengerUser, membership: RoomUser) -> NativeMessengerMember:
    return NativeMessengerMember(
        id=user.id,
        external_id=user.external_id,
        display_name=user.display_name or user.external_id,
        avatar_url=None,
        is_ai=user.is_ai,
        agent_id=user.agent_id,
        role=membership.role,
        joined_at=membership.joined_at,
        muted=membership.muted,
    )


def _user_avatar_url(user: User | None) -> str | None:
    return user.avatar_url if user is not None else None


async def _message_dto(
    message: Message,
    *,
    human_avatar_url: str | None = None,
    human_external_id: str | None = None,
    viewer_galaris_user_id: int | None = None,
    viewer_agent_id: int | None = None,
    memberships: dict[tuple[UUID, UUID], RoomUser] | None = None,
    interaction: NativeMessengerInteraction | None = None,
) -> NativeMessengerMessage:
    if message.messenger_room_id is None:
        raise ValueError("A native Messenger message must belong to a canonical room.")
    sender = message.sender
    sender_dto = None
    if sender is not None:
        membership = (
            memberships.get((message.messenger_room_id, sender.id))
            if memberships is not None else await get_db().get(
                RoomUser,
                {"room_id": message.messenger_room_id, "user_id": sender.id},
            )
        )
        sender_dto = NativeMessengerMember(
            id=sender.id,
            external_id=sender.external_id,
            display_name=sender.display_name or sender.external_id,
            avatar_url=(
                human_avatar_url
                if not sender.is_ai and sender.external_id == human_external_id
                else None
            ),
            is_ai=sender.is_ai,
            agent_id=sender.agent_id,
            role=membership.role if membership is not None else "member",
            joined_at=membership.joined_at if membership is not None else None,
            muted=membership.muted if membership is not None else False,
        )
    is_mine = bool(
        sender is not None
        and (
            (
                viewer_agent_id is not None
                and sender.is_ai
                and sender.agent_id == viewer_agent_id
            )
            or (
                viewer_galaris_user_id is not None
                and not sender.is_ai
                and (
                    sender.galaris_user_id == viewer_galaris_user_id
                    or sender.external_id == human_external_id
                )
            )
        )
    )
    files = [
        NativeMessengerFile(
            id=file.id,
            uri=attachment_resource_uri(
                message.tool_code or message.platform,
                message.room.external_id if message.room is not None else str(message.messenger_room_id),
                file.id,
            ),
            name=file.name,
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            kind=file.kind,
        )
        for file in message.files
    ]
    effective_topic_id = resolve_effective_topic_id(
        message.topic_id,
        topic_overridden=message.topic_overridden,
        room_topic_id=message.room.topic_id if message.room is not None else None,
    )
    return NativeMessengerMessage(
        id=message.id,
        external_id=message.remote_message_id,
        room_id=message.messenger_room_id,
        direction=message.direction,
        text=_visible_message_text(message.text),
        topic_id=effective_topic_id,
        topic_overridden=message.topic_overridden,
        sender=sender_dto,
        reply_to=message.reply_to,
        files=files,
        status=message.status,
        created_at=message.created_at,
        is_mine=is_mine,
        interaction=interaction,
    )


@dataclass
class _RoomListProjection:
    last_messages: dict[UUID, NativeMessengerMessage] = field(default_factory=dict[UUID, NativeMessengerMessage])
    unread: dict[tuple[UUID, UUID], int] = field(default_factory=dict[tuple[UUID, UUID], int])
    expected_agents: dict[UUID, int | None] = field(default_factory=dict[UUID, int | None])


async def _room_list_projection(room_ids: list[UUID]) -> _RoomListProjection:
    """Load page projections in batches, independent of the number of rooms."""
    projection = _RoomListProjection()
    if not room_ids:
        return projection
    db = get_db()
    ranked = select(
        Message.id,
        func.row_number().over(
            partition_by=Message.messenger_room_id,
            order_by=(Message.created_at.desc(), Message.id.desc()),
        ).label("position"),
    ).where(Message.messenger_room_id.in_(room_ids)).subquery()
    records = list(await db.scalars(
        select(Message).where(Message.id.in_(select(ranked.c.id).where(ranked.c.position == 1)))
    ))
    messages = await journal.hydrate_messages(records)
    sender_keys = [(message.messenger_room_id, message.sender.id) for message in messages if message.sender is not None]
    sender_memberships: list[RoomUser] = list(await db.scalars(
        select(RoomUser).where(tuple_(RoomUser.room_id, RoomUser.user_id).in_(sender_keys))
    )) if sender_keys else []
    memberships = {
        (membership.room_id, membership.user_id): membership
        for membership in sender_memberships
    }
    for message in messages:
        if message.messenger_room_id is not None:
            projection.last_messages[message.messenger_room_id] = await _message_dto(message, memberships=memberships)
    unread_rows = await db.execute(
        select(RoomUser.room_id, RoomUser.user_id, func.count(Message.id))
        .join(Message, Message.messenger_room_id == RoomUser.room_id)
        .where(
            RoomUser.room_id.in_(room_ids), Message.counts_as_unread.is_(True),
            Message.journal_position > func.coalesce(RoomUser.read_through_position, 0),
            or_(Message.sender_messenger_user_id.is_(None), Message.sender_messenger_user_id != RoomUser.user_id),
        ).group_by(RoomUser.room_id, RoomUser.user_id)
    )
    projection.unread = {(room_id, user_id): int(count) for room_id, user_id, count in unread_rows}
    agent_rows = await db.execute(
        select(RoomUser.room_id, func.count(MessengerUser.id), func.min(MessengerUser.agent_id))
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(RoomUser.room_id.in_(room_ids), MessengerUser.is_ai.is_(True))
        .group_by(RoomUser.room_id)
    )
    projection.expected_agents = {room_id: agent_id if count == 1 else None for room_id, count, agent_id in agent_rows}
    return projection


async def _room_dto(
    room: Room,
    membership: RoomUser | None,
    connection: Connection,
    tool: Tool,
    agent: Agent,
    *,
    include_members: bool,
    projection: _RoomListProjection | None = None,
) -> NativeMessengerRoom:
    is_internal = tool.code == CHAT_TOOL_CODE
    members: list[NativeMessengerMember] = []
    if include_members:
        member_filter = RoomUser.room_id == room.id
        if is_internal and membership is not None:
            member_filter = and_(
                member_filter,
                or_(
                    RoomUser.user_id == membership.user_id,
                    and_(
                        MessengerUser.is_ai.is_(True),
                        MessengerUser.agent_id == connection.agent_id,
                    ),
                ),
            )
        rows = (
            await get_db().execute(
                select(MessengerUser, RoomUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(member_filter)
                .order_by(RoomUser.joined_at, MessengerUser.display_name)
            )
        ).all()
        await enrich_messenger_users([user for user, _relation in rows])
        members = [await _member_dto(user, relation) for user, relation in rows]
    if projection is None:
        projection = await _room_list_projection([room.id])
    last_message_dto = projection.last_messages.get(room.id)
    writable = bool(
        is_internal
        and membership is not None
        and membership.role == "owner"
        and connection.active
        and projection.expected_agents.get(room.id) == connection.agent_id
    )
    unread_count = (
        projection.unread.get((room.id, membership.user_id), 0) if membership is not None else 0
    )
    source = _tool_source(tool)
    messenger_kind = kind_for_tool(tool) or source
    messenger_spec = get_spec(messenger_kind)
    messenger_label = (
        messenger_spec.label
        if messenger_spec is not None and messenger_spec.label
        else tool.label
    )
    agent_name = " ".join(
        part for part in (agent.first_name, agent.last_name) if part
    ).strip() or agent.code
    room_label = room.label
    if membership is not None and membership.custom_label:
        room_label = membership.custom_label
    return NativeMessengerRoom(
        id=room.id,
        external_id=room.external_id,
        label=room_label,
        kind=room.kind,
        conversation_type=room.conversation_type,
        topic_id=room.topic_id,
        connection_id=room.connection_id,
        agent_id=connection.agent_id,
        agent_name=agent_name,
        agent_active=writable,
        source=None if is_internal else source,
        messenger_label=messenger_label,
        messenger_active=bool(
            connection.active and is_kind_enabled(messenger_kind)
        ),
        writable=writable,
        role=membership.role if membership is not None else "viewer",
        muted=membership.muted if membership is not None else False,
        unread_count=unread_count,
        show_last_message=(
            membership.show_last_message if membership is not None else True
        ),
        archived=membership.archived if membership is not None else False,
        last_message=last_message_dto,
        members=members,
    )


async def count_chat_unread(user_id: int) -> int:
    """Return the authoritative unread total across every mapped Chat room."""

    return int(
        await get_db().scalar(
            select(func.count(func.distinct(Message.id)))
            .select_from(RoomUser)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .join(Message, Message.messenger_room_id == RoomUser.room_id)
            .where(
                MessengerUser.galaris_user_id == user_id,
                Message.counts_as_unread.is_(True),
                Message.journal_position
                > func.coalesce(RoomUser.read_through_position, 0),
                or_(
                    Message.sender_messenger_user_id.is_(None),
                    Message.sender_messenger_user_id != RoomUser.user_id,
                ),
            )
        )
        or 0
    )


async def list_internal_rooms(
    user_id: int, *, page: int = 1, page_size: int = 50, search: str = ""
) -> NativeMessengerRoomPage:
    filters = [
        Tool.code == CHAT_TOOL_CODE,
        Room.kind == "direct",
        MessengerUser.external_id == human_external_id(user_id),
        RoomUser.role == "owner",
    ]
    if search.strip():
        filters.append(
            func.coalesce(RoomUser.custom_label, Room.label).ilike(
                f"%{search.strip()[:200]}%"
            )
        )
    base = (
        select(Room, RoomUser, Connection, Tool, Agent)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Tool, Tool.id == Connection.tool_id)
        .join(Agent, Agent.id == Connection.agent_id)
        .join(RoomUser, RoomUser.room_id == Room.id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(*filters)
    )
    total = int(
        await get_db().scalar(
            select(func.count()).select_from(base.subquery())
        )
        or 0
    )
    rows = (
        await get_db().execute(
            base.order_by(Room.updated_at.desc(), Room.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    projection = await _room_list_projection([row[0].id for row in rows])
    return NativeMessengerRoomPage(
        items=[
            await _room_dto(
                room, membership, connection, tool, agent, include_members=False,
                projection=projection,
            )
            for room, membership, connection, tool, agent in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_internal_room(user_id: int, room_id: UUID) -> NativeMessengerRoom | None:
    membership = await room_membership(user_id, room_id)
    if membership is None:
        return None
    room, relation, _identity, connection = membership
    tool = await get_db().get(Tool, connection.tool_id)
    agent = await get_db().get(Agent, connection.agent_id)
    if tool is None or agent is None:
        return None
    return await _room_dto(
        room, relation, connection, tool, agent, include_members=True
    )


async def list_chat_rooms(
    user_id: int,
    *,
    agent_id: int | None = None,
    agent_ids: Collection[int] | None = None,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    include_external: bool = True,
    include_archived: bool = False,
) -> NativeMessengerRoomPage:
    """List canonical rooms belonging to one linked Galaris identity."""

    identity_filter = (
        and_(
            MessengerUser.agent_id == agent_id,
            MessengerUser.is_ai.is_(True),
        )
        if agent_id is not None
        else or_(
            MessengerUser.galaris_user_id == user_id,
            and_(
                Tool.code == CHAT_TOOL_CODE,
                MessengerUser.external_id == human_external_id(user_id),
            ),
        )
    )
    base = (
        select(Room, RoomUser, Connection, Tool, Agent)
        .join(Connection, Connection.id == Room.connection_id)
        .join(Tool, Tool.id == Connection.tool_id)
        .join(Agent, Agent.id == Connection.agent_id)
        .join(RoomUser, RoomUser.room_id == Room.id)
        .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
        .where(
            identity_filter,
            Tool.code != MAIL_TOOL_CODE,
            Room.conversation_type == "text",
        )
    )
    if agent_ids is not None:
        if not agent_ids:
            return NativeMessengerRoomPage(
                items=[], total=0, page=page, page_size=page_size
            )
        base = base.where(Agent.id.in_(agent_ids))
    if search.strip():
        base = base.where(
            func.coalesce(RoomUser.custom_label, Room.label).ilike(
                f"%{search.strip()[:200]}%"
            )
        )
    if not include_external:
        base = base.where(Tool.code == CHAT_TOOL_CODE)
    if not include_archived:
        base = base.where(RoomUser.archived.is_(False))
    total = int(
        await get_db().scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    rows = (
        await get_db().execute(
            base.order_by(Room.updated_at.desc(), Room.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items: list[NativeMessengerRoom] = []
    projection = await _room_list_projection([row[0].id for row in rows])
    provider_rooms_by_connection: dict[int, list[UUID]] = {}
    for room, membership, connection, tool, agent in rows:
        items.append(
            await _room_dto(
                room,
                membership,
                connection,
                tool,
                agent,
                include_members=False,
                projection=projection,
            )
        )
        if connection.active and tool.code != CHAT_TOOL_CODE:
            provider_rooms_by_connection.setdefault(connection.id, []).append(room.id)

    provider_unread_counts: dict[str, int] = {}
    provider_slots = asyncio.Semaphore(4)

    async def refresh_provider(connection_id: int, room_ids: list[UUID]) -> None:
        # Each concurrent root owns its contextual session; never share the request's.
        async with provider_slots, get_db_session():
            await refresh_provider_counts(connection_id, room_ids)

    async def refresh_provider_counts(connection_id: int, room_ids: list[UUID]) -> None:
        messenger = None
        try:
            async with asyncio.timeout(2):
                messenger = await get_messenger(connection_id)
                if messenger.supports(Capability.UNREAD):
                    provider_unread_counts.update(
                        await messenger.unread_counts(room_ids)
                    )
        except Exception as exc:
            logger.warning(
                "Provider unread count refresh failed: connection={} error_type={}",
                connection_id,
                type(exc).__name__,
            )
        finally:
            if messenger is not None:
                try:
                    async with asyncio.timeout(2):
                        await messenger.close()
                except Exception as exc:
                    logger.warning(
                        "Provider unread client close failed: connection={} error_type={}",
                        connection_id,
                        type(exc).__name__,
                    )
    try:
        async with asyncio.timeout(8):
            await asyncio.gather(*(
                refresh_provider(connection_id, room_ids)
                for connection_id, room_ids in provider_rooms_by_connection.items()
            ))
    except TimeoutError:
        logger.warning("Provider unread refresh exceeded its deadline; returning local counts")
    if provider_unread_counts:
        items = [
            item.model_copy(
                update={
                    "unread_count": max(
                        item.unread_count,
                        provider_unread_counts.get(str(item.id), 0),
                    )
                }
            )
            for item in items
        ]
    return NativeMessengerRoomPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_chat_room(user_id: int, room_id: UUID) -> NativeMessengerRoom | None:
    row = await chat_room_membership(user_id, room_id)
    if row is None:
        return None
    room, membership, _identity, connection, tool = row
    agent = await get_db().get(Agent, connection.agent_id)
    if agent is None:
        return None
    return await _room_dto(
        room,
        membership,
        connection,
        tool,
        agent,
        include_members=True,
    )


async def get_agent_chat_room(
    agent_id: int,
    room_id: UUID,
) -> NativeMessengerRoom | None:
    row = (
        await get_db().execute(
            select(Room, RoomUser, Connection, Tool)
            .join(Connection, Connection.id == Room.connection_id)
            .join(Tool, Tool.id == Connection.tool_id)
            .join(RoomUser, RoomUser.room_id == Room.id)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(
                Room.id == room_id,
                Room.conversation_type == "text",
                MessengerUser.agent_id == agent_id,
                MessengerUser.is_ai.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    room, membership, connection, tool = row
    agent = await get_db().get(Agent, connection.agent_id)
    if agent is None:
        return None
    return await _room_dto(
        room,
        membership,
        connection,
        tool,
        agent,
        include_members=True,
    )


async def _synchronize_nextcloud_room_history_page(
    room_id: UUID,
    *,
    limit: int,
    cursor: str | None,
) -> HistoryPage[Message] | None:
    """Import one Talk history slice selected by the UI scroll cursor."""

    row = (
        await get_db().execute(
            select(Room, Connection, Tool)
            .join(Connection, Connection.id == Room.connection_id)
            .join(Tool, Tool.id == Connection.tool_id)
            .where(Room.id == room_id)
        )
    ).one_or_none()
    if row is None:
        return None
    room, connection, tool = row
    if _tool_source(tool) != "nextcloud_talk" or not connection.active:
        return None

    lock = _nextcloud_history_sync_locks.setdefault(room_id, asyncio.Lock())
    async with lock:
        messenger = None
        try:
            messenger = await get_messenger(connection.id)
            page = await messenger.history_page(
                room.id,
                limit=limit,
                cursor=cursor,
            )
            logger.info(
                "Nextcloud history page synchronized: room={} connection={} "
                "messages={} has_more={}",
                room_id,
                connection.id,
                len(page.messages),
                page.has_more,
            )
            return page
        except Exception as exc:
            logger.warning(
                "Nextcloud history synchronization failed: room={} connection={} "
                "error_type={}",
                room_id,
                connection.id,
                type(exc).__name__,
            )
            return None
        finally:
            if messenger is not None:
                await messenger.close()


async def list_chat_messages(
    user_id: int,
    room_id: UUID,
    *,
    agent_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    history_cursor: str | None = None,
) -> NativeMessengerMessagePage | None:
    if not (
        await has_agent_chat_room_access(agent_id, room_id)
        if agent_id is not None
        else await has_chat_room_access(user_id, room_id)
    ):
        return None
    provider_page = (
        await _synchronize_nextcloud_room_history_page(
            room_id,
            limit=page_size,
            cursor=history_cursor,
        )
        if page == 1 or history_cursor is not None
        else None
    )
    visible_message = Message.metadata_[
        CONVERSATION_OUTPUT_PENDING_METADATA_KEY
    ].as_boolean().is_not(True)
    total = int(
        await get_db().scalar(
            select(func.count(Message.id)).where(
                Message.messenger_room_id == room_id,
                visible_message,
            )
        )
        or 0
    )
    if provider_page is not None and history_cursor is not None:
        hydrated = [
            message
            for message in provider_page.messages
            if message.metadata_.get(CONVERSATION_OUTPUT_PENDING_METADATA_KEY) is not True
        ]
    else:
        rows = list(
            (
                await get_db().scalars(
                    select(Message)
                    .where(
                        Message.messenger_room_id == room_id,
                        visible_message,
                    )
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        rows.reverse()
        hydrated = await journal.hydrate_messages(rows)
    actor = await get_db().get(User, user_id)
    avatar_url = _user_avatar_url(actor)
    choices = await message_interactions(
        hydrated, viewer_user_id=user_id if agent_id is None else None,
    )
    return NativeMessengerMessagePage(
        items=[
            await _message_dto(
                message,
                human_avatar_url=avatar_url,
                human_external_id=(
                    message.sender.external_id
                    if message.sender is not None
                    and (
                        message.sender.galaris_user_id == user_id
                        or (
                            message.platform == INTERNAL_PLATFORM
                            and message.sender.external_id == human_external_id(user_id)
                        )
                    )
                    else None
                ),
                viewer_galaris_user_id=(user_id if agent_id is None else None),
                viewer_agent_id=agent_id,
                interaction=choices.get(message.id),
            )
            for message in hydrated
        ],
        total=total,
        page=page,
        page_size=page_size,
        provider_history=provider_page is not None,
        history_has_more=provider_page.has_more if provider_page is not None else False,
        history_next_cursor=(
            provider_page.next_cursor if provider_page is not None else None
        ),
    )


async def list_chat_message_agent_ids(
    user_id: int,
    room_id: UUID,
    *,
    agent_id: int | None = None,
) -> list[int] | None:
    """Return the linked agents that actually authored messages in a Chat room."""

    allowed = (
        await has_agent_chat_room_access(agent_id, room_id)
        if agent_id is not None
        else await has_chat_room_access(user_id, room_id)
    )
    if not allowed:
        return None
    users = list(
        (
            await get_db().scalars(
                select(MessengerUser)
                .join(RoomUser, RoomUser.user_id == MessengerUser.id)
                .where(RoomUser.room_id == room_id)
            )
        ).all()
    )
    await enrich_messenger_users(users)
    authored_external_ids = set(
        (
            await get_db().scalars(
                select(
                    case(
                        (Message.direction == "inbound", Message.user_id),
                        else_=Message.metadata_["sender_id"].as_string(),
                    )
                )
                .where(Message.messenger_room_id == room_id)
                .distinct()
            )
        ).all()
    )
    return sorted(
        {
            user.agent_id
            for user in users
            if user.external_id in authored_external_ids
            and user.is_ai
            and user.agent_id is not None
        }
    )


async def get_chat_message(
    user_id: int,
    room_id: UUID,
    message_id: UUID,
    *,
    agent_id: int | None = None,
) -> NativeMessengerMessage | None:
    """Return one exact Chat-visible message without scanning paginated history."""

    allowed = (
        await has_agent_chat_room_access(agent_id, room_id)
        if agent_id is not None
        else await has_chat_room_access(user_id, room_id)
    )
    if not allowed:
        return None
    row = await get_db().scalar(
        select(Message).where(
            Message.id == message_id,
            Message.messenger_room_id == room_id,
        )
    )
    if row is None:
        return None
    message = (await journal.hydrate_messages([row]))[0]
    actor = await get_db().get(User, user_id)
    avatar_url = _user_avatar_url(actor)
    choices = await message_interactions(
        [message], viewer_user_id=user_id if agent_id is None else None,
    )
    return await _message_dto(
        message,
        human_avatar_url=avatar_url,
        human_external_id=(
            message.sender.external_id
            if message.sender is not None
            and (
                message.sender.galaris_user_id == user_id
                or (
                    message.platform == INTERNAL_PLATFORM
                    and message.sender.external_id == human_external_id(user_id)
                )
            )
            else None
        ),
        viewer_galaris_user_id=(user_id if agent_id is None else None),
        viewer_agent_id=agent_id,
        interaction=choices.get(message.id),
    )


async def reassign_chat_message_topic(
    room_id: UUID,
    message_id: UUID,
    topic_id: UUID,
    *,
    include_following_same_topic: bool = False,
) -> int | None:
    """Manually reassign one message, optionally including later peers.

    The extended scope follows the canonical Chat ordering and only selects
    later messages from the same room that still carry the anchor's original
    Topic. Intervening messages assigned to another Topic are left untouched.
    """

    message = await get_db().scalar(
        select(Message)
        .where(
            Message.id == message_id,
            Message.messenger_room_id == room_id,
        )
        .with_for_update()
    )
    if message is None:
        return None
    room_topic_id = await get_db().scalar(
        select(Room.topic_id).where(Room.id == room_id)
    )
    previous_topic_id = resolve_effective_topic_id(
        message.topic_id,
        topic_overridden=message.topic_overridden,
        room_topic_id=room_topic_id,
    )
    if message.topic_overridden and message.topic_id == topic_id:
        return 0

    message_ids = [message.id]
    if include_following_same_topic:
        effective_topic = case(
            (Message.topic_overridden.is_(True), Message.topic_id),
            else_=func.coalesce(room_topic_id, Message.topic_id),
        )
        message_ids = list(
            (
                await get_db().scalars(
                    select(Message.id)
                    .where(
                        Message.messenger_room_id == room_id,
                        effective_topic == previous_topic_id,
                        or_(
                            Message.created_at > message.created_at,
                            and_(
                                Message.created_at == message.created_at,
                                Message.id >= message.id,
                            ),
                        ),
                    )
                    .order_by(Message.created_at, Message.id)
                    .with_for_update()
                )
            ).all()
        )

    await get_db().execute(
        update(Message)
        .where(Message.id.in_(message_ids))
        .values(topic_id=topic_id, topic_overridden=True)
    )
    await get_db().commit()
    return len(message_ids)


async def chat_file_access(
    user_id: int,
    room_id: UUID,
    file_id: UUID,
    *,
    agent_id: int | None = None,
) -> NativeMessengerFileAccess | None:
    allowed = (
        await has_agent_chat_room_access(agent_id, room_id)
        if agent_id is not None
        else await has_chat_room_access(user_id, room_id)
    )
    if not allowed:
        return None
    row = (
        await get_db().execute(
            select(File, Message)
            .join(Attachment, Attachment.file_id == File.id)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                File.id == file_id,
                Message.messenger_room_id == room_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    file, message = row
    return NativeMessengerFileAccess(
        id=file.id,
        room_id=room_id,
        connection_id=message.connection_id,
        name=file.name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        kind=file.kind,
    )


async def fetch_chat_file_bytes(
    user_id: int,
    room_id: UUID,
    file_id: UUID,
    *,
    agent_id: int | None = None,
) -> tuple[NativeMessengerFileAccess, bytes] | None:
    access = await chat_file_access(
        user_id,
        room_id,
        file_id,
        agent_id=agent_id,
    )
    if access is None:
        return None
    file = await get_db().get(File, file_id)
    if file is None:
        return None
    messenger = await get_messenger(access.connection_id)
    return access, await fetch_bytes(messenger, file)


async def list_internal_messages(
    user_id: int,
    room_id: UUID,
    *,
    page: int = 1,
    page_size: int = 50,
) -> NativeMessengerMessagePage | None:
    if await room_membership(user_id, room_id) is None:
        return None
    total = int(
        await get_db().scalar(
            select(func.count(Message.id)).where(Message.messenger_room_id == room_id)
        )
        or 0
    )
    rows = list(
        (
            await get_db().scalars(
                select(Message)
                .where(Message.messenger_room_id == room_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    rows.reverse()
    hydrated = await journal.hydrate_messages(rows)
    actor = await get_db().get(User, user_id)
    human_avatar_url = _user_avatar_url(actor)
    return NativeMessengerMessagePage(
        items=[
            await _message_dto(
                message,
                human_avatar_url=human_avatar_url,
                human_external_id=human_external_id(user_id),
                viewer_galaris_user_id=user_id,
            )
            for message in hydrated
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _mark_room_read(
    relation: RoomUser,
    room_id: UUID,
    message_id: UUID | None,
) -> tuple[bool, str | None]:
    message = (
        await get_db().scalar(
            select(Message)
            .where(Message.messenger_room_id == room_id)
            .order_by(Message.journal_position.desc())
            .limit(1)
        )
        if message_id is None
        else await get_db().scalar(
            select(Message).where(
                Message.id == message_id,
                Message.messenger_room_id == room_id,
            )
        )
    )
    if message_id is not None and message is None:
        return False, None
    if message is not None and (
        relation.read_through_position is None
        or message.journal_position > relation.read_through_position
    ):
        relation.read_through_position = message.journal_position
        relation.last_read_message_id = message.id
    await get_db().commit()
    return True, message.remote_message_id if message is not None else None


async def mark_chat_room_read(
    user_id: int, room_id: UUID, message_id: UUID | None = None
) -> bool:
    membership = await chat_room_membership(user_id, room_id, lock=True)
    if membership is None:
        return False
    room, relation, _identity, connection, tool = membership
    marked, provider_message_id = await _mark_room_read(
        relation,
        room_id,
        message_id,
    )
    if not marked:
        return False
    if tool.code == CHAT_TOOL_CODE or provider_message_id is None:
        return True
    messenger = None
    try:
        messenger = await get_messenger(connection.id)
        if messenger.supports(Capability.UNREAD):
            await messenger.mark_read(room.id, provider_message_id)
    except Exception as exc:
        logger.warning(
            "Provider read marker failed: room={} connection={} error_type={}",
            room_id,
            connection.id,
            type(exc).__name__,
        )
    finally:
        if messenger is not None:
            try:
                await messenger.close()
            except Exception as exc:
                logger.warning(
                    "Provider read marker client close failed: connection={} error_type={}",
                    connection.id,
                    type(exc).__name__,
                )
    return True


async def mark_internal_room_read(
    user_id: int, room_id: UUID, message_id: UUID | None = None
) -> bool:
    membership = await room_membership(user_id, room_id, lock=True)
    if membership is None:
        return False
    marked, _provider_message_id = await _mark_room_read(
        membership[1],
        room_id,
        message_id,
    )
    return marked


async def set_internal_room_muted(user_id: int, room_id: UUID, muted: bool) -> bool:
    membership = await room_membership(user_id, room_id, lock=True)
    if membership is None:
        return False
    membership[1].muted = muted
    await get_db().commit()
    return True


async def set_chat_room_muted(user_id: int, room_id: UUID, muted: bool) -> bool:
    """Set the local notification preference for any visible Chat room."""

    membership = await chat_room_membership(user_id, room_id, lock=True)
    if membership is None:
        return False
    membership[1].muted = muted
    await get_db().commit()
    return True


async def set_chat_room_archived(
    user_id: int,
    room_id: UUID,
    archived: bool,
) -> NativeMessengerRoom | None:
    """Set the authenticated member's local archive preference."""

    membership = await chat_room_membership(user_id, room_id, lock=True)
    if membership is None:
        return None
    membership[1].archived = archived
    await get_db().commit()
    return await get_chat_room(user_id, room_id)


async def update_chat_room_preferences(
    user_id: int,
    room_id: UUID,
    *,
    label: str,
    show_last_message: bool,
) -> NativeMessengerRoom | None:
    """Update the authenticated member's local presentation of any Chat room."""

    membership = await chat_room_membership(user_id, room_id, lock=True)
    if membership is None:
        return None
    normalized_label = label.strip()[:500]
    if not normalized_label:
        raise ValueError("A room label is required.")
    membership[1].custom_label = normalized_label
    membership[1].show_last_message = show_last_message
    await get_db().commit()
    return await get_chat_room(user_id, room_id)


async def update_chat_room_topic(
    user_id: int,
    room_id: UUID,
    *,
    topic_id: UUID | None,
) -> NativeMessengerRoom | None:
    """Set the canonical default Topic shared by every member of a Chat room."""

    membership = await chat_room_membership(user_id, room_id, lock=True)
    if membership is None:
        return None
    membership[0].topic_id = topic_id
    await get_db().commit()
    return await get_chat_room(user_id, room_id)


async def touch_chat_room(room_id: UUID) -> None:
    await get_db().execute(
        update(Room)
        .where(Room.id == room_id)
        .values(updated_at=datetime.now(timezone.utc))
    )


async def live_internal_file_ids() -> set[UUID]:
    return set(
        (
            await get_db().scalars(
                select(File.id)
                .join(Connection, Connection.id == File.connection_id)
                .join(Tool, Tool.id == Connection.tool_id)
                .where(Tool.code == CHAT_TOOL_CODE)
            )
        ).all()
    )


async def publish_internal_message(
    *,
    user_id: int,
    room_id: UUID,
    client_message_id: UUID,
    text: str,
    topic_id: UUID | None = None,
    reply_to_message_id: UUID | None = None,
    attachments: list[ObservedMessengerFile] | None = None,
    reasoning_effort_override: str | None = None,
    task_requested: bool = False,
    displayed_document_id: UUID | None = None,
    language: str | None = None,
) -> NativeMessengerMessage | None:
    # Admission runs in its own durable database session and locks the canonical
    # room while attaching the message to a ConversationRound. Keeping a lock in
    # the HTTP session here would make that nested admission wait on itself.
    membership = await room_membership(user_id, room_id)
    if membership is None:
        return None
    room, _relation, human, connection = membership
    scope = await internal_connection(connection.id)
    if (
        scope is None
        or not scope.active
        or not await _room_has_expected_agent(room.id, connection.agent_id)
    ):
        raise PermissionError("The room agent is unavailable.")
    reply_to: str | None = None
    if reply_to_message_id is not None:
        reply_to = await get_db().scalar(
            select(Message.remote_message_id).where(
                Message.id == reply_to_message_id,
                Message.messenger_room_id == room.id,
            )
        )
        if reply_to is None:
            raise LookupError("The replied-to message is inaccessible.")
    agent_identity = await get_db().scalar(
        select(MessengerUser).where(
            MessengerUser.tool_id == scope.tool_id,
            MessengerUser.agent_id == scope.agent_id,
        )
    )
    if agent_identity is None:
        agent = await get_db().get(Agent, scope.agent_id)
        if agent is None:
            raise LookupError("The room agent no longer exists.")
        agent_identity_id = await _ensure_agent(scope.tool_id, agent)
        agent_identity = await get_db().get(MessengerUser, agent_identity_id)
    assert agent_identity is not None
    observation = ObservedMessengerMessage(
        id=str(client_message_id),
        platform=INTERNAL_PLATFORM,
        tool_id=scope.tool_id,
        sender=ObservedMessengerUser(
            id=human.external_id,
            display_name=human.display_name,
            is_ai=False,
            connection_id=connection.id,
            tool_id=scope.tool_id,
        ),
        recipient=ObservedMessengerUser(
            id=agent_identity.external_id,
            display_name=agent_identity.display_name,
            agent_id=scope.agent_id,
            is_ai=True,
            connection_id=connection.id,
            tool_id=scope.tool_id,
        ),
        room=ObservedMessengerRoom(
            id=room.external_id,
            local_id=room.id,
            label=room.label,
            kind=cast(Literal["direct", "group"], room.kind),
            conversation_type="text",
            connection_id=connection.id,
            tool_id=scope.tool_id,
        ),
        text=text,
        attachments=list(attachments or []),
        topic_id=topic_id,
        topic_overridden=topic_id is not None,
        reply_to=reply_to,
        # Internal messages have no remote provider clock. Let the journal stamp their
        # exact receipt time instead of truncating causally ordered messages to one second.
        time=0,
    )
    from .inbound import dispatch_incoming

    direct_task_requested = task_requested or reasoning_effort_override is not None
    metadata: dict[str, object] = {}
    if language:
        metadata["language"] = normalize_language(language)
    if displayed_document_id is not None:
        metadata[DISPLAYED_DOCUMENT_METADATA_KEY] = f"document://{displayed_document_id}"
    if direct_task_requested:
        metadata[TASK_REQUESTED_METADATA_KEY] = True
    if reasoning_effort_override is not None:
        metadata[TASK_REASONING_EFFORT_METADATA_KEY] = reasoning_effort_override
    if not metadata:
        await dispatch_incoming(observation)
    else:
        await dispatch_incoming(observation, metadata=metadata)
    stored = await journal.stored_message(
        connection_id=connection.id,
        remote_message_id=str(client_message_id),
        direction="inbound",
    )
    if stored is None:
        raise RuntimeError("The native message was not persisted.")
    hydrated = await journal.hydrate_messages([stored])
    return await _message_dto(
        hydrated[0],
        human_external_id=human.external_id,
        viewer_galaris_user_id=user_id,
    )


async def reconcile_internal_admissions(*, limit: int = 500) -> int:
    """Retry native inbound messages interrupted before durable round admission."""

    safe_limit = max(1, min(limit, 500))
    async with get_db_session():
        pending = list(
            (
                await get_db().execute(
                    select(Message.connection_id, Message.remote_message_id)
                    .where(
                        Message.platform == INTERNAL_PLATFORM,
                        Message.direction == "inbound",
                        Message.status.in_(("received", "failed")),
                    )
                    .order_by(Message.created_at, Message.id)
                    .limit(safe_limit)
                )
            ).all()
        )

    recovered = 0
    from .service import admit_incoming

    for connection_id, remote_message_id in pending:
        message = await journal.stored_message(
            connection_id=int(connection_id),
            remote_message_id=str(remote_message_id),
            direction="inbound",
        )
        if message is None:
            continue
        try:
            await admit_incoming(message)
        except Exception as exc:
            await journal.update_inbound_admission_status(
                connection_id=int(connection_id),
                remote_message_id=str(remote_message_id),
                status="failed",
                error=type(exc).__name__,
            )
            logger.exception(
                "Chat admission recovery failed: connection={} message={}",
                connection_id,
                message.id,
            )
            continue
        await journal.update_inbound_admission_status(
            connection_id=int(connection_id),
            remote_message_id=str(remote_message_id),
            status="admitted",
        )
        recovered += 1
    if recovered:
        logger.info("Chat admissions recovered: count={}", recovered)
    return recovered


async def internal_outbound_observation(
    connection_id: int,
    room_external_id: str,
    text: str,
    *,
    reply_to: str | None = None,
    attachments: list[ObservedMessengerFile] | None = None,
) -> ObservedMessengerMessage:
    scope = await internal_connection(connection_id)
    if scope is None or not scope.active:
        raise PermissionError("The Chat connection is inactive.")
    room = await get_db().scalar(
        select(Room).where(
            Room.connection_id == connection_id,
            Room.external_id == room_external_id,
        )
    )
    if room is None:
        raise LookupError("The Chat room is unknown.")
    if not await _room_has_expected_agent(room.id, scope.agent_id):
        raise PermissionError("The Chat room must contain its unique agent.")
    agent = await get_db().scalar(
        select(MessengerUser).where(
            MessengerUser.tool_id == scope.tool_id,
            MessengerUser.agent_id == scope.agent_id,
        )
    )
    if agent is None:
        raise LookupError("The Chat agent identity is missing.")
    recipient = await get_db().scalar(
        select(MessengerUser)
        .join(RoomUser, RoomUser.user_id == MessengerUser.id)
        .where(
            RoomUser.room_id == room.id,
            MessengerUser.is_ai.is_(False),
        )
        .order_by(RoomUser.joined_at)
        .limit(1)
    )
    return ObservedMessengerMessage(
        id=str(uuid4()),
        platform=INTERNAL_PLATFORM,
        tool_id=scope.tool_id,
        sender=ObservedMessengerUser(
            id=agent.external_id,
            display_name=agent.display_name,
            agent_id=agent.agent_id,
            is_ai=True,
            connection_id=connection_id,
            tool_id=scope.tool_id,
        ),
        recipient=(
            ObservedMessengerUser(
                id=recipient.external_id,
                display_name=recipient.display_name,
                connection_id=connection_id,
                tool_id=scope.tool_id,
            )
            if recipient is not None
            else None
        ),
        room=ObservedMessengerRoom(
            id=room.external_id,
            local_id=room.id,
            label=room.label,
            kind=cast(Literal["direct", "group"], room.kind),
            conversation_type=cast(Literal["audio", "text"], room.conversation_type),
            connection_id=connection_id,
            tool_id=scope.tool_id,
        ),
        text=text,
        attachments=list(attachments or []),
        reply_to=reply_to,
        # Internal messages have no remote provider clock; the journal owns their precise time.
        time=0,
    )


async def internal_history_observations(
    connection_id: int, room_external_id: str, limit: int
) -> list[ObservedMessengerMessage]:
    rows = await journal.history(connection_id, room_external_id, min(limit, 500))
    observations: list[ObservedMessengerMessage] = []
    for row in rows:
        observations.append(
            ObservedMessengerMessage(
                id=row.remote_message_id,
                local_id=row.id,
                platform=row.platform,
                tool_id=row.tool_id,
                sender=(
                    ObservedMessengerUser(
                        id=row.sender.external_id,
                        display_name=row.sender.display_name,
                        agent_id=row.sender.agent_id,
                        is_ai=row.sender.is_ai,
                    )
                    if row.sender is not None
                    else None
                ),
                recipient=(
                    ObservedMessengerUser(
                        id=row.recipient.external_id,
                        display_name=row.recipient.display_name,
                        agent_id=row.recipient.agent_id,
                        is_ai=row.recipient.is_ai,
                    )
                    if row.recipient is not None
                    else None
                ),
                room=ObservedMessengerRoom(
                    id=row.room.external_id if row.room is not None else room_external_id,
                    local_id=row.messenger_room_id,
                    label=row.room.label if row.room is not None else "",
                    kind=cast(
                        Literal["direct", "group"],
                        row.room.kind if row.room is not None else "group",
                    ),
                    conversation_type=cast(
                        Literal["audio", "text"],
                        row.room.conversation_type if row.room is not None else "text",
                    ),
                ),
                text=row.text,
                attachments=[
                    ObservedMessengerFile(
                        id=file.external_identifier or str(file.id),
                        local_id=file.id,
                        name=file.name,
                        mime=file.mime_type,
                        size=file.size_bytes,
                        kind=cast(
                            Literal["image", "audio", "video", "document", "other"],
                            file.kind,
                        ),
                    )
                    for file in row.files
                ],
                reply_to=row.reply_to,
                time=int(row.created_at.timestamp()),
            )
        )
    return observations


async def internal_file_access(
    *, user_id: int, room_id: UUID, file_id: UUID
) -> NativeMessengerFileAccess | None:
    if await room_membership(user_id, room_id) is None:
        return None
    row = (
        await get_db().execute(
            select(File, Message)
            .join(Attachment, Attachment.file_id == File.id)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                File.id == file_id,
                Message.messenger_room_id == room_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    file, message = row
    return NativeMessengerFileAccess(
        id=file.id,
        room_id=room_id,
        connection_id=message.connection_id,
        name=file.name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        kind=file.kind,
    )


async def internal_file_for_connection(
    *, connection_id: int, room_external_id: str, file_id: UUID
) -> NativeMessengerFileAccess | None:
    row = (
        await get_db().execute(
            select(File, Message, Room)
            .join(Attachment, Attachment.file_id == File.id)
            .join(Message, Message.id == Attachment.message_id)
            .join(Room, Room.id == Message.messenger_room_id)
            .where(
                File.id == file_id,
                File.connection_id == connection_id,
                Room.connection_id == connection_id,
                Room.external_id == room_external_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    file, _message, room = row
    return NativeMessengerFileAccess(
        id=file.id,
        room_id=room.id,
        connection_id=connection_id,
        name=file.name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        kind=file.kind,
    )


__all__ = [
    "CHAT_TOOL_CODE",
    "agent_external_id",
    "create_internal_room",
    "get_internal_room",
    "has_room_access",
    "human_external_id",
    "internal_agent_avatar",
    "internal_connection",
    "internal_direct_room_observation",
    "internal_file_access",
    "internal_file_for_connection",
    "internal_history_observations",
    "internal_outbound_observation",
    "search_internal_users",
    "list_internal_agents",
    "list_internal_messages",
    "list_internal_rooms",
    "mark_chat_room_read",
    "mark_internal_room_read",
    "set_internal_room_muted",
    "set_chat_room_archived",
    "set_chat_room_muted",
    "count_chat_unread",
    "update_chat_room_preferences",
    "touch_chat_room",
    "live_internal_file_ids",
    "publish_internal_message",
    "reassign_chat_message_topic",
    "reconcile_internal_admissions",
    "room_membership",
]
