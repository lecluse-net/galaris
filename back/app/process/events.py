"""Authorize live notifications with the domain's HTTP management scope."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent import management_scope_for
from core import websocket
from core.database import get_db
from core.user import UserModel
from .models import ProcessRun


async def _authorize(user: UserModel, action: str, data: Mapping[str, Any]) -> bool:
    scope = await management_scope_for(user, get_db())
    agent_id = data.get("launcher_agent_id") if action == "delete" else await get_db().scalar(
        select(ProcessRun.launcher_agent_id).where(ProcessRun.id == UUID(str(data["id"])))
    )
    return scope.allows(agent_id)


def register_events() -> None:
    websocket.register_event_authorization("process_run", _authorize)
