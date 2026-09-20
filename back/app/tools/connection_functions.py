"""Tool-owned discovery of functions exposed through a connection."""

from typing import Any

from app.agent import agent_service, validate_agent_driver
from app.connection.facade import (
    function_state_label,
    get_connection,
    get_params_as_dict,
    list_function_states,
    list_tool_function_states,
    resolve_function_enabled,
)
from core.i18n import tr

from . import tool_service
from .mcp_loader import (
    list_external_mcp_functions,
    list_internal_mcp_functions,
    mcp_tools_by_tool_code,
    native_tool_codes_for_tool,
)


async def _list_external_functions(
    tool: Any,
    params: dict[str, Any],
) -> list[tuple[str, str]]:
    """Query functions exposed by an external MCP connector."""

    return await list_external_mcp_functions(tool, params)


async def _list_internal_functions(
    agent_id: int,
    tool_code: str,
    *,
    tool: Any | None = None,
) -> list[tuple[str, str]]:
    """Build functions exposed by an integrated Galaris tool in memory."""

    agent = await agent_service.get(agent_id)
    runtime = validate_agent_driver(
        getattr(agent, "agent_driver", None),
        require_available=False,
    )
    return await list_internal_mcp_functions(
        agent_id,
        tool_code,
        runtime=runtime,
        tool=tool,
    )


async def list_available_connection_functions(
    connection_id: int,
) -> dict[str, Any]:
    """List local and external functions with their effective authorization state."""

    connection = await get_connection(connection_id)
    if not connection:
        return {
            "success": False,
            "message": await tr("connection_api.errors.not_found"),
            "functions": [],
        }
    if not connection.active:
        return {
            "success": False,
            "message": await tr("connection_api.errors.inactive"),
            "functions": [],
        }

    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if not tool:
        return {
            "success": False,
            "message": await tr("connection_api.errors.tool_not_found_generic"),
            "functions": [],
        }

    connection_states = {
        state.function_name: state.enabled
        for state in await list_function_states(connection_id)
    }
    tool_states = {
        state.function_name: state.enabled
        for state in await list_tool_function_states(connection.tool_id)
    }
    has_internal = bool(
        native_tool_codes_for_tool(tool) & set(mcp_tools_by_tool_code())
    )
    has_external = bool(tool.mcp)
    if not (has_internal or has_external):
        return {
            "success": False,
            "message": await tr("connection_api.errors.no_functions"),
            "functions": [],
        }

    pairs: list[tuple[str, str]] = []
    failed_sources = 0
    if has_internal:
        try:
            pairs.extend(
                await _list_internal_functions(
                    connection.agent_id,
                    tool.code,
                    tool=tool,
                )
            )
        except Exception:  # Keep another independent source available.
            failed_sources += 1

    if has_external:
        try:
            _, params = await get_params_as_dict(
                connection_id,
                decrypt_passwords=True,
            )
            pairs.extend(await _list_external_functions(tool, params))
        except Exception:  # Keep another independent source available.
            failed_sources += 1

    if failed_sources and not pairs:
        return {
            "success": False,
            "message": await tr("connection_api.errors.connection_error"),
            "functions": [],
        }

    functions = [
        {
            "name": name,
            "description": description,
            "connection_state": function_state_label(connection_states.get(name)) if tool.can_disable else "enabled",
            "global_state": function_state_label(tool_states.get(name)) if tool.can_disable else "enabled",
            "effective": not tool.can_disable or resolve_function_enabled(
                name,
                connection_states,
                tool_states,
            ),
        }
        for name, description in pairs
    ]
    return {
        "success": True,
        "message": f"{len(functions)} function(s) available",
        "functions": functions,
    }
