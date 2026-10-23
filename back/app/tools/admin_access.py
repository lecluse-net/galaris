"""Live authorization witness for the optional Galaris administration package."""

from __future__ import annotations


GALARIS_ADMIN_TOOL_CODE = "galaris_admin"


async def has_documentation_access(agent_id: int) -> bool:
    """The catalog function is the read grant, including direct file URI access."""
    from app.connection import facade as connections

    return await connections.has_active_tool_function(agent_id, GALARIS_ADMIN_TOOL_CODE, "documentation_catalog")


async def require_documentation_access(agent_id: int) -> None:
    if not await has_documentation_access(agent_id):
        raise PermissionError("An active galaris_admin connection with documentation_catalog enabled is required.")


async def has_galaris_admin_access(agent_id: int, *, target_agent_id: int | None = None) -> bool:
    """Check a target owner; omitting the target requires global administration."""
    from .management_scope import administration_scope
    scope = await administration_scope(agent_id, GALARIS_ADMIN_TOOL_CODE)
    return scope.allows(target_agent_id)


async def require_galaris_admin_access(agent_id: int) -> None:
    """Require the caller's optional administration connection to remain active."""

    if not await has_galaris_admin_access(agent_id):
        raise PermissionError(
            "An active galaris_admin connection with global management scope is required to inspect global execution datasets."
        )


async def has_process_admin_access(agent_id: int, *, target_agent_id: int | None = None) -> bool:
    """Check a run owner against the live Process administration scope."""
    from .management_scope import administration_scope
    return (await administration_scope(agent_id, "process_admin")).allows(target_agent_id)


__all__ = ["GALARIS_ADMIN_TOOL_CODE", "has_galaris_admin_access", "require_galaris_admin_access",
           "has_documentation_access", "require_documentation_access", "has_process_admin_access"]
