"""Authorize live notifications with the domain's HTTP management scope."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent import management_scope_for
from core import websocket
from core.database import get_db
from core.user import UserModel
from app.connection import Connection
from app.messenger import Room
from .models import VoiceConversationSession


async def _authorize(user: UserModel, _action: str, data: Mapping[str, Any]) -> bool:
    scope = await management_scope_for(user, get_db())
    agent_id = await get_db().scalar(
        select(Connection.agent_id).select_from(VoiceConversationSession)
        .join(Room, Room.id == VoiceConversationSession.messenger_room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(VoiceConversationSession.id == UUID(str(data["id"])))
    )
    return scope.allows(agent_id)


def register_events() -> None:
    websocket.register_event_authorization("voice_conversation", _authorize)
