"""Public read-only projection of agent-assigned process definitions."""

from __future__ import annotations


from typing import Any
from uuid import UUID

from . import process_service
from .models import ProcessDefinition


async def read_process_run_resource(identity: UUID, *, actor_agent_id: int) -> dict[str, Any]:
    """Observe an authorized run without refreshing or advancing its engine."""
    from . import native_runs
    from app.tools import has_process_admin_access

    run = await process_service.get_run(identity)
    if run is None:
        raise FileNotFoundError("Process run not found")
    if run.engine_code == "galaris":
        payload = await native_runs.inspect_run(identity, actor_agent_id)
    else:
        if run.launcher_agent_id != actor_agent_id and not await has_process_admin_access(actor_agent_id):
            raise PermissionError("Run not found in this agent's participation scope")
        detail = await process_service.get_run_detail(identity)
        if detail is None:
            raise FileNotFoundError("Process run not found")
        payload = detail.model_dump(mode="json")
    return {**payload, "resource_uri": f"processus://run/{identity}"}


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


__all__ = ["list_process_resources", "read_process_resource", "read_process_run_resource"]
