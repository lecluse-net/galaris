"""Resource assertions for room and attachment-scoped native Messenger routes."""

from __future__ import annotations

from uuid import UUID

from core.authorize import AssertionContext, BaseAssertion, check_privilege

from app.messenger import (
    get_chat_room,
    get_internal_room,
    has_agent_chat_room_access,
    has_chat_room_access,
    has_room_access,
    internal_file_access,
)
from app.agent import management_scope_for, dialogue_scope_for

CHAT_IMPERSONATE = "CHAT_IMPERSONATE"


def _agent_id(context: AssertionContext) -> int | None:
    raw = context.params.get("agent_id")
    if raw in {None, ""} and context.request is not None:
        raw = context.request.query_params.get("agent_id")
    try:
        parsed = int(str(raw))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class ChatScopeAssertion(BaseAssertion):
    async def assert_(self, context: AssertionContext) -> bool:
        agent_id = _agent_id(context)
        if agent_id is None:
            return context.user is not None and context.db is not None
        return bool(
            context.user is not None
            and context.db is not None
            and await check_privilege(context.user, CHAT_IMPERSONATE, context.db)
            and (await management_scope_for(context.user, context.db)).allows(agent_id)
        )


class ChatRoomAccessAssertion(BaseAssertion):
    async def assert_(self, context: AssertionContext) -> bool:
        room_id = _path_uuid(context, "room_id")
        agent_id = _agent_id(context)
        if context.user is None or context.db is None or room_id is None:
            return False
        if agent_id is not None:
            return bool(
                await check_privilege(context.user, CHAT_IMPERSONATE, context.db)
                and (await management_scope_for(context.user, context.db)).allows(agent_id)
                and await has_agent_chat_room_access(agent_id, room_id)
            )
        if not await has_chat_room_access(context.user.id, room_id):
            return False
        room = await get_chat_room(context.user.id, room_id)
        # Membership retains personal history after contact permission is revoked.
        return room is not None


def _path_uuid(context: AssertionContext, name: str) -> UUID | None:
    request = context.request
    raw = request.path_params.get(name) if request is not None else None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


class InternalRoomAccessAssertion(BaseAssertion):
    async def assert_(self, context: AssertionContext) -> bool:
        room_id = _path_uuid(context, "room_id")
        if context.user is None or context.db is None or room_id is None:
            return False
        if not await has_room_access(context.user.id, room_id):
            return False
        room = await get_internal_room(context.user.id, room_id)
        return bool(
            room is not None
            and (await dialogue_scope_for(context.user, context.db)).allows(
                room.agent_id
            )
        )


class InternalFileAccessAssertion(BaseAssertion):
    async def assert_(self, context: AssertionContext) -> bool:
        room_id = _path_uuid(context, "room_id")
        file_id = _path_uuid(context, "file_id")
        if (
            context.user is None
            or context.db is None
            or room_id is None
            or file_id is None
        ):
            return False
        room = await get_internal_room(context.user.id, room_id)
        return bool(
            room is not None
            and (await dialogue_scope_for(context.user, context.db)).allows(
                room.agent_id
            )
            and await internal_file_access(
                user_id=context.user.id, room_id=room_id, file_id=file_id
            )
            is not None
        )


__all__ = [
    "ChatRoomAccessAssertion",
    "ChatScopeAssertion",
    "InternalFileAccessAssertion",
    "InternalRoomAccessAssertion",
]
