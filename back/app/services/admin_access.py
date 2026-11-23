"""Live authorization witness for the Galaris administration tools."""

from __future__ import annotations


GALARIS_ADMIN_SERVICE_CODE = "galaris"


async def has_documentation_access(agent_id: int) -> bool:
    """The catalog function is the read grant, including direct file URI access."""
    from app.connection import facade as connections

    return await connections.has_active_service_function(agent_id, GALARIS_ADMIN_SERVICE_CODE, "documentation_catalog")


async def require_documentation_access(agent_id: int) -> None:
    if not await has_documentation_access(agent_id):
        raise PermissionError("An active Galaris connection with documentation_catalog enabled is required.")


async def has_galaris_admin_access(agent_id: int, *, target_agent_id: int | None = None) -> bool:
    """Check a target owner; omitting the target requires global administration."""
    from .management_scope import service_administration_scope
    scope = await service_administration_scope(agent_id)
    return scope.allows(target_agent_id)


async def require_galaris_admin_access(agent_id: int) -> None:
    """Require active global delegation on the Services connection."""

    if not await has_galaris_admin_access(agent_id):
        raise PermissionError(
            "An active Services connection with global management scope is required to inspect global execution datasets."
        )


async def has_process_admin_access(agent_id: int, *, target_agent_id: int | None = None) -> bool:
    """Check whether a delegated Process scope can extend resource permissions."""
    from .management_scope import administration_scope
    scope = await administration_scope(agent_id, "process")
    return scope.level in {"team", "all"} and scope.allows(target_agent_id)


__all__ = ["GALARIS_ADMIN_SERVICE_CODE", "has_galaris_admin_access", "require_galaris_admin_access",
           "has_documentation_access", "require_documentation_access", "has_process_admin_access"]
