"""Live authorization witness for the optional Galaris administration package."""

from __future__ import annotations


GALARIS_ADMIN_TOOL_CODE = "galaris_admin"


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


__all__ = ["GALARIS_ADMIN_TOOL_CODE", "has_galaris_admin_access", "require_galaris_admin_access"]
