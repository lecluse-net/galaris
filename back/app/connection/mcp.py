"""ToolAdmin's connection-centred commands use the common administration services."""

from typing import Any

from app.tools.facade import administration as admin
from app.tools import McpToolContext, mcp_tool


@mcp_tool("tool_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", description="List administrative connections, including inactive ones. Filter by tool_id, agent_id and active; pages default to 50, maximum 500.", effect_policy="read", concurrency_policy="safe", conversation_policy="short")
async def tool_admin_connection_list(ctx: McpToolContext, tool_id: int | None = None, agent_id: int | None = None, active: bool | None = None, offset: int = 0, limit: int = 50) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_list", admin.connection_list, tool_id=tool_id, agent_id=agent_id, active=active, offset=offset, limit=limit)


@mcp_tool("tool_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", description="Read local and effective redacted parameters, inheritance origins, forced values and current version. Resolve by connection_id or agent_id/tool_id pair.", effect_policy="read", concurrency_policy="safe", conversation_policy="short")
async def tool_admin_connection_get(ctx: McpToolContext, connection_id: int | None = None, tool_id: int | None = None, agent_id: int | None = None) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_get", admin.connection_get, connection_id=connection_id, tool_id=tool_id, agent_id=agent_id)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Create an inactive connection for an existing agent/Tool pair. Requires the Tool expected_version. Existing pairs return conflict; read the pair to reconcile.", conversation_policy="deferred")
async def tool_admin_connection_create(ctx: McpToolContext, tool_id: int, agent_id: int, expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_create", admin.connection_create, tool_id=tool_id, agent_id=agent_id, expected_version=expected_version)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Change only activation of an optional connection. Agent and Tool identity are immutable. Requires expected_version from connection_get.", conversation_policy="deferred")
async def tool_admin_connection_update(ctx: McpToolContext, connection_id: int, active: bool, expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_update", admin.connection_mutate, action="update", connection_id=connection_id, active=active, expected_version=expected_version)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Delete an optional connection with its local parameters and overrides, following domain FK cleanup and listener reconciliation. Inspect references with connection_get first.", conversation_policy="deferred")
async def tool_admin_connection_delete(ctx: McpToolContext, connection_id: int, expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_delete", admin.connection_mutate, action="delete", connection_id=connection_id, expected_version=expected_version)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Atomically patch local parameters. Entries use value, clear or secret_reference; omitted secrets remain unchanged. Forced globals cannot be overridden. Requires connection expected_version.", conversation_policy="deferred")
async def tool_admin_connection_params_set(ctx: McpToolContext, connection_id: int, params: dict[str, Any], expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_params_set", admin.connection_mutate, action="params", connection_id=connection_id, params=params, expected_version=expected_version)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Remove one local parameter override and return its resulting inherited value, redacted if secret.", conversation_policy="deferred")
async def tool_admin_connection_param_delete(ctx: McpToolContext, connection_id: int, param_name: str, expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_param_delete", admin.connection_mutate, action="param_delete", connection_id=connection_id, param_name=param_name, expected_version=expected_version)


@mcp_tool("tool_admin", approval='ask', approval_reason='Sensitive trace, content disclosure or remote diagnostic', description="Test the resolved HTTP/SSE configuration of an active or inactive connection. Reads inherited credentials server-side; does not activate, save parameters or call a remote function.", effect_policy="read", conversation_policy="deferred", timeout_seconds=40)
async def tool_admin_connection_test(ctx: McpToolContext, connection_id: int, offset: int = 0, limit: int = 50) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_test", admin.mcp_test, connection_id=connection_id, offset=offset, limit=limit)


@mcp_tool("tool_admin", approval="enabled", approval_reason="Governed bounded read or control without a new sensitive effect", description="Discover functions for this connection and show local/global/effective permission plus availability for the selected runtime and conversation/task context.", effect_policy="read", conversation_policy="deferred", timeout_seconds=40)
async def tool_admin_connection_function_list(ctx: McpToolContext, connection_id: int, offset: int = 0, limit: int = 50, runtime: str = "internal", conversation_only: bool = False) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_function_list", admin.connection_function_list, connection_id=connection_id, offset=offset, limit=limit, runtime=runtime, conversation_only=conversation_only)


@mcp_tool("tool_admin", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", description="Set local default/enabled/disabled. A local override wins over the global state; default removes it. Returns the effective state and current connection version.", conversation_policy="deferred")
async def tool_admin_connection_function_set(ctx: McpToolContext, connection_id: int, function_name: str, state: str, expected_version: str) -> str:
    return await admin.invoke(ctx, "tool_admin_connection_function_set", admin.connection_mutate, action="function", connection_id=connection_id, function_name=function_name, state=state, expected_version=expected_version)

from .agent_admin_mcp import (
    agent_tool_list as agent_tool_list,
    agent_connection_list as agent_connection_list,
    agent_connection_get as agent_connection_get,
    agent_connection_create as agent_connection_create,
    agent_connection_update as agent_connection_update,
    agent_connection_delete as agent_connection_delete,
    agent_connection_params_set as agent_connection_params_set,
    agent_connection_param_delete as agent_connection_param_delete,
    agent_connection_function_list as agent_connection_function_list,
    agent_connection_function_set as agent_connection_function_set,
)
