"""Minimal agent choices, resolved against the same scopes as domain operations."""

from typing import Literal

from pydantic import BaseModel

from .dialogue_service import current_dialogue_scope, policy_snapshot
from .management_scope import current_management_scope

AgentSelectionScope = Literal["management", "dialogue", "teams"]


class AgentSelectionOption(BaseModel):
    id: int
    label: str
    has_avatar: bool


async def selection_options(scope: AgentSelectionScope) -> list[AgentSelectionOption]:
    """Return only display metadata; endpoint authorization gates team composition."""
    allowed = (
        None if scope == "teams" else
        await current_dialogue_scope() if scope == "dialogue" else
        await current_management_scope()
    )
    policy = await policy_snapshot()
    return [
        AgentSelectionOption(id=agent.id, label=agent.label, has_avatar=agent.has_avatar)
        for agent in policy.agents.values()
        if allowed is None or allowed.allows(agent.id)
    ]
