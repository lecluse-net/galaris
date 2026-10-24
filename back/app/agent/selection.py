"""Minimal agent choices, resolved against the same scopes as domain operations."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from core.database import get_db
from .models import Agent

from .dialogue_service import current_dialogue_scope, policy_snapshot
from .management_scope import current_management_scope

AgentSelectionScope = Literal["management", "dialogue", "teams"]


class AgentSelectionOption(BaseModel):
    id: int
    label: str
    has_avatar: bool
    driver: str | None = None


async def selection_options(scope: AgentSelectionScope) -> list[AgentSelectionOption]:
    """Return only display metadata; endpoint authorization gates team composition."""
    allowed = (
        None if scope == "teams" else
        await current_dialogue_scope() if scope == "dialogue" else
        await current_management_scope()
    )
    policy = await policy_snapshot()
    visible = [agent for agent in policy.agents.values() if allowed is None or allowed.allows(agent.id)]
    drivers: dict[int, str] = {
        identity: driver for identity, driver in (await get_db().execute(
            select(Agent.id, Agent.agent_driver).where(Agent.id.in_([agent.id for agent in visible]))
        )).all()
    } if scope == "management" else {}
    return [
        AgentSelectionOption(id=agent.id, label=agent.label, has_avatar=agent.has_avatar, driver=drivers.get(agent.id))
        for agent in visible
    ]
