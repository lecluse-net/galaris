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


async def has_galaris_admin_access(agent_id: int) -> bool:
    """Resolve the live global administration grant, without caching revocations."""
    from app.connection import facade as connection_service

    return await connection_service.has_active_tool_connection(
        agent_id=agent_id, tool_code=GALARIS_ADMIN_TOOL_CODE,
    )


async def require_galaris_admin_access(agent_id: int) -> None:
    """Require the caller's optional administration connection to remain active."""

    if not await has_galaris_admin_access(agent_id):
        raise PermissionError(
            "An active galaris_admin connection is required to inspect execution datasets."
        )


__all__ = ["GALARIS_ADMIN_TOOL_CODE", "has_galaris_admin_access", "require_galaris_admin_access",
           "has_documentation_access", "require_documentation_access"]
