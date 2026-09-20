"""Authorize live notifications with the domain's HTTP management scope."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.agent import management_scope_for
from core import websocket
from core.database import get_db
from core.user import UserModel
from .models import Goal


async def _authorize(user: UserModel, action: str, data: Mapping[str, Any]) -> bool:
    scope = await management_scope_for(user, get_db())
    if action == "delete":
        return scope.allows(data.get("agent_id")) and (
            data.get("referrer_agent_id") is None or scope.allows(data["referrer_agent_id"])
        )
    goal = await get_db().get(Goal, UUID(str(data["id"])))
    return goal is not None and scope.allows(goal.agent_id) and (
        goal.referrer_agent_id is None or scope.allows(goal.referrer_agent_id)
    )


async def _authorize_settings(_user: UserModel, _action: str, _data: Mapping[str, Any]) -> bool:
    # Like GET /goals/settings, this is shared configuration; core already checks GOAL_ACCESS.
    return True


def register_events() -> None:
    websocket.register_event_authorization("goal", _authorize)
    websocket.register_event_authorization("goal_settings", _authorize_settings)
