"""Stable configuration read port consumed by connection resolution."""

from typing import Any
from .schemas import Tool


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
