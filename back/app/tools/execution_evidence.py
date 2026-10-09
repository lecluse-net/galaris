"""Attach server-owned execution evidence to native MCP responses."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid4

from fastmcp.exceptions import ValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams
from pydantic import ValidationError as PydanticValidationError

from .contracts import EXECUTION_META_KEY, ToolExecutionContext, tool_execution
from .authorization import AUTHORIZATION_META_KEY, AuthorizationRequired, AuthorizationClosed
from .tool_arguments import parameter_advice


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
                result.meta.pop(AUTHORIZATION_META_KEY, None)
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
        control: Any = getattr(meta, AUTHORIZATION_META_KEY, None) if meta else None
        if isinstance(control, dict) and isinstance(cast(dict[str, Any], control).get("continuation"), str):
            execution.authorization_continuation = cast(str, control["continuation"])
        with tool_execution(execution):
            try:
                result = await call_next(context)
            except AuthorizationRequired as exc:
                execution.outcome = "rejected"
                result = ToolResult(content="Authorization required before execution.", is_error=True,
                                    meta={AUTHORIZATION_META_KEY: {"request_id": str(exc.request_id),
                                          "continuation": exc.continuation,
                                          "status": "pending", "disposition": "authorization_required"}})
            except AuthorizationClosed as exc:
                execution.outcome = "rejected"
                result = ToolResult(content=str(exc), is_error=True,
                                    meta={AUTHORIZATION_META_KEY: {"request_id": str(exc.request_id),
                                          "status": exc.status, "disposition": "authorization_closed"}})
            except ValidationError, PydanticValidationError:
                # FastMCP distinguishes argument validation from errors inside the body.
                if execution.entered:
                    raise
                execution.outcome = "rejected"
                advice: dict[str, Any] = {}
                if context.fastmcp_context is not None:
                    tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
                    if tool is not None:
                        advice = parameter_advice(tool.parameters)
                result = ToolResult(
                    content="Invalid tool arguments; correct the call to match its schema. " + json.dumps(advice),
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
