"""AgentAdmin's connection-centred MCP commands."""

from typing import Any
from app.agent.facade import delegated_admin, PageLimit, PageOffset
from app.tools import McpToolContext, mcp_tool
from .schemas import FunctionState
from . import agent_admin_service as service


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed administrative read", name="agent_tool_list", description="List configurable Tools, public parameter schemas and mandatory status.", effect_policy="read", concurrency_policy="safe")
async def agent_tool_list(ctx: McpToolContext, agent_id: int, search: str = "", skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_tool_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        return await service.list_tools(search, skip, limit)


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_list", description="List managed agent connections, including inactive connections.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_list(ctx: McpToolContext, agent_id: int, tool_id: int | None = None, active_only: bool = False, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        return await service.list_connections(agent_id, tool_id, active_only, skip, limit)


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_get", description="Read a connection and effective parameters with secrets masked.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_get(ctx: McpToolContext, connection_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_get", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id)
        await grant.target(connection.agent_id)
        return await service.projection(connection_id)


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_create", description="Create one optional Tool connection for a managed agent. Administrative delegation requires a human.")
async def agent_connection_create(ctx: McpToolContext, agent_id: int, tool_id: int, active: bool = False) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_create", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        return await service.create(agent_id, tool_id, active)


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_update", description="Activate/deactivate a connection without changing its target or Tool.", effect_policy="idempotent")
async def agent_connection_update(ctx: McpToolContext, connection_id: int, active: bool) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_update", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id, editable=True)
        await grant.target(connection.agent_id)
        return await service.set_active(connection_id, active)


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_delete", description="Delete an optional connection and its parameters and local function permissions.", effect_policy="idempotent")
async def agent_connection_delete(ctx: McpToolContext, connection_id: int) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_delete", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id, editable=True)
        await grant.target(connection.agent_id)
        return await service.delete(connection_id)


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_params_set", description="Validate local parameters, encrypt secrets and return masked values.", effect_policy="idempotent")
async def agent_connection_params_set(ctx: McpToolContext, connection_id: int, params: dict[str, str | None]) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_params_set", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id, editable=True)
        await grant.target(connection.agent_id)
        return await service.params_set(connection_id, params)


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_param_delete", description="Remove a local parameter override and restore inheritance.", effect_policy="idempotent")
async def agent_connection_param_delete(ctx: McpToolContext, connection_id: int, param_name: str) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_param_delete", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id, editable=True)
        await grant.target(connection.agent_id)
        return await service.param_delete(connection_id, param_name)


@mcp_tool("agent_admin", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_function_list", description="List local/global function states and effective permissions, including inactive connections.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_function_list(ctx: McpToolContext, connection_id: int, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_function_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id)
        await grant.target(connection.agent_id)
        result = await service.functions(connection_id)
        result["functions"] = result["functions"][skip:skip + limit]
        result.update(skip=skip, limit=limit)
        return result


@mcp_tool("agent_admin", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_function_set", description="Set default/enabled/disabled locally. System functions and administrative delegation are protected.", effect_policy="idempotent")
async def agent_connection_function_set(ctx: McpToolContext, connection_id: int, function_name: str, state: FunctionState) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_function_set", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        connection = await service.require_connection(connection_id, editable=True)
        await grant.target(connection.agent_id)
        return await service.function_set(connection_id, function_name, state)
