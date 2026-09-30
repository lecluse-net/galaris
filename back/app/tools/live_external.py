"""External calls resolve current credentials and authorization, even in old runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool
from .mcp_loader import resolve_live_connection


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
        del tool
        from .mcp import build_mcp_server

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
            return await server.call_tool(name, tool_args, ctx, current_tool)
