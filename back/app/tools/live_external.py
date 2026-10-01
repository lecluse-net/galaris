"""External calls resolve current credentials and authorization, even in old runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from .mcp_loader import resolve_live_connection
from .authorization import tool_authorization_configuration


class LiveConnectionToolset(AbstractToolset[Any]):
    """Pydantic AI adapter with a fresh transport at each discovery and effect."""

    def __init__(self, agent_id: int, connection_id: int, tool_id: int) -> None:
        self.agent_id = agent_id
        self.connection_id = connection_id
        self.tool_id = tool_id

    @property
    def id(self) -> str:
        return f"connection-{self.connection_id}"

    async def _server(self, function_name: str = "") -> Any:
        from .mcp import build_mcp_server

        tool, params, disabled = await resolve_live_connection(self.agent_id, self.connection_id, self.tool_id,
                                                              function_name=function_name)
        return build_mcp_server(tool, params, disabled_functions=disabled)

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        try:
            server = await self._server()
        except PermissionError:
            return {}
        async with server:
            tools = cast(dict[str, ToolsetTool[Any]], await server.get_tools(ctx))
        return {name: replace(tool, toolset=self) for name, tool in tools.items()}

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext[Any], tool: ToolsetTool[Any]) -> Any:
        from .mcp import build_mcp_server
        from .authorization import AuthorizationAction, claim_action, finish_action
        from .contracts import current_tool_execution

        current, params, disabled = await resolve_live_connection(self.agent_id, self.connection_id, self.tool_id)
        prefix = f"{current.code}_"
        raw_name = name.removeprefix(prefix)
        if raw_name in disabled:
            raise PermissionError("External MCP function was revoked.")
        server = build_mcp_server(current, params, disabled_functions=disabled)
        assert server is not None
        async with server:
            tools = await server.get_tools(ctx)
            current_tool = tools.get(name)
            if current_tool is None:
                raise PermissionError("External MCP function is no longer available.")
            execution = current_tool_execution()
            identifier = await claim_action(AuthorizationAction(
                agent_id=self.agent_id, runtime="internal", context_key=f"principal:internal:{self.id}",
                callback_key=str(execution.operation_id if execution else ctx.tool_call_id or uuid4()),
                tool_id=self.tool_id, connection_id=self.connection_id, name=raw_name,
                arguments=tool_args, configuration={"tool": tool_authorization_configuration(current), "params": params,
                    "schema": current_tool.tool_def.parameters_json_schema}, preview=f"{current.label}: {raw_name}",
            ))
            try:
                result = await server.call_tool(name, tool_args, ctx, current_tool)
            except BaseException:
                await finish_action(identifier, outcome="outcome_unknown")
                raise
            await finish_action(identifier, receipt=result)
            return result
