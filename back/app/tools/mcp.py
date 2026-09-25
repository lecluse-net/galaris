"""Construct and authenticate MCP transports from database tool configuration."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional, cast
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastmcp.client.transports import StdioTransport
from loguru import logger
from pydantic_ai.mcp import MCPToolset

from app.tools.mcp_loader import (
    McpToolContext,
    context_language,
    list_agent_mcp_tools,
    mcp_tool,
)
from app.tools.schemas import McpAuth, McpConfig, Tool
from app.tools.secrets import (
    MissingConnectionReference,
    resolve_connection_references,
    resolve_mapping_references,
)
from core.i18n import render_prompt, t

_MCP_TOOL_MAX_RETRIES = 3


@mcp_tool("galaris_admin", name="documentation_catalog", description=(
    "Discover the official Galaris documentation shipped with this installation: version, languages, "
    "domains and entrypoints. This function also grants read-only file access below galaris://documentation/. "
    "Use documentation_search for questions and file_read to verify sources."
), effect_policy="read", concurrency_policy="safe", conversation_policy="short")
async def documentation_catalog(ctx: McpToolContext) -> str:
    import json
    from . import documentation_service

    return json.dumps(await documentation_service.documentation_catalog(ctx.agent_id), ensure_ascii=False)


@mcp_tool("galaris_admin", name="documentation_search", description=(
    "Search official Galaris product knowledge to explain features, guide users and troubleshoot usage. "
    "Returns source URIs, sections, excerpts and character offsets for file_read. "
    "Hybrid retrieval falls back to text search without embeddings. Filters: language fr/en, domain user/admin/dev/architecture, "
    "kind documentation/decision/plan and source path prefix. Plans are prospective. Requires documentation_catalog too."
), effect_policy="read", concurrency_policy="safe", conversation_policy="short")
async def documentation_search(ctx: McpToolContext, query: str, language: str = "", domain: str = "",
                               kind: str = "", path_prefix: str = "", limit: int = 10) -> str:
    import json
    from . import documentation_service

    return json.dumps(await documentation_service.documentation_search(
        ctx.agent_id, query, language=language, domain=domain, kind=kind, path_prefix=path_prefix, limit=limit,
    ), ensure_ascii=False)


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"tools.errors.{key}"), **values)


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"tools.{key}", language), **values)


@mcp_tool(
    "search",
    description="Search the web through the local SearXNG engine.",
    effect_policy="read",
    concurrency_policy="safe",
)
async def search_web(ctx: McpToolContext, query: str) -> str:
    """Search the web."""
    from app.tools import search_tool

    return await search_tool.asearch_web(query, language=await context_language(ctx))


@mcp_tool(
    "galaris",
    name="tools_list",
    description=(
        "List authorized MCP functions and distinguish those present in this run from "
        "those requiring a new execution context, grouped by application tool."
    ),
)
async def list_mcp_tools(ctx: McpToolContext) -> str:
    """List and document available MCP functions grouped by application tool."""

    language = await context_language(ctx)
    try:
        groups = await list_agent_mcp_tools(ctx.agent_id)
        run_tool_names = ctx.resource("run_tool_names")
        mounted_names = (
            await cast(Callable[[], Awaitable[frozenset[str]]], run_tool_names)()
            if callable(run_tool_names) else None
        )
    except Exception as exc:
        logger.warning(
            "MCP list_mcp_tools failed (error_type={})",
            type(exc).__name__,
        )
        return _message(language, "list_failed")

    lines: list[str] = [_message(language, "list_heading"), ""]
    available_count = 0
    for group in groups:
        tools = [tool for tool in group.get("mcp_tools", []) if tool.get("enabled")]
        if not tools:
            continue

        header = f"## {group['tool_label']} (`{group['tool_code']}`)"
        lines.append(header)

        for tool in tools:
            available_count += 1
            availability = ""
            if mounted_names is not None:
                key = "present_in_run" if tool["name"] in mounted_names else "absent_from_run"
                availability = f" [{_message(language, key)}]"
            lines.append(f"• **{tool['name']}**{availability} — {tool['description']}")
        lines.append("")

    if available_count == 0:
        lines.append(f"_{_message(language, 'none_available')}_")
    else:
        lines.append(_message(language, "availability_hint"))
    return "\n".join(lines).rstrip()


def _resolve_token(auth: McpAuth, connection_params: Dict[str, Any]) -> Optional[str]:
    """Resolve a token with dynamic connection parameters taking priority."""
    if auth.param:
        value = connection_params.get(auth.param)
        if value:
            return str(value)

    if auth.token_static:
        return auth.token_static

    return None


def _build_auth_headers(
    auth: McpAuth,
    connection_params: Dict[str, Any],
) -> Dict[str, str]:
    """Build authentication headers for the configured auth type."""
    headers: Dict[str, str] = {}

    if auth.type == "none":
        return headers

    if auth.type == "basic":
        login = connection_params.get(auth.login_param, "")
        password = connection_params.get(auth.password_param, "")
        if not login or not password:
            raise ValueError(_error(
                "basic_auth_parameters_required",
                login_parameter=auth.login_param,
                password_parameter=auth.password_param,
            ))
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
        return headers

    token = _resolve_token(auth, connection_params)
    if not token:
        raise ValueError(_error(
            "auth_token_missing",
            auth_type=auth.type,
            parameter=auth.param,
            static_token_state=_error(
                "static_token_set" if auth.token_static else "static_token_absent"
            ),
        ))

    if auth.type == "bearer":
        headers["Authorization"] = f"Bearer {token}"
    elif auth.type == "header":
        headers[auth.header_name] = token

    return headers


def _inject_url_param(url: str, auth: McpAuth, connection_params: Dict[str, Any]) -> str:
    """Add the token to the query string when ``auth.url_param`` is set."""
    if not auth.url_param:
        return url

    token = _resolve_token(auth, connection_params)
    if not token:
        return url

    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    existing[auth.url_param] = [token]
    new_query = urlencode({k: v[0] for k, v in existing.items()})
    return urlunparse(parsed._replace(query=new_query))


def build_mcp_server(
    tool: Tool,
    connection_params: Optional[Dict[str, Any]] = None,
    disabled_functions: Optional[set[str]] = None,
    prefix_tools: bool = True,
) -> Any:
    """Build a native Pydantic AI MCP toolset from tool configuration.

    Function names are prefixed by tool code unless disabled. ``disabled_functions`` is a
    denylist; all other functions remain exposed by default.
    """
    if not tool.mcp:
        return None

    mcp: McpConfig = tool.mcp
    params: Dict[str, Any] = connection_params or {}

    try:
        auth_headers = _build_auth_headers(mcp.auth, params)
    except ValueError as e:
        raise ValueError(_error(
            "tool_configuration_error", code=tool.code, error=e
        )) from e

    try:
        headers = {
            **resolve_mapping_references(mcp.headers, params),
            **auth_headers,
        }
        url = resolve_connection_references(mcp.url or "", params).rstrip("/")
        env = resolve_mapping_references(mcp.env, params)
    except MissingConnectionReference as exc:
        raise ValueError(
            _error(
                "connection_reference_missing",
                parameter=exc.parameter,
            )
        ) from exc

    if headers:
        logger.info("Authentication headers for {}: {}", tool.code, list(headers.keys()))

    if mcp.auth.url_param and url:
        url = _inject_url_param(url, mcp.auth, params)

    if mcp.type == "sse":
        server = MCPToolset(url, headers=headers, max_retries=_MCP_TOOL_MAX_RETRIES)
    elif mcp.type == "http":
        server = MCPToolset(url, headers=headers, max_retries=_MCP_TOOL_MAX_RETRIES)
    elif mcp.type == "stdio":
        if not mcp.command:
            raise ValueError(_error(
                "tool_configuration_error",
                code=tool.code,
                error=_error("stdio_command_missing"),
            ))
        server = MCPToolset(
            StdioTransport(
                command=mcp.command,
                args=mcp.args or [],
                env=env or None,
            ),
            max_retries=_MCP_TOOL_MAX_RETRIES,
        )
    else:
        raise ValueError(_error(
            "tool_configuration_error",
            code=tool.code,
            error=render_prompt(t("tools.errors.unsupported_mcp_type"), type=mcp.type),
        ))

    if disabled_functions:
        from pydantic_ai import RunContext
        from pydantic_ai.tools import ToolDefinition

        blocked = set(disabled_functions)

        def filter_func(ctx: RunContext[Any], tool_def: ToolDefinition) -> bool:
            return tool_def.name not in blocked

        server = server.filtered(filter_func)

    if prefix_tools and tool.code:
        server = server.prefixed(tool.code)

    return server
