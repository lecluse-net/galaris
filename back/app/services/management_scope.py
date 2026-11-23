"""Live, connection-local administration scopes shared by native Services."""

from dataclasses import dataclass

from .contracts import MANAGEMENT_SCOPE_OPTIONS

EXECUTION_INSPECTION_SCOPE_SERVICE = "service"


@dataclass(frozen=True, slots=True)
class AdministrationScope:
    level: str
    agent_ids: frozenset[int] | None

    @property
    def is_global(self) -> bool:
        return self.level == "all"

    def allows(self, agent_id: int | None) -> bool:
        return self.is_global or (agent_id is not None and agent_id in (self.agent_ids or ()))

    def require(self, agent_id: int | None) -> None:
        if not self.allows(agent_id):
            raise PermissionError("Resource not found in the administration scope")

    def require_administration(self) -> None:
        if self.level == "usage":
            raise PermissionError("An explicit administration management scope is required")

    def require_global(self) -> None:
        if not self.is_global:
            raise PermissionError("Global administration management scope is required")


async def administration_level(agent_id: int, service_code: str) -> str:
    """Read only a valid local management value for a declared Service."""
    from app.connection.facade import get_management_scope

    options = MANAGEMENT_SCOPE_OPTIONS.get(service_code, ())
    if not options:
        return "usage"
    level = await get_management_scope(agent_id, service_code)
    return level if level in options else "usage"


async def administration_scope(agent_id: int, service_code: str) -> AdministrationScope:
    """Re-read activation, local delegation and active memberships on every call."""
    level = await administration_level(agent_id, service_code)
    if level == "all":
        return AdministrationScope(level, None)
    if level == "personal":
        return AdministrationScope(level, frozenset({agent_id}))
    if level == "team":
        from app.agent.facade import team_agent_ids

        ids = await team_agent_ids(agent_id)
        return AdministrationScope(level, ids - {agent_id} if service_code == "agent" else ids)
    # Unknown values, absent parameters and inactive connections fail closed.
    return AdministrationScope("usage", frozenset())


async def service_administration_scope(agent_id: int) -> AdministrationScope:
    """Use the Services connection for administration and execution inspection."""
    return await administration_scope(agent_id, EXECUTION_INSPECTION_SCOPE_SERVICE)
