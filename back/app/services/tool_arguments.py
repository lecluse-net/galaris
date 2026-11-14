"""Discard only undeclared top-level arguments from closed MCP input schemas."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams, TextContent

from .contracts import TOOL_ARGUMENTS_META_KEY


def normalize_tool_arguments(
    arguments: dict[str, Any], schema: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    # Open dictionaries and composed schemas can declare keys beyond properties.
    # Never drop such keys, or recursively rewrite caller-owned business payloads.
    if schema.get("additionalProperties") is not False or any(
        key in schema for key in ("$ref", "allOf", "anyOf", "oneOf", "if", "then", "else")
    ):
        return arguments, ()
    properties = cast(dict[str, Any], schema.get("properties", {}))
    patterns = cast(dict[str, Any], schema.get("patternProperties", {}))
    ignored = tuple(sorted(
        key for key in arguments
        if key not in properties and not any(re.search(pattern, key) for pattern in patterns)
    ))
    return ({key: value for key, value in arguments.items() if key not in ignored}, ignored)


def parameter_advice(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "available_parameters": sorted(cast(dict[str, Any], schema.get("properties", {}))),
        "required_parameters": schema.get("required", []),
    }


def argument_warning(name: str, ignored: tuple[str, ...], schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": TOOL_ARGUMENTS_META_KEY, "status": "warning", "tool_name": name,
        "ignored_parameters": list(ignored), **parameter_advice(schema),
        "instruction": "Unknown parameters were ignored. Use the available parameters for future calls.",
    }


class ToolArgumentsMiddleware(Middleware):
    """Normalize before validation and authorization; retain the result's contract."""

    async def on_call_tool(
        self, context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if not context.message.arguments or context.fastmcp_context is None:
            return await call_next(context)
        tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)
        if tool is None:
            return await call_next(context)
        arguments, ignored = normalize_tool_arguments(context.message.arguments, tool.parameters)
        if not ignored:
            return await call_next(context)
        normalized = context.copy(message=context.message.model_copy(update={"arguments": arguments}))
        result = await call_next(normalized)
        warning = argument_warning(context.message.name, ignored, tool.parameters)
        result.content = [*result.content, TextContent(type="text", text=json.dumps(
            warning, ensure_ascii=False,
        ))]
        result.meta = {**(result.meta or {}), TOOL_ARGUMENTS_META_KEY: warning}
        return result
