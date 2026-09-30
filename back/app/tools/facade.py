"""Stable configuration read port consumed by connection resolution."""

from typing import Any
from .schemas import Tool
from .secrets import public_connection_schema as public_connection_schema


async def has_active_admin_function(agent_id: int, function: str) -> bool:
    from app.connection.facade import has_active_tool_function

    return await has_active_tool_function(agent_id, "agent_admin", function)


async def get_tool_by_id(tool_id: int) -> Tool | None:
    from . import tool_service

    return await tool_service.get_tool_by_id(tool_id)


async def get_runtime_global_params(
    tool_id: int, *, decrypt_passwords: bool = True
) -> tuple[dict[str, Any], set[str]]:
    from . import tool_service

    return await tool_service.get_runtime_global_params(
        tool_id, decrypt_passwords=decrypt_passwords
    )


from .administration_lock import lock_tools, finish_write
from .admin_contracts import AdministrationContext, AdministrationError, HUMAN_ONLY_TOOL_CODES

from . import admin_service as administration

__all__ = [
    "get_tool_by_id",
    "get_runtime_global_params",
    "has_active_admin_function",
    "lock_tools",
    "finish_write",
    "AdministrationContext",
    "AdministrationError",
    "HUMAN_ONLY_TOOL_CODES",
    "administration",
]
