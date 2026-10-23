"""Explicit MCP delegation, independent of an ambient HTTP user."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy import select

from core.authorize import check_privilege, role_id_ctx
from core.database import get_db
from core.user import UserModel, get_user_record

from .management_scope import AgentManagementScope, management_scope_for
from .models import Agent


@dataclass(frozen=True)
class AdminDelegation:
    caller_id: int
    manager: UserModel
    scope: AgentManagementScope
    delegation_level: str = "all"
    manager_is_global: bool = False

    async def target(self, agent_id: int) -> Agent:
        if agent_id == self.caller_id:
            raise PermissionError("An administrator agent cannot modify itself")
        self.scope.require(agent_id)
        agent = await get_db().scalar(select(Agent).where(Agent.id == agent_id)
                                     .execution_options(populate_existing=True))
        if agent is None:
            raise LookupError("Agent not found")
        if not self.manager_is_global and agent.user_id != self.manager.id:
            raise PermissionError("The target no longer belongs to the delegated manager")
        return agent

    async def team(self, team_id: int | None) -> None:
        if self.delegation_level == "all":
            return
        from core.team import TeamModel
        from .models import AgentTeam
        if team_id is None or not await get_db().scalar(select(AgentTeam.id).join(
            TeamModel, TeamModel.id == AgentTeam.team_id).where(
                AgentTeam.agent_id == self.caller_id, AgentTeam.team_id == team_id)):
            raise PermissionError("The team is outside the AgentAdmin management scope")

    async def reference(self, identity: int, *, title: bool = False) -> None:
        """Shared-reference mutations must not change the caller indirectly."""
        from .models import AgentTeam
        caller = await get_db().scalar(select(Agent).where(Agent.id == self.caller_id)
                                       .execution_options(populate_existing=True))
        affects_caller = caller is not None and (
            caller.title_id == identity if title else caller.group_id == identity or bool(
                await get_db().scalar(select(AgentTeam.id).where(
                    AgentTeam.agent_id == self.caller_id, AgentTeam.team_id == identity))))
        if affects_caller:
            raise PermissionError("An administrator agent cannot modify its own shared references")

    def manager_change(self, target_id: int | None, manager_id: int) -> None:
        if target_id == self.caller_id or (not self.scope.is_global and manager_id != self.manager.id):
            raise PermissionError("The delegated manager cannot be changed outside the current scope")


@asynccontextmanager
async def delegated_admin(
    caller_id: int, function: str, *privileges: str, global_scope: bool = False,
) -> AsyncGenerator[AdminDelegation]:
    from app.tools.facade import administration_scope, has_active_admin_function

    if not await has_active_admin_function(caller_id, function):
        raise PermissionError("AgentAdmin delegation is inactive or revoked")
    caller = await get_db().scalar(select(Agent).where(Agent.id == caller_id)
                                  .execution_options(populate_existing=True))
    manager = await get_user_record(caller.user_id) if caller else None
    if manager is not None:
        await get_db().refresh(manager)
    if manager is None or not manager.is_active:
        raise PermissionError("An active human manager is required")
    token = role_id_ctx.set(None)
    try:
        for privilege in privileges:
            if not await check_privilege(manager, privilege, get_db()):
                raise PermissionError("The human manager lacks the required domain privilege")
        scope = await management_scope_for(manager, get_db())
        manager_is_global = scope.is_global
        delegated = await administration_scope(caller_id, "agent_admin")
        delegated.require_administration()
        if not delegated.is_global:
            ids = delegated.agent_ids or frozenset()
            if scope.agent_ids is not None:
                ids = ids & scope.agent_ids
            scope = AgentManagementScope(manager.id, ids)
        if global_scope and not scope.is_global:
            raise PermissionError("Global Agent management is required for this shared reference")
        yield AdminDelegation(caller_id, manager, scope, delegated.level, manager_is_global)
    finally:
        role_id_ctx.reset(token)


async def admin_available(caller_id: int, *privileges: str, global_scope: bool = False) -> bool:
    """Live public catalogue predicate; mutations still check their exact function."""
    from app.tools.facade import administration_scope
    delegated = await administration_scope(caller_id, "agent_admin")
    if delegated.level == "usage" or (global_scope and not delegated.is_global):
        return False
    caller = await get_db().scalar(select(Agent).where(Agent.id == caller_id)
                                  .execution_options(populate_existing=True))
    manager = await get_user_record(caller.user_id) if caller else None
    if manager is not None:
        await get_db().refresh(manager)
    if manager is None or not manager.is_active:
        return False
    token = role_id_ctx.set(None)
    try:
        return (all([await check_privilege(manager, p, get_db()) for p in privileges])
                and (not global_scope or await check_privilege(manager, "AGENT_MANAGE_ALL", get_db())))
    finally:
        role_id_ctx.reset(token)
