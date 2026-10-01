"""Tool-owned discovery of functions exposed through a connection."""

from typing import Any, Literal

from app.agent import agent_service, validate_agent_driver
from app.connection.facade import (
    get_connection,
    get_params_as_dict,
    list_function_states,
    list_tool_function_states,
    project_function_policy,
    stored_function_state,
)
from core.i18n import tr

from . import tool_service
from .mcp_loader import (
    list_external_mcp_capabilities,
    list_internal_mcp_functions,
    mcp_tools_by_tool_code,
    native_tool_codes_for_tool,
)


async def _list_external_functions(
    tool: Any,
    params: dict[str, Any],
) -> list[tuple[str, str, Literal["tool", "resource", "prompt"]]]:
    """Query functions exposed by an external MCP connector."""

    return await list_external_mcp_capabilities(tool, params)


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
    *, include_inactive: bool = False,
) -> dict[str, Any]:
    """List local and external functions with their effective authorization state."""

    connection = await get_connection(connection_id)
    if not connection:
        return {
            "success": False,
            "message": await tr("connection_api.errors.not_found"),
            "functions": [],
        }
    if not connection.active and not include_inactive:
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

    local_rows = await list_function_states(connection_id)
    global_rows = await list_tool_function_states(connection.tool_id)
    connection_states = {
        state.function_name: stored_function_state(state)
        for state in local_rows
        if (state.capability_kind or "tool") == "tool"
    }
    tool_states = {
        state.function_name: stored_function_state(state)
        for state in global_rows
        if (state.capability_kind or "tool") == "tool"
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

    pairs: list[tuple[str, str] | tuple[str, str, Literal["tool", "resource", "prompt"]]] = []
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

    functions: list[dict[str, Any]] = []
    definitions = {definition.name: definition for code in native_tool_codes_for_tool(tool)
                   for definition in mcp_tools_by_tool_code().get(code, [])}
    from .authorization import canonical
    seen: set[str] = set()
    for pair in pairs:
        name, description = pair[:2]
        kind: Literal["tool", "resource", "prompt"] = pair[2] if len(pair) == 3 else "tool"
        identity = canonical((kind, name))
        if identity in seen:
            continue
        seen.add(identity)
        definition = definitions.get(name) if kind == "tool" else None
        if kind != "tool":
            connection_states = {row.function_name: stored_function_state(row) for row in local_rows if row.capability_kind == kind}
            tool_states = {row.function_name: stored_function_state(row) for row in global_rows if row.capability_kind == kind}
        else:
            connection_states = {row.function_name: stored_function_state(row) for row in local_rows if (row.capability_kind or "tool") == "tool"}
            tool_states = {row.function_name: stored_function_state(row) for row in global_rows if (row.capability_kind or "tool") == "tool"}
        policy = project_function_policy(name, connection_states, tool_states, capability_kind=kind,
                                         default=definition.approval if definition else "enabled",
                                         native=definition is not None)
        functions.append({**policy, "key": identity, "description": description,
                          "effective": connection.active and policy["effective"]})
    return {
        "success": True,
        "message": f"{len(functions)} function(s) available",
        "functions": functions,
    }
