"""Publish canonical Messenger changes to resource-authorized Chat sockets."""

from __future__ import annotations

from uuid import UUID
from collections.abc import Mapping
from typing import Any

from app.conversation import (
    ConversationRuntimeEvent,
    register_activity_listener,
    register_runtime_listener,
    register_document_display_publisher,
)
from app.messenger import (
    Interaction,
    interaction_changed,
    Message,
    has_ai_chat_room_access,
    has_chat_room_access,
    get_chat_room,
    get_internal_room,
    get_agent_chat_room,
    message_journaled,
    message_received,
    message_sent,
    touch_chat_room,
)
from app.voice import (
    VoiceCallInfo,
    VoiceTranscriptionEvent,
    register_voice_call_ended_listener,
    register_voice_transcription_listener,
)
from core import websocket
from core.database import get_db_session
from core.database import get_db
from core.authorize import check_privilege
from core.user import UserModel as User
from app.agent import dialogue_scope_for, management_scope_for
from .push_service import enqueue_message_push


class ChatRoom(websocket.BaseRoom):
    """One canonical Messenger room UUID visible in Chat."""


async def _publish_document_display(room_id: UUID, document_id: UUID) -> None:
    await websocket.emit(
        "chat", "document_show",
        {"room_id": str(room_id), "document_id": str(document_id)},
        room=ChatRoom(room_id),
    )


async def _publish(message: Message) -> None:
    if message.messenger_room_id is None:
        return
    # Signal receivers run sequentially. Touching the room in the caller's HTTP
    # session would retain a row lock while the next receiver opens its own
    # admission session and locks the same room, producing a self-deadlock.
    async with get_db_session():
        await touch_chat_room(message.messenger_room_id)
    await websocket.emit(
        "chat",
        "message",
        {
            "room_id": str(message.messenger_room_id),
            "message_id": str(message.id),
            "is_new": True,
        },
        room=ChatRoom(message.messenger_room_id),
    )


async def _publish_interaction(interaction: Interaction) -> None:
    if not interaction.room_id or not interaction.prompt_message_id:
        return
    try:
        room_id = UUID(interaction.room_id)
    except ValueError:
        return
    await websocket.emit(
        "chat", "message",
        {"room_id": str(room_id), "message_id": interaction.prompt_message_id, "is_new": False},
        room=ChatRoom(room_id),
    )


async def _publish_activity(round_id: UUID, room_id: UUID) -> None:
    await websocket.emit(
        "chat",
        "activity",
        {"room_id": str(room_id), "round_id": str(round_id)},
        room=ChatRoom(room_id),
    )


async def _publish_runtime(room_id: UUID, event: ConversationRuntimeEvent) -> None:
    await websocket.emit(
        "chat",
        "runtime",
        {"room_id": str(room_id), **event.model_dump(mode="json")},
        room=ChatRoom(room_id),
    )


async def _publish_call_ended(call: VoiceCallInfo) -> None:
    room_id = call.conversation_room_id
    if room_id is None:
        return
    await websocket.emit(
        "chat",
        "call",
        {
            "room_id": str(room_id),
            "call_id": call.call_id,
            "status": "ended",
        },
        room=ChatRoom(room_id),
    )


async def _publish_voice_transcription(event: VoiceTranscriptionEvent) -> None:
    await websocket.emit(
        "chat",
        "voice_transcription",
        {
            "room_id": str(event.room_id),
            "transcription_id": str(event.transcription_id),
            "status": event.status,
            "started_at": event.started_at.isoformat(),
            "message_id": (
                str(event.message_id) if event.message_id is not None else None
            ),
        },
        room=ChatRoom(event.room_id),
    )


def register_events() -> None:
    register_document_display_publisher(_publish_document_display)
    message_journaled.connect(_publish)
    interaction_changed.connect(_publish_interaction, required=False)
    message_journaled.connect(enqueue_message_push)
    message_received.connect(_publish, required=False)
    message_received.connect(enqueue_message_push, required=False)
    message_sent.connect(_publish)
    message_sent.connect(enqueue_message_push)
    register_activity_listener(_publish_activity)
    register_runtime_listener(_publish_runtime)
    register_voice_call_ended_listener(_publish_call_ended)
    register_voice_transcription_listener(_publish_voice_transcription)
    websocket.register_event_authorization("chat", _can_receive_event)
    websocket.register_resource_room(
        "chat",
        ChatRoom,
        required_privileges="CHAT_ACCESS",
        authorize=_can_access_room,
    )


async def _can_access_room(user_id: int, resource_id: str) -> bool:
    return await can_access_live_room(user_id, resource_id, voice=True)


async def _can_receive_event(user: User, action: str, data: Mapping[str, Any]) -> bool:
    return await can_access_live_room(
        user.id, str(data.get("room_id", "")),
        voice=action in {"call", "voice_transcription"},
    )


async def can_access_live_room(user_id: int, resource_id: str, *, voice: bool = False) -> bool:
    try:
        room_id = UUID(resource_id)
    except ValueError:
        return False
    user = await get_db().get(User, user_id)
    if user is None:
        return False
    if voice and await check_privilege(user, "CHAT_CALL", get_db()):
        if await get_internal_room(user_id, room_id) is not None:
            return True
    if await has_chat_room_access(user_id, room_id):
        room = await get_chat_room(user_id, room_id)
        return room is not None and (await dialogue_scope_for(user, get_db())).allows(room.agent_id)
    if not await check_privilege(user, "CHAT_IMPERSONATE", get_db()):
        return False
    scope = await management_scope_for(user, get_db())
    if scope.is_global:
        return await has_ai_chat_room_access(room_id)
    for agent_id in scope.agent_ids or ():
        if await get_agent_chat_room(agent_id, room_id) is not None:
            return True
    return False


__all__ = ["ChatRoom", "register_events", "can_access_live_room"]
