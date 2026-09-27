"""Authenticated human-management scope for Agent-backed API resources."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import RequestAuthorizationCache, check_privilege, role_id_ctx
from core.database import get_db
from core.user import user_service
from core.user import UserModel as User

from .models import Agent


MANAGE_ALL_AGENTS_PRIVILEGE = "AGENT_MANAGE_ALL"
_managed_agents = RequestAuthorizationCache[tuple[int, int | None], frozenset[int]]()


class AgentScopeDeniedError(PermissionError):
    """Raised when a human requests an Agent outside their management scope."""


@dataclass(frozen=True, slots=True)
class AgentManagementScope:
    """Exact Agent ids visible to a human, or every Agent for global managers."""

    user_id: int
    agent_ids: frozenset[int] | None

    @property
    def is_global(self) -> bool:
        return self.agent_ids is None

    def allows(self, agent_id: int | None) -> bool:
        return agent_id is not None and (
            self.agent_ids is None or agent_id in self.agent_ids
        )

    def require(self, agent_id: int | None) -> int:
        if not self.allows(agent_id):
            raise AgentScopeDeniedError(
                "Agent not found in the current management scope."
            )
        assert agent_id is not None
        return agent_id


async def management_scope_for(
    user: User,
    db: AsyncSession,
) -> AgentManagementScope:
    """Resolve one user's effective Agent-management scope."""

    if await check_privilege(user, MANAGE_ALL_AGENTS_PRIVILEGE, db):
        return AgentManagementScope(user_id=user.id, agent_ids=None)
    key = (user.id, role_id_ctx.get())
    cache = _managed_agents.entries(db.sync_session)
    if cache is not None and key in cache:
        return AgentManagementScope(user_id=user.id, agent_ids=cache[key])
    ids = frozenset(
        int(agent_id)
        for agent_id in (
            await db.scalars(select(Agent.id).where(Agent.user_id == user.id))
        ).all()
    )
    cache = _managed_agents.entries(db.sync_session)
    if cache is not None:
        cache[key] = ids
    return AgentManagementScope(user_id=user.id, agent_ids=ids)


async def current_management_scope() -> AgentManagementScope:
    """Resolve the authenticated human scope from the request context."""

    user = await user_service.get_current_user()
    if user is None:
        raise AgentScopeDeniedError("An authenticated user is required.")
    return await management_scope_for(user, get_db())


__all__ = [
    "AgentManagementScope",
    "AgentScopeDeniedError",
    "MANAGE_ALL_AGENTS_PRIVILEGE",
    "current_management_scope",
    "management_scope_for",
]
