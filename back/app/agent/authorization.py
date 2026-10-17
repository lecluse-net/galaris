"""Human-owned agent approval policy; never exposed as an MCP mutation."""

from dataclasses import dataclass

from sqlalchemy import select

from core.database import get_db
from .models import Agent


@dataclass(frozen=True)
class AgentAuthorizationPolicy:
    manager_user_id: int
    version: int


async def authorization_policy(agent_id: int, *, lock: bool = False) -> AgentAuthorizationPolicy:
    query = select(Agent).where(Agent.id == agent_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    agent = await get_db().scalar(query)
    if agent is None or agent.deleted_at is not None:
        raise PermissionError("Agent is unavailable")
    return AgentAuthorizationPolicy(agent.user_id, agent.authorization_version)
