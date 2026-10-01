"""Human-owned agent approval policy; never exposed as an MCP mutation."""

from dataclasses import dataclass

from sqlalchemy import select

from core.database import get_db
from .models import Agent, AgentAuthorizationChange


@dataclass(frozen=True)
class AgentAuthorizationPolicy:
    manager_user_id: int
    yolo: bool
    version: int


async def authorization_policy(agent_id: int, *, lock: bool = False) -> AgentAuthorizationPolicy:
    query = select(Agent).where(Agent.id == agent_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    agent = await get_db().scalar(query)
    if agent is None or agent.deleted_at is not None:
        raise PermissionError("Agent is unavailable")
    return AgentAuthorizationPolicy(agent.user_id, agent.yolo, agent.authorization_version)


async def set_yolo(agent_id: int, *, enabled: bool, acknowledged: bool, expected_version: int | None = None) -> Agent:
    if enabled and not acknowledged:
        raise ValueError("YOLO requires explicit acknowledgement")
    agent = await get_db().scalar(select(Agent).where(Agent.id == agent_id).with_for_update()
                                 .execution_options(populate_existing=True))
    if agent is None:
        raise LookupError("Agent not found")
    if expected_version is not None and expected_version != agent.authorization_version:
        raise ValueError("Authorization policy changed; reload the agent before changing YOLO")
    if agent.yolo != enabled:
        from core.user import user_service
        get_db().add(AgentAuthorizationChange(agent_id=agent.id, actor_user_id=user_service.get_current_user_id(),
            old_yolo=agent.yolo, new_yolo=enabled, version=agent.authorization_version + 1, reason="human_setting"))
        agent.yolo = enabled
        agent.authorization_version += 1
    await get_db().commit()
    return agent
