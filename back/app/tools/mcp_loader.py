"""Central loader for native and external MCP tools."""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, TypeVar, cast
from uuid import UUID, uuid4

from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.client.transports.http import StreamableHttpTransport
from fastmcp.client.transports.sse import SSETransport
from fastmcp.exceptions import ToolError
from fastmcp.prompts import Prompt
from fastmcp.resources.base import Resource
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.providers.proxy import ProxyProvider
from fastmcp.tools.base import Tool
from loguru import logger
from sqlalchemy import select

from app.agent.contracts import (
    RuntimeName,
    ToolConcurrencyPolicy,
    ToolEffectPolicy,
)
from app.tools.secrets import (
    resolve_connection_references,
    resolve_mapping_references,
)
from app.tools.tool_errors import (
    classify_tool_failure,
    exception_diagnostic,
    render_tool_failure,
    safe_trace,
)
from core.i18n import render_prompt, t, tr
from core.database import get_db
from core.params import runtime_settings

from .contracts import ToolCallRejectedError, current_tool_execution
from .execution_evidence import ExecutionEvidenceMiddleware

ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])


def native_tool_codes_for_connection(tool_code: str) -> frozenset[str]:
    """Return the native family identified directly by a Tool code."""

    return frozenset({tool_code}) if tool_code else frozenset()


def native_tool_codes_for_tool(tool: Any) -> frozenset[str]:
    """Return native families exposed by one concrete Tool configuration."""

    codes = set(native_tool_codes_for_connection(str(getattr(tool, "code", "") or "")))
    codes.discard("messenger")
    messenger = getattr(tool, "messenger", None)
    service = str(getattr(messenger, "service", "") or "")
    if service:
        from app.messenger import is_kind_enabled

        if is_kind_enabled(service):
            codes.add("messenger")
        else:
            codes.discard("messenger")
    return frozenset(codes)


@dataclass(frozen=True)
class McpToolContext:
    """Context injected by the loader into each native MCP tool.

    ``task_id`` is frozen when building the toolset and remains exact in both runtimes.
    """

    agent_id: int
    runtime: RuntimeName
    task_id: UUID | None = None
    resources: dict[str, Any] = field(default_factory=dict[str, Any])
    conversation_only: bool = False

    def resource(self, name: str) -> Any | None:
        """Return a server-resolved run resource never exposed to the model."""
        return self.resources.get(name)


async def context_language(ctx: McpToolContext) -> str:
    """Prefer the user language, preserving Task and conversation context."""
    from core.i18n import current_language

    conversation_language = getattr(ctx.resource("conversation_turn"), "language", None)
    if ctx.task_id is None:
        return await current_language(conversation_language)
    try:
        from app.task import task_service

        task = await task_service.get_by_id(ctx.task_id)
        raw_data = getattr(task, "data", None) if task is not None else None
        data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
        return await current_language(
            data.get("language") or conversation_language,
            user_id=task.requester_user_id if task is not None else None,
        )
    except RuntimeError:
        return await current_language(conversation_language)


@dataclass(frozen=True)
class McpToolDefinition:
    """Metadata attached by ``@mcp_tool``."""

    tool_code: str
    name: str
    description: str
    required_capabilities: frozenset[str]
    function: Callable[..., Any]
    conversation_policy: Literal["short", "deferred", "forbidden"] = "forbidden"
    task_enabled: bool = True
    timeout_seconds: float | None = None
    effect_policy: ToolEffectPolicy = "non_idempotent"
    concurrency_policy: ToolConcurrencyPolicy = "exclusive"
    available_when: Callable[[McpToolContext], Awaitable[bool]] | None = None


_CONVERSATION_TOOL_POLICIES: dict[str, Literal["short", "deferred"]] = {
    # Bounded web search is the direct fast path for current factual information.
    "search_web": "short",
    # Governed resource reads and bounded document updates remain available in conversation mode.
    **{
        name: "short"
        for name in (
            "file_list", "file_info", "file_search", "file_read", "file_create",
            "file_write", "file_append", "file_edit", "memory_remember", "memory_forget",
            "memory_summarize", "document_share",
        )
    },
    # Personal processes are inspected or started asynchronously.
    "process_list": "short",
    "process_get": "short",
    "conversation_process_start": "deferred",
    "process_list_runs": "short",
    "process_get_run": "short",
    # Messenger operations that stay bounded; media/file transfers remain forbidden.
    "messenger_room_send_message": "deferred",
    "messenger_send_message_to_user": "deferred",
    "messenger_list_rooms": "short",
    "messenger_room_history": "short",
    "messenger_search_users": "short",
    # Dedicated conversation control-plane functions.
    "conversation_task_submit": "deferred",
    "conversation_choice_resolve": "deferred",
    "conversation_task_list": "short",
    "conversation_task_status": "short",
    "conversation_task_pause": "deferred",
    "conversation_task_resume": "deferred",
    "conversation_task_retry": "deferred",
    "conversation_task_stop": "deferred",
}


def mcp_tool(
    tool_code: str,
    *,
    name: str | None = None,
    description: str = "",
    requires: tuple[
        Literal["voice_calling", "file_tools", "console_execution"], ...
    ] = (),
    conversation_policy: Literal["short", "deferred", "forbidden"] | None = None,
    task_enabled: bool = True,
    timeout_seconds: float | None = None,
    effect_policy: ToolEffectPolicy = "non_idempotent",
    concurrency_policy: ToolConcurrencyPolicy = "exclusive",
    available_when: Callable[[McpToolContext], Awaitable[bool]] | None = None,
) -> Callable[[ToolFunc], ToolFunc]:
    """Mark an ``mcp.py`` function as a native MCP tool.

    The decorated function takes ``ctx`` first; the loader injects it and hides it from the model.
    """

    def decorator(func: ToolFunc) -> ToolFunc:
        definition = McpToolDefinition(
            tool_code=tool_code,
            name=name or func.__name__,
            description=description or inspect.getdoc(func) or "",
            required_capabilities=frozenset(requires),
            conversation_policy=(
                conversation_policy
                or _CONVERSATION_TOOL_POLICIES.get(name or func.__name__, "forbidden")
            ),
            task_enabled=task_enabled,
            timeout_seconds=timeout_seconds,
            effect_policy=effect_policy,
            concurrency_policy=concurrency_policy,
            available_when=available_when,
            function=func,
        )
        setattr(func, "__galaris_mcp_tool__", definition)
        return func

    return decorator


def execution_policy_for_tool(
    name: str,
) -> tuple[ToolEffectPolicy, ToolConcurrencyPolicy]:
    """Return explicit native metadata, denying concurrency for unknown tools."""

    normalized = name.strip()
    for definition in load_mcp_tools():
        if definition.name == normalized:
            return definition.effect_policy, definition.concurrency_policy
    return "non_idempotent", "exclusive"


class _ResilientProxyProvider(ProxyProvider):
    """Proxy provider tolerant of temporarily unavailable external MCP servers."""

    def __init__(
        self,
        *args: Any,
        disabled_functions: set[str] | None = None,
        discovery_source: str | None = None,
        discovery_failures: set[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._disabled_functions = disabled_functions
        self._discovery_source = discovery_source
        self._discovery_failures = discovery_failures

    async def _list_tools(self) -> Sequence[Tool]:
        try:
            tools = await super()._list_tools()
            if self._disabled_functions:
                blocked = self._disabled_functions
                tools = [tool for tool in tools if tool.name not in blocked]
            return tools
        except Exception as exc:
            if self._discovery_source and self._discovery_failures is not None:
                self._discovery_failures.add(self._discovery_source)
            logger.warning(
                "MCP proxy _list_tools skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []

    async def _list_resources(self) -> Sequence[Resource]:
        try:
            return await super()._list_resources()
        except Exception as exc:
            logger.warning(
                "MCP proxy _list_resources skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []

    async def _list_resource_templates(self) -> Sequence[ResourceTemplate]:
        try:
            return await super()._list_resource_templates()
        except Exception as exc:
            logger.warning(
                "MCP proxy _list_resource_templates skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []

    async def _list_prompts(self) -> Sequence[Prompt]:
        try:
            return await super()._list_prompts()
        except Exception as exc:
            logger.warning(
                "MCP proxy _list_prompts skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []


def _module_names() -> list[str]:
    try:
        import modules
    except ImportError:
        logger.warning("Could not import modules.py. No MCP tools will be loaded.")
        return []
    return [str(module_name) for module_name in modules.MODULES]


@lru_cache(maxsize=1)
def load_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Load decorated tools from every declared module's ``mcp.py`` file."""
    definitions: list[McpToolDefinition] = []
    for module_name in _module_names():
        mcp_module_name = f"{module_name}.mcp"
        try:
            mcp_module = importlib.import_module(mcp_module_name)
            logger.info("Loaded MCP tools from {}", mcp_module_name)
        except ImportError:
            continue

        for value in vars(mcp_module).values():
            definition = getattr(value, "__galaris_mcp_tool__", None)
            if isinstance(definition, McpToolDefinition):
                definitions.append(definition)
    return tuple(definitions)


def mcp_tools_by_tool_code() -> dict[str, list[McpToolDefinition]]:
    grouped: dict[str, list[McpToolDefinition]] = {}
    for definition in load_mcp_tools():
        grouped.setdefault(definition.tool_code, []).append(definition)
    return grouped


def mcp_tool_names_by_tool_code() -> dict[str, tuple[str, ...]]:
    return {
        tool_code: tuple(definition.name for definition in definitions)
        for tool_code, definitions in mcp_tools_by_tool_code().items()
    }


def _public_signature(func: Callable[..., Any]) -> inspect.Signature:
    signature = inspect.signature(func)
    parameters = list(signature.parameters.values())
    if parameters and parameters[0].name in {"ctx", "context"}:
        parameters = parameters[1:]
    return signature.replace(parameters=parameters)


def _wrap_tool(definition: McpToolDefinition, ctx: McpToolContext) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(definition.function)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # ``ctx.task_id`` is frozen when the toolset is built and needs no call-time lookup.
        language: str | None = None
        execution = current_tool_execution()
        if execution is not None:
            execution.entered = True
        try:
            from core.database import get_db_session

            timeout_seconds = (
                definition.timeout_seconds
                if definition.timeout_seconds is not None
                else runtime_settings.TASK_TOOL_TIMEOUT_SECONDS
            )
            # Each parallel native call owns its transaction. The asyncio task must not
            # inherit and concurrently use the scheduler or another tool's AsyncSession.
            async with get_db_session():
                from app.agent import effective_capabilities

                capabilities = await effective_capabilities(ctx.agent_id, ctx.runtime)
                if "execute" not in capabilities or not definition.required_capabilities <= capabilities:
                    raise ToolCallRejectedError("The Harness policy no longer permits this tool call.")
                language = await context_language(ctx)
                async with asyncio.timeout(timeout_seconds):
                    visible = await list_enabled_native_mcp_definitions(
                        ctx.agent_id, runtime=ctx.runtime, conversation_only=ctx.conversation_only,
                        allowed_tool_names={definition.name}, resources=ctx.resources,
                    )
                    if not visible:
                        raise ToolCallRejectedError("This tool is no longer authorized or available in this execution.")
                    result = definition.function(ctx, *args, **kwargs)
                    if inspect.isawaitable(result):
                        result = await result
                    bound = inspect.signature(definition.function).bind(ctx, *args, **kwargs)
                    arguments = {
                        key: value for key, value in bound.arguments.items() if key != "ctx"
                    }
                    from .resource_effects import record_tool_resources

                    await record_tool_resources(ctx, definition.name, arguments, result)
                    return result
        except Exception as exc:
            if isinstance(exc, ToolCallRejectedError) and execution is not None:
                execution.outcome = "rejected"
            failure = classify_tool_failure(exc)
            error_reference = uuid4().hex[:12]
            error_trace = safe_trace(exc)
            log = logger.bind(
                tool_name=definition.name,
                tool_code=definition.tool_code,
                error_kind=failure.kind,
                error_type=failure.error_type,
                error_reference=error_reference,
                error_trace=error_trace,
            )
            log.log(
                "WARNING" if failure.kind == "actionable" else "ERROR",
                "MCP tool {} failed (error_kind={}, error_type={}, error_reference={}, trace={})",
                definition.name,
                failure.kind,
                failure.error_type,
                error_reference,
                error_trace,
            )
            if language is None:
                from core.i18n import default_language

                language = default_language()
            message = render_tool_failure(
                tool_name=definition.name,
                failure=failure,
                language=language,
                reference=error_reference,
            )
            from core.failure_journal import FailureEvent, record_failure_event

            # The tool transaction has rolled back. Persist its original diagnostic
            # separately before FastMCP replaces the exception with model-safe text.
            await record_failure_event(FailureEvent(
                idempotency_key=f"native-tool:{error_reference}",
                kind="tool",
                phase="tool_execution",
                error_type=failure.error_type,
                error_code=failure.kind,
                error_message=message,
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
                driver_code=ctx.runtime,
                tool_name=definition.name,
                trace={"native_failure": {
                    "reference": error_reference,
                    "exceptions": exception_diagnostic(exc),
                }},
            ))
            # FastMCP validates successful return values against the function's annotated
            # output schema. Returning this message as a string breaks every tool annotated
            # with a structured result and masks the original recoverable tool error behind
            # a protocol validation failure. ToolError produces a proper MCP error result.
            if execution is not None:
                from fastmcp.tools import ToolResult

                return ToolResult(content=message, is_error=True)
            raise ToolError(message) from exc

    wrapper.__name__ = definition.name
    wrapper.__doc__ = definition.description
    wrapper.__signature__ = _public_signature(definition.function)  # type: ignore[attr-defined]
    return wrapper


def add_galaris_tools(
    mcp: Any,
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    enabled_tool_codes: set[str] | None = None,
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
) -> None:
    """Register discovered native tools on a FastMCP server."""
    from app.agent import resolve_tool_profile

    profile = resolve_tool_profile(runtime)
    ctx = McpToolContext(
        agent_id=agent_id,
        runtime=runtime,
        task_id=task_id,
        resources=dict(resources or {}),
    )
    for definition in load_mcp_tools():
        if enabled_tool_codes is not None and definition.tool_code not in enabled_tool_codes:
            continue
        if not profile.supports(definition.required_capabilities):
            continue
        # Contextual tools are mounted by the asynchronous, authorized run projection.
        if definition.available_when is not None:
            continue
        mcp.tool()(_wrap_tool(definition, ctx))
        if isinstance(mcp, _MediaFilteredFastMCP):
            mcp.native_execution_names.add(definition.name)


def build_galaris_fastmcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    enabled_tool_codes: set[str] | None = None,
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
) -> FastMCP:
    """Build a complete or filtered native Galaris FastMCP server."""
    mcp: FastMCP = _MediaFilteredFastMCP(f"Galaris tools — Agent {agent_id}", agent_id=agent_id)
    add_galaris_tools(
        mcp,
        agent_id,
        runtime=runtime,
        enabled_tool_codes=enabled_tool_codes,
        task_id=task_id,
        resources=resources,
    )
    return mcp


async def get_enabled_integrated_tool_codes(agent_id: int) -> set[str]:
    """Return native tool codes with an active connection for the agent."""
    from app.connection import facade as connection_service
    from app.tools import tool_service

    known_codes = set(mcp_tools_by_tool_code())
    enabled: set[str] = set()
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool:
            enabled.update(
                native_tool_codes_for_tool(tool) & known_codes
            )
    return enabled


async def get_disabled_internal_function_names(agent_id: int) -> set[str]:
    """Return native functions disabled across the agent's active connections."""
    from app.connection import facade as connection_service
    from app.tools import tool_service

    known_codes = set(mcp_tools_by_tool_code())
    names: set[str] = set()
    system_codes: set[str] = set()
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool and native_tool_codes_for_tool(tool) & known_codes:
            names |= await connection_service.get_disabled_function_names(connection)
            if not tool.can_disable:
                system_codes.update(native_tool_codes_for_tool(tool))
    from app.llm import available_media_functions

    media_names = {definition.name for definition in load_mcp_tools() if definition.tool_code == "multimedia"}
    names |= media_names - await available_media_functions(agent_id)
    # Stale or invalid overrides on another Tool cannot disable a system function.
    system_names = {
        definition.name for definition in load_mcp_tools()
        if definition.tool_code in system_codes
    }
    return names - system_names


async def list_enabled_native_mcp_definitions(
    agent_id: int,
    *,
    runtime: RuntimeName,
    allowed_tool_names: Collection[str] | None = None,
    conversation_only: bool = False,
    resources: dict[str, Any] | None = None,
) -> tuple[McpToolDefinition, ...]:
    """Return the exact native function definitions visible to an agent.

    This is the shared authorization projection used by both the MCP server and agent-facing
    capability advertising. Keeping it here prevents prompts from naming an inactive,
    runtime-incompatible, connection-disabled, or task-scoped function.
    """
    from app.agent import effective_tool_profile

    enabled_tool_codes = await get_enabled_integrated_tool_codes(agent_id)
    if conversation_only:
        from app.tools.models import Tool

        checked_tools = (
            await get_db().scalars(
                select(Tool).where(Tool.conversation_enabled.is_(True))
            )
        ).all()
        conversation_codes: set[str] = set()
        for tool in checked_tools:
            conversation_codes.add(tool.code)
            messenger_config = tool.messenger_config or {}
            service = str(messenger_config.get("service") or "")
            if service:
                from app.messenger import is_kind_enabled

                if is_kind_enabled(service):
                    conversation_codes.add("messenger")
        # Ending a live call is a safety/control action, not optional foreground work.
        # Keep it reachable whenever the agent has the Voice capability, even when the
        # administrator did not enable the rest of that Tool for short conversations.
        if "voice" in enabled_tool_codes:
            conversation_codes.add("voice")
        enabled_tool_codes &= conversation_codes
    disabled_names = await get_disabled_internal_function_names(agent_id)
    allowed_names = frozenset(allowed_tool_names) if allowed_tool_names is not None else None
    profile = await effective_tool_profile(agent_id, runtime)
    definitions = (
        definition
        for definition in load_mcp_tools()
        if definition.tool_code in enabled_tool_codes
        and definition.name not in disabled_names
        and profile.supports(definition.required_capabilities)
        and (not conversation_only or definition.conversation_policy != "forbidden")
        and (conversation_only or definition.task_enabled)
        and (allowed_names is None or definition.name in allowed_names)
    )
    ctx = McpToolContext(
        agent_id=agent_id, runtime=runtime, resources=dict(resources or {}),
        conversation_only=conversation_only,
    )
    visible = [
        definition for definition in definitions
        if definition.available_when is None or await definition.available_when(ctx)
    ]
    return tuple(sorted(visible, key=lambda item: (item.tool_code, item.name)))


async def execute_native_mcp_tool(
    agent_id: int,
    *,
    runtime: RuntimeName,
    task_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
    resources: dict[str, Any] | None = None,
) -> Any:
    """Execute one exact authorized native tool without involving a model.

    This deterministic path reuses the model-facing MCP projection's authorization and
    effect recorder, so a server-owned recovery cannot bypass either boundary.
    """

    definitions = await list_enabled_native_mcp_definitions(
        agent_id,
        runtime=runtime,
        allowed_tool_names={tool_name},
    )
    definition = next(
        (item for item in definitions if item.name == tool_name),
        None,
    )
    if definition is None:
        raise PermissionError(f"Native tool {tool_name!r} is not authorized for this agent.")
    ctx = McpToolContext(
        agent_id=agent_id,
        runtime=runtime,
        task_id=task_id,
        resources=dict(resources or {}),
    )
    return await _wrap_tool(definition, ctx)(**arguments)


async def build_agent_galaris_fastmcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
    allowed_tool_names: Collection[str] | None = None,
    conversation_only: bool = False,
) -> FastMCP:
    """Build native MCP filtered by active connections and disabled functions."""
    resolved_resources = dict(resources or {})
    definitions = await list_enabled_native_mcp_definitions(
        agent_id,
        runtime=runtime,
        allowed_tool_names=allowed_tool_names,
        conversation_only=conversation_only,
        resources=resolved_resources,
    )
    if (
        any(definition.tool_code == "console" for definition in definitions)
        and "console" not in resolved_resources
    ):
        from app.console.console_service import build_run_resource

        resolved_resources["console"] = await build_run_resource(agent_id)
    ctx = McpToolContext(
        agent_id=agent_id,
        runtime=runtime,
        task_id=task_id,
        resources=resolved_resources,
        conversation_only=conversation_only,
    )
    mcp: FastMCP = _MediaFilteredFastMCP(f"Galaris tools — Agent {agent_id}", agent_id=agent_id)
    for definition in definitions:
        mcp.tool()(_wrap_tool(definition, ctx))
        mcp.native_execution_names.add(definition.name)
    # Keep the registrations available for live reconfiguration. list_tools and the
    # call-time guard consult current profile/connection rights on every access.
    from app.agent import resolve_tool_profile
    present = {definition.name for definition in definitions}
    for definition in load_mcp_tools():
        if (definition.tool_code == "multimedia" and definition.name not in present
                and resolve_tool_profile(runtime).supports(definition.required_capabilities)
                and (allowed_tool_names is None or definition.name in allowed_tool_names)
                and not conversation_only):
            mcp.tool()(_wrap_tool(definition, ctx))
            mcp.native_execution_names.add(definition.name)
    return mcp


class _MediaFilteredFastMCP(FastMCP):
    def __init__(self, name: str, *, agent_id: int) -> None:
        super().__init__(name)  # pyright: ignore[reportUnknownMemberType]
        self.media_agent_id = agent_id
        self.native_execution_names: set[str] = set()
        self.add_middleware(ExecutionEvidenceMiddleware(self.native_execution_names))

    async def list_tools(self, *, run_middleware: bool = True) -> Sequence[Tool]:
        tools = await super().list_tools(run_middleware=run_middleware)
        from core.database import get_db_session

        media = {definition.name for definition in load_mcp_tools() if definition.tool_code == "multimedia"}
        if not any(tool.name in media for tool in tools):
            return tools
        try:
            get_db()
        except RuntimeError:
            async with get_db_session():
                enabled = await get_enabled_integrated_tool_codes(self.media_agent_id)
                disabled = await get_disabled_internal_function_names(self.media_agent_id)
        else:
            enabled = await get_enabled_integrated_tool_codes(self.media_agent_id)
            disabled = await get_disabled_internal_function_names(self.media_agent_id)
        return [tool for tool in tools if tool.name not in media or (
            "multimedia" in enabled and tool.name not in disabled
        )]


def _resolve_auth_headers(mcp_config: Any, params: dict[str, Any]) -> dict[str, str]:
    from app.tools.mcp import _build_auth_headers  # pyright: ignore[reportPrivateUsage]

    headers = resolve_mapping_references(mcp_config.headers or {}, params)
    headers.update(_build_auth_headers(mcp_config.auth, params))
    return headers


def _external_transport(tool: Any, params: dict[str, Any]) -> Any:
    from app.tools.mcp import _inject_url_param  # pyright: ignore[reportPrivateUsage]

    mcp = tool.mcp
    if mcp.type == "sse":
        url = resolve_connection_references(mcp.url or "", params).rstrip("/")
        if mcp.auth.url_param:
            url = _inject_url_param(url, mcp.auth, params)
        return SSETransport(url, headers=_resolve_auth_headers(mcp, params))
    if mcp.type == "http":
        url = resolve_connection_references(mcp.url or "", params).rstrip("/")
        if mcp.auth.url_param:
            url = _inject_url_param(url, mcp.auth, params)
        return StreamableHttpTransport(url, headers=_resolve_auth_headers(mcp, params))
    if mcp.type == "stdio":
        if not mcp.command:
            raise ValueError(t("tools.errors.stdio_command_missing"))
        return StdioTransport(
            command=mcp.command,
            args=mcp.args or [],
            env=resolve_mapping_references(mcp.env or {}, params) or None,
        )
    raise ValueError(
        render_prompt(
            t("tools.errors.unsupported_mcp_type"),
            type=mcp.type,
        )
    )


async def build_agent_mcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
    discovery_failures: set[str] | None = None,
    conversation_only: bool = False,
    allowed_tool_names: Collection[str] | None = None,
) -> FastMCP:
    """Build an agent's aggregate native and external MCP server."""
    from app.connection import facade as connection_service
    from app.tools import tool_service

    mcp: FastMCP = FastMCP(f"Galaris — Agent {agent_id}")

    async def run_tool_names() -> frozenset[str]:
        # Query this run's mounted server, not a fresh agent-wide configuration.
        # This includes deferred tools and namespaced external MCP tools.
        return frozenset(tool.name for tool in await mcp.list_tools())

    galaris_mcp = await build_agent_galaris_fastmcp(
        agent_id,
        runtime=runtime,
        task_id=task_id,
        resources={**(resources or {}), "run_tool_names": run_tool_names},
        allowed_tool_names=allowed_tool_names,
        conversation_only=conversation_only,
    )
    mcp.mount(galaris_mcp)

    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if not tool or not tool.mcp:
            continue
        if conversation_only and not tool.conversation_enabled:
            continue
        try:
            _, params = await connection_service.get_params_as_dict(
                connection, decrypt_passwords=True
            )
            disabled_functions = await connection_service.get_disabled_function_names(connection)
            proxy = FastMCP(tool.code)
            proxy.add_provider(_ResilientProxyProvider(
                Client(_external_transport(tool, params)).new,
                disabled_functions=disabled_functions,
                discovery_source=tool.code,
                discovery_failures=discovery_failures,
            ))
            mcp.mount(proxy, namespace=tool.code)
            logger.info("MCP loader: proxy mounted {} ({})", tool.code, tool.mcp.type)
        except Exception as exc:
            logger.warning(
                "MCP loader: proxy {} skipped (error_type={})",
                tool.code,
                type(exc).__name__,
            )
    return mcp


async def get_agent_mcp_servers(agent_id: int) -> list[Any]:
    """Return external Pydantic AI MCP servers connected to an agent."""
    from app.connection import facade as connection_service
    from app.tools import tool_service
    from app.tools.mcp import build_mcp_server

    servers: list[Any] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if not tool or not tool.mcp:
            continue
        try:
            _, params = await connection_service.get_params_as_dict(
                connection, decrypt_passwords=True
            )
            server = build_mcp_server(
                tool,
                connection_params=params,
                disabled_functions=await connection_service.get_disabled_function_names(connection),
            )
            if server:
                servers.append(server)
        except Exception as exc:
            logger.error(
                "MCP loader: external server {} skipped (error_type={})",
                tool.code,
                type(exc).__name__,
            )
    return servers


async def list_external_mcp_functions(tool: Any, params: dict[str, Any]) -> list[tuple[str, str]]:
    """List functions exposed by an external MCP tool without prefixes."""
    from app.tools.mcp import build_mcp_server

    server = build_mcp_server(tool, params, prefix_tools=False)
    if not server:
        raise ValueError(await tr("tools.errors.server_creation_failed"))
    async with server:
        tools = await server.list_tools()
    return [(tool.name, tool.description or "") for tool in tools]


async def list_internal_mcp_functions(
    agent_id: int,
    tool_code: str,
    *,
    runtime: RuntimeName = "internal",
    tool: Any | None = None,
) -> list[tuple[str, str]]:
    """List native functions declared by a built-in tool."""
    mcp = build_galaris_fastmcp(
        agent_id,
        runtime=runtime,
        enabled_tool_codes=set(
            native_tool_codes_for_tool(tool)
            if tool is not None
            else native_tool_codes_for_connection(tool_code)
        ),
    )
    tools = await mcp.list_tools()
    disabled = await get_disabled_internal_function_names(agent_id)
    return [(tool.name, tool.description or "") for tool in tools if tool.name not in disabled]


async def list_agent_mcp_tools(agent_id: int) -> list[dict[str, Any]]:
    """Return an agent's MCP catalog grouped by application tool."""
    from app.agent import agent_service, effective_tool_profile, validate_agent_driver
    from app.connection import facade as connection_service
    from app.tools import tool_service

    agent = await agent_service.get(agent_id)
    runtime: RuntimeName = validate_agent_driver(
        getattr(agent, "agent_driver", None),
        require_available=False,
    )
    profile = await effective_tool_profile(agent_id, runtime)
    connections = await connection_service.get_connections_by_agent(agent_id)
    connections_by_tool = {connection.tool_id: connection for connection in connections}
    native_by_tool = mcp_tools_by_tool_code()
    from app.llm import available_media_functions
    media_functions: frozenset[str] = await available_media_functions(agent_id) if "multimedia" in native_by_tool else frozenset()
    records = await tool_service.get_all_tool_records()

    groups: list[dict[str, Any]] = []
    for record in records:
        tool = tool_service._to_internal(record)  # pyright: ignore[reportPrivateUsage]
        native_definitions = [
            definition
            for native_code in sorted(native_tool_codes_for_tool(tool))
            for definition in native_by_tool.get(native_code, [])
        ]
        has_native = bool(native_definitions)
        has_external = bool(tool.mcp)
        if not (has_native or has_external):
            continue

        connection = connections_by_tool.get(record.id)
        active = bool(connection and connection.active)
        disabled: set[str] = set()
        if connection is not None:
            disabled = await connection_service.get_disabled_function_names(connection)

        mcp_tools: list[dict[str, Any]] = []
        error = ""
        if has_native:
            for definition in native_definitions:
                if getattr(definition, "tool_code", None) == "multimedia" and definition.name not in media_functions:
                    continue
                runtime_supported = profile.supports(definition.required_capabilities)
                mcp_tools.append({
                    "name": definition.name,
                    "description": definition.description,
                    "enabled": active and runtime_supported and definition.name not in disabled,
                })
        if has_external and active and connection is not None:
            try:
                _, params = await connection_service.get_params_as_dict(
                    connection, decrypt_passwords=True
                )
                for name, description in await list_external_mcp_functions(tool, params):
                    mcp_tools.append({
                        "name": name,
                        "description": description,
                        "enabled": name not in disabled,
                    })
            except Exception:
                error = t("tools.introspection_failed")

        groups.append({
            "tool_id": record.id,
            "tool_code": record.code,
            "tool_label": record.label,
            "tool_description": record.description or "",
            "connection_id": connection.id if connection is not None else None,
            "active": active,
            "source": (
                "mixed"
                if has_native and has_external
                else "native" if has_native else "external"
            ),
            "runtime": runtime,
            "error": error,
            "mcp_tools": sorted(mcp_tools, key=lambda item: cast(str, item["name"])),
        })
    return sorted(groups, key=lambda item: cast(str, item["tool_code"]))
