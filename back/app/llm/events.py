"""Apply the HTTP trace scope to WebSocket recipients."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core import websocket
from core.database import get_db
from core.user import UserModel


async def _authorize(user: UserModel, action: str, data: Mapping[str, Any]) -> bool:
    from app.agent import management_scope_for
    from . import llm_call_service

    if action == "cleanup" and not data:
        return True
    scope = await management_scope_for(user, get_db())
    if scope.is_global:
        return True
    if action != "delete":
        return await llm_call_service.get_call(UUID(str(data["id"])), agent_ids=scope.agent_ids) is not None

    # A deleted row no longer exists. The publisher supplies only its durable
    # provenance, and the same related resources still determine its visibility.
    from app.task import Task
    from app.process import ProcessRun
    from app.conversation import ConversationRound
    from app.messenger import Room
    from app.connection import Connection

    if scope.allows(data.get("agent_id")):
        return True
    task_id = data.get("task_id")
    if task_id and scope.allows(await get_db().scalar(
        select(Task.agent_id).where(Task.id == UUID(str(task_id)))
    )):
        return True
    process_id = data.get("process_run_id")
    if process_id and scope.allows(await get_db().scalar(
        select(ProcessRun.launcher_agent_id).where(ProcessRun.id == UUID(str(process_id)))
    )):
        return True
    round_id = data.get("conversation_round_id")
    return bool(round_id and scope.allows(await get_db().scalar(
        select(Connection.agent_id).select_from(ConversationRound)
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(ConversationRound.id == UUID(str(round_id)))
    )))


def register_events() -> None:
    websocket.register_event_authorization("llm_call", _authorize)
