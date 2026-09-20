"""Resource-authorized WebSocket projection of ephemeral agent-run events."""

from __future__ import annotations

from typing import Any, cast
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from loguru import logger

from app.agent import AgentLiveEvent, register_live_listener
from core import websocket
from core.authorize import Privileges
from core.database import get_db
from core.user import UserModel, get_user_record

from .models import Task


class TaskRunRoom(websocket.BaseRoom):
    """One live Task run, joined by its durable Task UUID."""


async def _can_read_task(user_id: int, resource_id: str) -> bool:
    from app.agent import management_scope_for

    try:
        task_id = UUID(resource_id)
    except ValueError:
        return False
    user = await get_user_record(user_id)
    if user is None:
        return False
    scope = await management_scope_for(user, get_db())
    agent_id = await get_db().scalar(select(Task.agent_id).where(Task.id == task_id))
    return scope.allows(agent_id)


async def _can_read_event(user: UserModel, action: str, data: Mapping[str, Any]) -> bool:
    from app.agent import management_scope_for

    if action == "cleanup" and not data:
        return True
    scope = await management_scope_for(user, get_db())
    agent_id = data.get("agent_id")
    return isinstance(agent_id, int) and scope.allows(agent_id)


async def publish_task_run(event: AgentLiveEvent) -> None:
    data = event.model_dump(mode="json", exclude_none=True)
    from .live_checkpoint import checkpoint_live_event

    try:
        snapshot = await checkpoint_live_event(event)
        if snapshot is not None:
            data["snapshot"] = snapshot.model_dump(mode="json")
    except Exception:
        logger.exception("Task activity checkpoint failed: task={} run={}", event.task_id, event.run_id)
    message = data.get("message")
    if isinstance(message, dict):
        message_data = cast(dict[str, object], message)
        message_data["content"] = str(message_data.get("content") or "")[:8_000]
        message_data.pop("tool_arguments", None)
        message_data.pop("tool_result", None)
    result = data.get("result")
    if isinstance(result, dict):
        result_data = cast(dict[str, object], result)
        result_data["prompt"] = ""
        result_data["system_prompt"] = ""
        result_data["result"] = str(result_data.get("result") or "")[:8_000]
        # The terminal snapshot must reconcile live tool cards, including runtimes
        # without invocation IDs. Keep the same bounded projection as live messages.
        for raw_message in cast(list[dict[str, object]], result_data.get("messages", [])):
            raw_message["content"] = str(raw_message.get("content") or "")[:8_000]
            raw_message.pop("tool_arguments", None)
            raw_message.pop("tool_result", None)
        result_data.pop("metadata", None)
    await websocket.emit(
        "agent_run",
        "event",
        data,
        room=TaskRunRoom(event.task_id),
    )


def register_events() -> None:
    websocket.register_event_authorization("task", _can_read_event)
    register_live_listener(publish_task_run)
    websocket.register_resource_room(
        "agent_run",
        TaskRunRoom,
        required_privileges=(Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
        authorize=_can_read_task,
    )


__all__ = ["TaskRunRoom", "publish_task_run", "register_events"]
