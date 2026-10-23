"""Goal ownership and live administrative delegation, shared with File Share."""

from uuid import UUID

from app.tools.facade import administration_scope

from . import goal_service


async def readable_agents(actor_agent_id: int) -> frozenset[int] | None:
    scope = await administration_scope(actor_agent_id, "goal_management")
    return None if scope.is_global else (scope.agent_ids or frozenset()) | {actor_agent_id}


async def owner_scope(actor_agent_id: int, goal_id: UUID, *, manage: bool = False) -> int:
    scope = await administration_scope(actor_agent_id, "goal_management")
    if manage:
        scope.require_administration()
    record = await goal_service.get_by_id(goal_id, for_update=manage)
    if record is None:
        raise ValueError("Goal not found in the current agent scope")
    if not manage and record.agent_id != actor_agent_id and not scope.allows(record.agent_id):
        raise ValueError("Goal not found in the current agent scope")
    if manage:
        scope.require(record.agent_id)
    return record.agent_id
