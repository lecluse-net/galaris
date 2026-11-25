"""AgentAdmin's connection-centred MCP commands."""

from typing import Any
from collections.abc import Awaitable, Callable
from app.agent.facade import delegated_admin, PageLimit, PageOffset
from app.services import McpToolContext, mcp_tool
from .service_selection import resolve_service_connection
from .schemas import FunctionState
from . import agent_admin_service as service


def _account_preflight(name: str) -> Callable[[McpToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def preflight(ctx: McpToolContext, args: dict[str, Any]) -> dict[str, Any]:
        async with delegated_admin(ctx.agent_id, name, "AGENT_EDIT", "CONNECTION_EDIT") as grant:
            await grant.target(args["agent_id"])
            if name == "agent_connection_create":
                return {"target_service": await service.service_identifier(args["service_code"])}
            connection = await resolve_service_connection(args["agent_id"], args["service_code"],
                account_email=args.get("account_email"), active_only=False)
            return {"target_account": connection.id}
    return preflight


@mcp_tool("agent", approval="enabled", approval_reason="Governed administrative read", name="agent_service_list", description="List configurable Services, public parameter schemas and mandatory status.", effect_policy="read", concurrency_policy="safe")
async def agent_service_list(ctx: McpToolContext, agent_id: int, search: str = "", skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_service_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        result = await service.list_tools(search, skip, limit)
        for item in result["items"]:
            item["service_code"] = item.pop("code")
            item.pop("id", None)
        return {"agent_id": agent_id, **result}


@mcp_tool("agent", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_list", description="List managed agent connections, including inactive connections.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_list(ctx: McpToolContext, agent_id: int, service_code: str | None = None, active_only: bool = False, skip: PageOffset = 0, limit: PageLimit = 50) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        service_id = await service.service_identifier(service_code) if service_code is not None else None
        result = await service.list_connections(agent_id, service_id, active_only, skip, limit)
        return {"agent_id": agent_id, **result}


@mcp_tool("agent", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_get", description="Read a connection and effective parameters with secrets masked.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_get(ctx: McpToolContext, agent_id: int, service_code: str, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_get", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        return await service.projection(connection.id)


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_create", authorization_preflight=_account_preflight("agent_connection_create"), description="Create one optional Service connection for a managed agent. Administrative delegation requires a human.")
async def agent_connection_create(ctx: McpToolContext, agent_id: int, service_code: str, active: bool = False) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_create", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        return await service.create(agent_id, await service.service_identifier(service_code), active)


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_update", authorization_preflight=_account_preflight("agent_connection_update"), description="Activate/deactivate a connection without changing its target or Service.", effect_policy="idempotent")
async def agent_connection_update(ctx: McpToolContext, agent_id: int, service_code: str, active: bool, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_update", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        return await service.set_active(connection.id, active)


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_delete", authorization_preflight=_account_preflight("agent_connection_delete"), description="Delete an optional connection and its parameters and local function permissions.", effect_policy="idempotent")
async def agent_connection_delete(ctx: McpToolContext, agent_id: int, service_code: str, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_delete", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        return {"service_code": service_code, **await service.delete(connection.id)}


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_params_set", authorization_preflight=_account_preflight("agent_connection_params_set"), description="Validate local parameters, encrypt secrets and return masked values.", effect_policy="idempotent")
async def agent_connection_params_set(ctx: McpToolContext, agent_id: int, service_code: str, params: dict[str, str | None], account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_params_set", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        return await service.params_set(connection.id, params)


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_param_delete", authorization_preflight=_account_preflight("agent_connection_param_delete"), description="Remove a local parameter override and restore inheritance.", effect_policy="idempotent")
async def agent_connection_param_delete(ctx: McpToolContext, agent_id: int, service_code: str, param_name: str, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_param_delete", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        return await service.param_delete(connection.id, param_name)


@mcp_tool("agent", approval="enabled", approval_reason="Governed administrative read", name="agent_connection_function_list", description="List local/global function states and effective permissions, including inactive connections.", effect_policy="read", concurrency_policy="safe")
async def agent_connection_function_list(ctx: McpToolContext, agent_id: int, service_code: str, skip: PageOffset = 0, limit: PageLimit = 50, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_function_list", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        result = await service.functions(connection.id)
        result["functions"] = result["functions"][skip:skip + limit]
        result.update(agent_id=connection.agent_id, skip=skip, limit=limit)
        return result


@mcp_tool("agent", approval="ask", approval_reason="Administrative mutation requires one-action approval", name="agent_connection_function_set", authorization_preflight=_account_preflight("agent_connection_function_set"), description="Set default/enabled/disabled locally. System functions and administrative delegation are protected.", effect_policy="idempotent")
async def agent_connection_function_set(ctx: McpToolContext, agent_id: int, service_code: str, function_name: str, state: FunctionState, account_email: str | None = None) -> dict[str, Any]:
    async with delegated_admin(ctx.agent_id, "agent_connection_function_set", "AGENT_EDIT", "CONNECTION_EDIT") as grant:
        await grant.target(agent_id)
        connection = await resolve_service_connection(agent_id, service_code, account_email=account_email, active_only=False)
        result = await service.function_set(connection.id, function_name, state)
        return {**result, "agent_id": connection.agent_id}
