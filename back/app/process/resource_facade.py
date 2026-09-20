"""Public read-only projection of agent-assigned process definitions."""

from __future__ import annotations


from typing import Any

from . import process_service
from .models import ProcessDefinition


async def _tool_codes() -> dict[int, str]:
    return {
        tool.id: tool.code
        for tool in await process_service.list_process_tools()
    }


def _payload(
    definition: ProcessDefinition,
    *,
    tool_codes: dict[int, str],
) -> dict[str, Any]:
    created_at = definition.created_at
    updated_at = definition.updated_at
    return {
        "workflow_id": definition.engine_process_id,
        "label": definition.label,
        "description": definition.description,
        "tool_id": definition.tool_id,
        "tool_code": tool_codes.get(definition.tool_id, ""),
        "created_at": created_at.isoformat(),
        "updated_at": (
            updated_at.isoformat()
            if updated_at is not None
            else None
        ),
    }


async def read_process_resource(
    workflow_id: str,
    *,
    actor_agent_id: int,
) -> dict[str, Any] | None:
    definition = await process_service.get_for_agent(actor_agent_id, workflow_id)
    if definition is None:
        return None
    return _payload(definition, tool_codes=await _tool_codes())


async def list_process_resources(
    *,
    actor_agent_id: int,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    definitions = await process_service.list_resource_definitions_for_agent(
        actor_agent_id,
        query=query,
        offset=offset,
        limit=limit,
    )
    tool_codes = await _tool_codes()
    return [_payload(definition, tool_codes=tool_codes) for definition in definitions]


__all__ = ["list_process_resources", "read_process_resource"]
