from typing import Any, Dict, Optional

from sqlalchemy import select

from core.authorize import BaseAssertion, AssertionContext, check_privilege

from .management_scope import MANAGE_ALL_AGENTS_PRIVILEGE
from .models import Agent


class AgentManagerAssertion(BaseAssertion):
    """Allow an Agent's assigned manager or a global Agent manager."""

    async def _has_global_access(self, context: AssertionContext) -> bool:
        return (
            context.user is not None
            and context.db is not None
            and await check_privilege(
                context.user,
                MANAGE_ALL_AGENTS_PRIVILEGE,
                context.db,
            )
        )

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        del privilege
        return (
            context.user is not None
            and (
                getattr(entity, "user_id", None) == context.user.id
                or await self._has_global_access(context)
            )
        )

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        del route_name
        if context.user is None or context.db is None:
            return False
        raw_agent_id = params.get("id", params.get("agent_id"))
        if isinstance(raw_agent_id, bool) or not isinstance(raw_agent_id, (int, str)):
            return False
        try:
            agent_id = int(raw_agent_id)
        except ValueError:
            return False
        owner_id = await context.db.scalar(
            select(Agent.user_id).where(Agent.id == agent_id)
        )
        return owner_id == context.user.id or await self._has_global_access(context)


# Compatibility for modules that still import the historical name. Its behavior now
# reflects the real domain concept: the assigned manager, with a global override.
AgentOwnerAssertion = AgentManagerAssertion


class AgentDialogueAssertion(BaseAssertion):
    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        from .dialogue_service import dialogue_scope_for
        if context.user is None or context.db is None:
            return False
        raw = params.get("agent_id", params.get("id"))
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            return False
        try:
            agent_id = int(raw)
        except ValueError:
            return False
        return (await dialogue_scope_for(context.user, context.db)).allows(agent_id)


__all__ = ["AgentManagerAssertion", "AgentOwnerAssertion", "AgentDialogueAssertion"]
