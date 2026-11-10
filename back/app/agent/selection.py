"""Minimal agent choices, resolved against the same scopes as domain operations."""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from core.database import get_db
from core.team import TeamModel
from .models import Agent

from .dialogue_service import current_dialogue_scope, policy_snapshot
from .management_scope import current_management_scope

AgentSelectionScope = Literal["management", "dialogue", "teams"]


class AgentSelectionTeam(BaseModel):
    id: int
    name: str
    order: int


class AgentSelectionOption(BaseModel):
    id: int
    label: str
    has_avatar: bool
    driver: str | None = None
    teams: list[AgentSelectionTeam] = Field(default_factory=list[AgentSelectionTeam])


async def selection_options(scope: AgentSelectionScope) -> list[AgentSelectionOption]:
    """Return only display metadata; endpoint authorization gates team composition."""
    allowed = (
        None if scope == "teams" else
        await current_dialogue_scope() if scope == "dialogue" else
        await current_management_scope()
    )
    policy = await policy_snapshot()
    visible = [agent for agent in policy.agents.values() if allowed is None or allowed.allows(agent.id)]
    visible_team_ids = {team_id for agent in visible for team_id in agent.team_ids}
    teams = [
        AgentSelectionTeam(id=team.id, name=team.name, order=team.order)
        for team in await get_db().scalars(
            select(TeamModel).where(TeamModel.id.in_(visible_team_ids)).order_by(TeamModel.order, TeamModel.id)
        )
    ]
    drivers: dict[int, str] = {
        identity: driver for identity, driver in (await get_db().execute(
            select(Agent.id, Agent.agent_driver).where(Agent.id.in_([agent.id for agent in visible]))
        )).all()
    } if scope == "management" else {}
    return [
        AgentSelectionOption(id=agent.id, label=agent.label, has_avatar=agent.has_avatar, driver=drivers.get(agent.id),
                             teams=[team for team in teams if team.id in agent.team_ids])
        for agent in visible
    ]
