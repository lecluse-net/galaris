"""Attach server-owned execution evidence to native MCP responses."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from fastmcp.exceptions import ValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams
from pydantic import ValidationError as PydanticValidationError

from .contracts import EXECUTION_META_KEY, ToolExecutionContext, tool_execution


class ExecutionEvidenceMiddleware(Middleware):
    def __init__(self, native_names: set[str]) -> None:
        self.native_names = native_names

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.message.name not in self.native_names:
            result = await call_next(context)
            # Proxied servers cannot assert native pre-dispatch rejection evidence.
            if result.meta:
                result.meta.pop(EXECUTION_META_KEY, None)
            return result
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        meta = request.meta if request is not None else context.message.meta
        raw: Any = getattr(meta, EXECUTION_META_KEY, None) if meta else None
        try:
            operation_id = (
                UUID(str(cast(dict[str, Any], raw).get("operation_id")))
                if isinstance(raw, dict)
                else uuid4()
            )
        except ValueError:
            operation_id = uuid4()
        execution = ToolExecutionContext(operation_id, context.message.name)
        with tool_execution(execution):
            try:
                result = await call_next(context)
            except ValidationError, PydanticValidationError:
                # FastMCP distinguishes argument validation from errors inside the body.
                if execution.entered:
                    raise
                execution.outcome = "rejected"
                result = ToolResult(
                    content="Invalid tool arguments; correct the call to match its schema.",
                    is_error=True,
                )
            if not result.is_error:
                execution.outcome = "returned"
            result.meta = {
                **(result.meta or {}),
                EXECUTION_META_KEY: {
                    "operation_id": str(operation_id),
                    "tool_name": execution.tool_name,
                    "outcome": execution.outcome,
                },
            }
            return result
