"""Central loader for native and external MCP tools."""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
import weakref
from collections.abc import Awaitable, Callable, Collection, Sequence
from contextvars import Context, ContextVar
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast
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
from fastmcp.tools import FunctionTool, ToolResult
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec
from loguru import logger
from mcp.types import ToolAnnotations
from pydantic import JsonValue, PrivateAttr

from app.agent.contracts import (
    RuntimeName,
    ToolConcurrencyPolicy,
    ToolEffectPolicy,
)
from app.agent import EffectDescriptorV1
from app.services.secrets import (
    resolve_connection_references,
    resolve_mapping_references,
)
from app.services.tool_errors import (
    classify_tool_failure,
    exception_diagnostic,
    render_tool_failure,
    safe_trace,
)
from core.i18n import render_prompt, t, tr
from core.database import get_db
from core.params import runtime_settings

from .contracts import (MANAGEMENT_SCOPE_OPTIONS, ScopePreflightRejected, ToolArgumentsRejectedError, ToolCallRejectedError,
                        ToolPermissionRejectedError, current_tool_execution)
from .management_scope import EXECUTION_INSPECTION_SCOPE_SERVICE
from .execution_evidence import ExecutionEvidenceMiddleware
from .mandatory_services import (
    AGENT_DISCOVERY_TOOLS, CONVERSATION_PROCESS_TOOLS, CONVERSATION_TASK_TOOLS,
    SERVICE_DISCOVERY_TOOLS, SPECIALIST_MEDIA_TOOLS, VOICE_TOOLS,
)
from .mcp_presentation import MCP_APP_EXTENSION, McpPresentation, McpPresentationSink, McpTable, app_tool_visible_to
from .tool_arguments import ToolArgumentsMiddleware
from .schemas import ConversationToolSource, McpConfig, Service as ServiceConfiguration

ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])

if TYPE_CHECKING:
    from app.connection.facade import ActiveConnectionRef


async def resolve_live_connection(agent_id: int, connection_id: int, service_id: int,
                                  *, function_name: str = "", conversation_only: bool = False) -> tuple[ServiceConfiguration, dict[str, Any], set[str]]:
    """Read a fresh detached snapshot before external MCP discovery or execution.

    Each runtime callback owns a short database branch. Borrowing the run's
    contextual session would keep its transaction open across external I/O and
    share an AsyncSession between parallel tool discoveries.
    """
    from core.database import get_db_session

    async def read() -> tuple[ServiceConfiguration, dict[str, Any], set[str]]:
        async with get_db_session():
            return await _resolve_live_connection(agent_id, connection_id, service_id,
                function_name=function_name, conversation_only=conversation_only)

    return await asyncio.create_task(read())


async def _resolve_live_connection(agent_id: int, connection_id: int, service_id: int,
                                   *, function_name: str, conversation_only: bool) -> tuple[ServiceConfiguration, dict[str, Any], set[str]]:
    from app.connection import facade as connections
    from . import service

    connection = await connections.get_connection(connection_id)
    if connection is None or not connection.active or connection.agent_id != agent_id or connection.service_id != service_id:
        raise PermissionError("The external MCP connection is inactive or has changed.")
    tool = await service.get_service_by_id(service_id)
    if tool is None or tool.mcp is None:
        raise PermissionError("The external MCP Tool is no longer available in this context.")
    if conversation_only:
        allowed = conversation_tool_names(tool, source="external")
        if not allowed or (function_name and function_name not in allowed):
            raise PermissionError("The external MCP Tool is no longer available in this context.")
    disabled = await connections.get_disabled_function_names(connection)
    if function_name and function_name in disabled:
        raise PermissionError("The external MCP function has been revoked.")
    _, params = await connections.get_params_as_dict(connection_id)
    return tool, params, disabled


def native_service_codes_for_connection(service_code: str) -> frozenset[str]:
    """Return the native family identified directly by a Service code."""

    return frozenset({service_code}) if service_code else frozenset()


def native_service_codes_for_service(tool: Any) -> frozenset[str]:
    """Return native families exposed by one concrete Service configuration."""

    codes = set(native_service_codes_for_connection(str(getattr(tool, "code", "") or "")))
    codes.difference_update({"messenger", "mail", "calendar", "rest"})
    if getattr(tool, "rest", getattr(tool, "rest_config", None)) is not None:
        codes.add("rest")
    if getattr(tool, "code", "") == "calendar":
        codes.add("calendar")
    if getattr(tool, "mail", getattr(tool, "mail_config", None)) is not None:
        codes.add("mail")
    if getattr(tool, "calendar", getattr(tool, "calendar_config", None)) is not None:
        codes.add("calendar")
    messenger = getattr(tool, "messenger", getattr(tool, "messenger_config", None))
    service = str((cast(dict[str, Any], messenger).get("service") if isinstance(messenger, dict) else getattr(messenger, "service", "")) or "")
    if service:
        from app.messenger import is_kind_enabled

        if is_kind_enabled(service):
            codes.add("messenger")
        else:
            codes.discard("messenger")
    return frozenset(codes)


def has_function_permissions(tool: object) -> bool:
    """Whether a public Service or runtime configuration exposes governed functions."""
    return bool(getattr(tool, "mcp_config", getattr(tool, "mcp", None))) or bool(
        native_service_codes_for_service(tool) & mcp_tools_by_service_code().keys())


async def native_service_codes_for_agent_connection(tool: Any, connection_id: int) -> frozenset[str]:
    codes = native_service_codes_for_service(tool)
    if tool.code == "chat" and "messenger" in codes:
        from app.messenger import is_messenger_connection_active

        if not await is_messenger_connection_active(connection_id):
            return codes - {"messenger"}
    return codes


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

    service_code: str
    name: str
    description: str
    required_capabilities: frozenset[str]
    function: Callable[..., Any]
    conversation_policy: Literal["short", "deferred", "forbidden"] | None = None
    task_enabled: bool = True
    timeout_seconds: float | None = None
    effect_policy: ToolEffectPolicy = "non_idempotent"
    concurrency_policy: ToolConcurrencyPolicy = "exclusive"
    available_when: Callable[[McpToolContext], Awaitable[bool]] | None = None
    approval: Literal["enabled", "ask"] = "ask"
    default_blocked: bool = False
    approval_reason: str = "Unclassified native action"
    authorization_boundary: Literal["native", "prepared"] = "native"
    authorization_preflight: Callable[[McpToolContext, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None
    effect_descriptor: EffectDescriptorV1 | None = None
    execution_inspection: bool = False

    @property
    def management_scope_service(self) -> str | None:
        if self.execution_inspection:
            return EXECUTION_INSPECTION_SCOPE_SERVICE
        return self.service_code if self.service_code in MANAGEMENT_SCOPE_OPTIONS else None

    @property
    def default_state(self) -> Literal["disabled", "enabled", "ask"]:
        return "disabled" if self.default_blocked else self.approval


# Execution classification is independent of Service eligibility.
_CONVERSATION_TOOL_POLICIES: dict[str, Literal["short", "deferred"]] = {
    # Read-only colleague discovery does not require a background Task.
    "agent_list": "short",
    "agent_get": "short",
    "team_list": "short",
    "team_members": "short",
    # Bounded web search is the direct fast path for current factual information.
    "search_web": "short",
    # Classify bounded tool calls independently of the Service's conversation allowlist.
    **{
        name: "short"
        for name in (
            "file_list", "file_info", "file_search", "file_read", "file_create",
            "file_write", "file_append", "file_edit", "file_rename", "memory_remember", "memory_forget",
            "memory_summarize", "memory_upcoming", "document_share", "document_sharing",
        )
    },
    # Personal processes are inspected or started asynchronously.
    "process_start_conversation": "deferred",
    # Messenger operations retain their exact destination and action permissions.
    "messenger_room_send_message": "deferred",
    "messenger_send_message_to_user": "deferred",
    "messenger_send_audio_message": "deferred",
    "messenger_room_send_file": "deferred",
    "messenger_send_file_to_user": "deferred",
    "messenger_list_rooms": "short",
    "messenger_room_history": "short",
    "messenger_search_users": "short",
    # Dedicated conversation control-plane functions.
    "chat_choice_resolve": "deferred",
    "task_list": "short",
    "task_pause": "deferred",
    "task_resume": "deferred",
}


# Keyed by the concrete Service, including the native functions supplied by its protocols.
BUILTIN_CONVERSATION_TOOLS: dict[str, frozenset[str]] = {
    "galaris": frozenset({
        "documentation_catalog", "documentation_search",
    }),
    "agent": frozenset((*AGENT_DISCOVERY_TOOLS, "agent_team_list")),
    "contact": frozenset({"contact_list", "contact_get"}),
    "task": frozenset(CONVERSATION_TASK_TOOLS),
    "process": frozenset(CONVERSATION_PROCESS_TOOLS),
    "service": frozenset({"services_list", "service_connection_list"}),
    "topic": frozenset({"topic_list", "topic_items_list"}),
    "memory": frozenset({"memory_remember", "memory_forget", "memory_summarize", "memory_upcoming"}),
    "document": frozenset({"document_show", "document_sharing", "document_share"}),
    "skills": frozenset({"skills_list", "skill_read"}),
    "file_sharing": frozenset({
        "file_schemes", "file_list", "file_info", "file_search", "file_read", "dataset_query",
    }),
    "calendar": frozenset({"calendar_list", "calendar_events"}),
    "chat": frozenset({
        "chat_screenshot", "chat_repository_show", "chat_choice_resolve", *VOICE_TOOLS,
        "messenger_room_send_message", "messenger_send_message_to_user", "messenger_list_rooms",
        "messenger_room_history", "messenger_search_users", "messenger_send_audio_message",
        "messenger_room_send_file", "messenger_send_file_to_user",
    }),
    "browser": frozenset({"search_web"}),
    "multimedia": frozenset({"image_read", "audio_read", "audio_transcribe"}),
}


def conversation_tool_names(service: ServiceConfiguration, *, source: ConversationToolSource) -> Collection[str]:
    from .assertions import service_can_edit

    if not service.can_disable or not service_can_edit(service.code):
        return BUILTIN_CONVERSATION_TOOLS.get(service.code, ()) if source == "native" else ()
    return service.conversation_tools.get(source, ())


def mcp_tool(
    service_code: str,
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
    approval: Literal["enabled", "ask"] = "ask",
    default_blocked: bool = False,
    approval_reason: str = "Unclassified native action",
    authorization_boundary: Literal["native", "prepared"] = "native",
    authorization_preflight: Callable[[McpToolContext, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    effect_descriptor: EffectDescriptorV1 | None = None,
    execution_inspection: bool = False,
) -> Callable[[ToolFunc], ToolFunc]:
    """Mark an ``mcp.py`` function as a native MCP tool.

    The decorated function takes ``ctx`` first; the loader injects it and hides it from the model.
    """

    def decorator(func: ToolFunc) -> ToolFunc:
        definition = McpToolDefinition(
            service_code=service_code,
            name=name or func.__name__,
            description=description or inspect.getdoc(func) or "",
            required_capabilities=frozenset(requires),
            conversation_policy=(
                conversation_policy
                or _CONVERSATION_TOOL_POLICIES.get(name or func.__name__)
            ),
            task_enabled=task_enabled,
            timeout_seconds=timeout_seconds,
            effect_policy=effect_policy,
            concurrency_policy=concurrency_policy,
            available_when=available_when,
            approval=approval,
            default_blocked=default_blocked,
            approval_reason=approval_reason,
            authorization_boundary=authorization_boundary,
            authorization_preflight=authorization_preflight,
            effect_descriptor=effect_descriptor,
            execution_inspection=execution_inspection,
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
    if normalized == "task_work_update":
        from .legacy_names import canonical_service_call

        normalized, _ = canonical_service_call(normalized, {})
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
        live_connection: tuple[int, int, int, bool] | None = None,
        mcp_apps: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._disabled_functions = disabled_functions
        self._discovery_source = discovery_source
        self._discovery_failures = discovery_failures
        self._live_connection = live_connection
        self._mcp_apps = mcp_apps

    async def _live_tool_policy(self) -> tuple[set[str], Collection[str] | None]:
        if self._live_connection is None:
            return self._disabled_functions or set(), None
        from .live_external import resolve_live_connection

        agent_id, connection_id, service_id, conversation_only = self._live_connection
        service, _, disabled = await resolve_live_connection(agent_id, connection_id, service_id, conversation_only=conversation_only)
        return disabled, conversation_tool_names(service, source="external") if conversation_only else None

    async def _live_disabled_kind(self, kind: Literal["resource", "prompt"]) -> set[str]:
        if self._live_connection is None:
            return set()
        from app.connection import facade as connections
        from core.database import get_db_session
        agent_id, connection_id, service_id, conversational = self._live_connection
        await resolve_live_connection(agent_id, connection_id, service_id, conversation_only=conversational)
        async with get_db_session():
            connection = await connections.get_connection(connection_id)
            if connection is None:
                raise PermissionError("Connection revoked")
            return await connections.get_disabled_function_names(connection, capability_kind=kind)

    async def _get_resource(self, uri: str, version: Any = None) -> Resource | None:
        if self._live_connection is not None and self._live_connection[3]:
            return None
        if uri in await self._live_disabled_kind("resource"):
            return None
        return await super()._get_resource(uri, version)

    async def _get_resource_template(self, uri: str, version: Any = None) -> ResourceTemplate | None:
        if self._live_connection is not None and self._live_connection[3]:
            return None
        blocked = await self._live_disabled_kind("resource")
        if uri in blocked:
            return None
        template = await super()._get_resource_template(uri, version)
        return template if template is not None and template.uri_template not in blocked else None

    async def _get_prompt(self, name: str, version: Any = None) -> Prompt | None:
        if self._live_connection is not None and self._live_connection[3]:
            return None
        if name in await self._live_disabled_kind("prompt"):
            return None
        return await super()._get_prompt(name, version)

    async def _get_tool(self, name: str, version: Any = None) -> Tool | None:
        blocked, allowed = await self._live_tool_policy()
        if name in blocked or (allowed is not None and name not in allowed):
            return None
        tool = await super()._get_tool(name, version)
        return tool if tool is None or not self._mcp_apps or app_tool_visible_to(tool, "model") else None

    async def _list_tools(self) -> Sequence[Tool]:
        try:
            blocked, allowed = await self._live_tool_policy()
            tools = await super()._list_tools()
            tools = [tool for tool in tools if tool.name not in blocked and (allowed is None or tool.name in allowed)]
            return [tool for tool in tools if app_tool_visible_to(tool, "model")] if self._mcp_apps else tools
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
        if self._live_connection is not None and self._live_connection[3]:
            return []
        try:
            blocked = await self._live_disabled_kind("resource")
            return [resource for resource in await super()._list_resources() if str(resource.uri) not in blocked]
        except Exception as exc:
            logger.warning(
                "MCP proxy _list_resources skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []

    async def _list_resource_templates(self) -> Sequence[ResourceTemplate]:
        if self._live_connection is not None and self._live_connection[3]:
            return []
        try:
            blocked = await self._live_disabled_kind("resource")
            return [template for template in await super()._list_resource_templates() if template.uri_template not in blocked]
        except Exception as exc:
            logger.warning(
                "MCP proxy _list_resource_templates skipped ({}, error_type={})",
                id(self),
                type(exc).__name__,
            )
            return []

    async def _list_prompts(self) -> Sequence[Prompt]:
        if self._live_connection is not None and self._live_connection[3]:
            return []
        try:
            blocked = await self._live_disabled_kind("prompt")
            return [prompt for prompt in await super()._list_prompts() if prompt.name not in blocked]
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


def mcp_tools_by_service_code() -> dict[str, list[McpToolDefinition]]:
    grouped: dict[str, list[McpToolDefinition]] = {}
    for definition in load_mcp_tools():
        grouped.setdefault(definition.service_code, []).append(definition)
    return grouped


def mcp_tool_names_by_service_code() -> dict[str, tuple[str, ...]]:
    return {
        service_code: tuple(definition.name for definition in definitions)
        for service_code, definitions in mcp_tools_by_service_code().items()
    }


@lru_cache(maxsize=512)
def _public_signature(func: Callable[..., Any]) -> inspect.Signature:
    signature = inspect.signature(func)
    parameters = list(signature.parameters.values())
    if parameters and parameters[0].name in {"ctx", "context"}:
        parameters = parameters[1:]
    return signature.replace(parameters=parameters)


_active_native_context: ContextVar[McpToolContext] = ContextVar("active_native_mcp_context")


def _wrap_tool(definition: McpToolDefinition, ctx: McpToolContext | None) -> Callable[..., Awaitable[Any]]:
    bound_context = ctx
    @functools.wraps(definition.function)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = bound_context if bound_context is not None else _active_native_context.get()
        from dataclasses import replace
        from .protocols import bind_protocol_connection, reset_protocol_connection, resolve_protocol_connection
        protocol_token = None
        # ``ctx.task_id`` is frozen when the toolset is built and needs no call-time lookup.
        language: str | None = None
        execution = current_tool_execution()
        authorization_id: UUID | None = None
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
                    raise ToolPermissionRejectedError("The Harness policy no longer permits this tool call.")
                language = await context_language(ctx)
                async with asyncio.timeout(None) as timeout:
                    # A cancelled timer can stay queued. Its callback only needs this task,
                    # so the timer must not retain the request's MCP or database context.
                    Context().run(timeout.reschedule, asyncio.get_running_loop().time() + timeout_seconds)
                    visible = await list_enabled_native_mcp_definitions(
                        ctx.agent_id, runtime=ctx.runtime, conversation_only=ctx.conversation_only,
                        allowed_tool_names={definition.name}, resources=ctx.resources, task_id=ctx.task_id,
                    )
                    if not visible:
                        raise ToolPermissionRejectedError("This tool is no longer authorized or available in this execution.")
                    if definition.execution_inspection:
                        from .management_scope import administration_level

                        if await administration_level(ctx.agent_id, EXECUTION_INSPECTION_SCOPE_SERVICE) == "usage":
                            raise ToolPermissionRejectedError("Execution inspection requires delegation on the Services connection.")
                    try:
                        bound = inspect.signature(definition.function).bind(ctx, *args, **kwargs)
                    except TypeError as error:
                        raise ToolArgumentsRejectedError("Arguments do not match this Tool's declared signature") from error
                    bound.apply_defaults()
                    arguments = {
                        key: value for key, value in bound.arguments.items() if key not in {"ctx", "context"}
                    }
                    call_ctx = ctx
                    if definition.service_code in {"mail", "calendar", "rest"}:
                        protocol = cast(Literal["mail", "calendar", "rest"], definition.service_code)
                        requested = ctx.resource("source_connection_id")
                        if requested is None and arguments.get("service_code") is None and protocol == "mail" and ctx.task_id is not None:
                            from app.messenger import inbound_task_connection

                            requested = await inbound_task_connection(
                                ctx.task_id, agent_id=ctx.agent_id, platform=protocol,
                            )
                        selected = await resolve_protocol_connection(ctx.agent_id, protocol, requested,
                            service_code=arguments.get("service_code"), account_email=arguments.get("account_email"),
                            resource_id=arguments.get("calendar_id") if protocol == "calendar" else None)
                        protocol_token = bind_protocol_connection(protocol, ctx.agent_id, selected)
                        call_ctx = replace(ctx, resources={**ctx.resources, "source_connection_id": selected})
                    if definition.service_code == "messenger":
                        from app.messenger import bind_messenger_tool_context

                        call_ctx = await bind_messenger_tool_context(ctx, arguments)
                    if ctx.task_id is not None:
                        from app.agent import record_scope_preflight
                        decision = await record_scope_preflight(ctx.task_id,
                            agent_id=ctx.agent_id, descriptor=definition.effect_descriptor,
                            tool_name=definition.name, arguments=arguments,
                            operation_id=execution.operation_id if execution is not None else None)
                        if decision.decision in ("deny", "clarify"):
                            raise ScopePreflightRejected(decision.decision, decision.reason)
                    else:
                        decision = None

                    async def recheck_scope() -> None:
                        if ctx.task_id is None or decision is None:
                            return
                        from app.agent import record_scope_preflight
                        final = await record_scope_preflight(ctx.task_id, agent_id=ctx.agent_id,
                            descriptor=definition.effect_descriptor, tool_name=definition.name, arguments=arguments,
                            operation_id=decision.operation_id, expected_scope_revision=decision.scope_revision)
                        if final.decision in ("deny", "clarify"):
                            raise ScopePreflightRejected(final.decision, final.reason)

                    from .mcp_authorization import authorize_native_call, bind_native_action
                    if definition.authorization_boundary == "prepared":
                        from .authorization import prepared_authorization
                        with prepared_authorization(await bind_native_action(call_ctx, definition, arguments)) as prepared:
                            try:
                                await recheck_scope()
                                result = definition.function(call_ctx, *args, **kwargs)
                                if inspect.isawaitable(result):
                                    result = await result
                            finally:
                                authorization_id = prepared.request_id
                    else:
                        authorization_id = await authorize_native_call(call_ctx, definition, arguments)
                        from .authorization import authorized_request
                        with authorized_request(authorization_id):
                            await recheck_scope()
                            result = definition.function(call_ctx, *args, **kwargs)
                            if inspect.isawaitable(result):
                                result = await result
                    from .resource_effects import record_tool_resources

                    await record_tool_resources(call_ctx, definition.name, arguments, result)
                await get_db().commit()
            from .authorization import finish_action
            await finish_action(authorization_id, receipt=result)
            if execution is not None:
                execution.outcome = "returned"
            return result
        except asyncio.CancelledError:
            from .authorization import finish_action

            # Cancellation cannot prove that a dispatched operation had no effect.
            await asyncio.shield(finish_action(authorization_id, outcome="outcome_unknown"))
            raise
        except Exception as exc:
            from .authorization import AuthorizationRequired, AuthorizationClosed, finish_action
            if isinstance(exc, (AuthorizationRequired, AuthorizationClosed)):
                if execution is not None:
                    execution.outcome = "rejected"
                from fastmcp.tools import ToolResult
                from .authorization import AUTHORIZATION_META_KEY
                pending = isinstance(exc, AuthorizationRequired)
                return ToolResult(content=str(exc), is_error=True, meta={AUTHORIZATION_META_KEY: {
                    "request_id": str(exc.request_id), "status": "pending" if pending else exc.status,
                    "disposition": "authorization_required" if pending else "authorization_closed",
                    "continuation": exc.continuation if pending else None,
                }})
            await finish_action(authorization_id, outcome="failed" if isinstance(exc, ToolCallRejectedError) else "outcome_unknown")
            if isinstance(exc, ToolCallRejectedError) and execution is not None:
                execution.outcome = "rejected"
                execution.permission_rejected = isinstance(exc, ToolPermissionRejectedError)
                execution.arguments_rejected = isinstance(exc, ToolArgumentsRejectedError)
                if isinstance(exc, ScopePreflightRejected):
                    execution.scope_rejection = exc.decision
            failure = classify_tool_failure(exc)
            error_reference = uuid4().hex[:12]
            error_trace = safe_trace(exc)
            log = logger.bind(
                tool_name=definition.name,
                service_code=definition.service_code,
                error_kind=failure.kind,
                error_type=failure.error_type,
                error_reference=error_reference,
                error_trace=error_trace,
            )
            log.log(
                "WARNING" if failure.kind in {"actionable", "scope_clarification", "scope_denied"} else "ERROR",
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
            if definition.service_code == "agent" and definition.name not in AGENT_DISCOVERY_TOOLS:
                from fastmcp.tools import ToolResult

                kind = ("access_denied" if isinstance(exc, (PermissionError, ToolCallRejectedError))
                        else "not_found" if isinstance(exc, LookupError)
                        else "conflict" if "Conflict" in type(exc).__name__ or
                        (isinstance(exc, ValueError) and any(word in str(exc).casefold() for word in ("conflict", "already exists", "referenced")))
                        else "invalid_configuration" if isinstance(exc, ValueError)
                        else "dependency_unavailable")
                return ToolResult(content=message, is_error=True, structured_content={
                    "success": False, "error": {"kind": kind, "reference": error_reference},
                })
            if execution is not None:
                from fastmcp.tools import ToolResult

                return ToolResult(content=message, is_error=True)
            raise ToolError(message) from exc

        finally:
            if protocol_token is not None:
                reset_protocol_connection(protocol_token)

    wrapper.__name__ = definition.name
    wrapper.__doc__ = definition.description
    wrapper.__signature__ = _public_signature(definition.function)  # type: ignore[attr-defined]
    return wrapper


class _NativeFunctionTool(FunctionTool):
    """Bind each mount to its run while sharing FastMCP's parsed callable."""

    _run_context: McpToolContext = PrivateAttr()

    def bind(self, context: McpToolContext) -> "_NativeFunctionTool":
        tool = self.model_copy(deep=True)
        tool._run_context = context
        if tool.name == "task_run" and context.conversation_only:
            # Conversation admissions use a durable action key. Delegations create children.
            tool.annotations = ToolAnnotations.model_validate({"idempotentHint": True})
        return tool

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        token = _active_native_context.set(self._run_context)
        try:
            return await super().run(arguments)
        finally:
            _active_native_context.reset(token)


@lru_cache(maxsize=512)
def _native_tool_template(definition: McpToolDefinition) -> _NativeFunctionTool:
    return cast(_NativeFunctionTool, _NativeFunctionTool.from_function(_wrap_tool(definition, None)))


def add_galaris_tools(
    mcp: Any,
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    enabled_service_codes: set[str] | None = None,
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
        if enabled_service_codes is not None and definition.service_code not in enabled_service_codes:
            continue
        if not profile.supports(definition.required_capabilities):
            continue
        # Contextual tools are mounted by the asynchronous, authorized run projection.
        if definition.available_when is not None:
            continue
        if isinstance(mcp, _MediaFilteredFastMCP):
            mcp.add_tool(_native_tool_template(definition).bind(ctx))
            mcp.native_execution_names.add(definition.name)
        else:
            mcp.tool()(_wrap_tool(definition, ctx))


def build_galaris_fastmcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    enabled_service_codes: set[str] | None = None,
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
) -> FastMCP:
    """Build a complete or filtered native Galaris FastMCP server."""
    mcp: FastMCP = _MediaFilteredFastMCP(f"Galaris tools — Agent {agent_id}", agent_id=agent_id, runtime=runtime)
    add_galaris_tools(
        mcp,
        agent_id,
        runtime=runtime,
        enabled_service_codes=enabled_service_codes,
        task_id=task_id,
        resources=resources,
    )
    return mcp


type ActiveServiceBindings = tuple[tuple[ActiveConnectionRef, ServiceConfiguration], ...]


async def active_service_bindings(agent_id: int) -> ActiveServiceBindings:
    from app.connection.facade import active_connection_refs
    from .service import get_services_by_ids

    active = await active_connection_refs(agent_id)
    services = await get_services_by_ids({ref.service_id for ref in active})
    return tuple((ref, services[ref.service_id]) for ref in active if ref.service_id in services)


async def get_enabled_integrated_service_codes(agent_id: int) -> set[str]:
    """Return native tool codes with an active connection for the agent."""
    known = mcp_tools_by_service_code().keys()
    enabled: set[str] = set()
    for connection, tool in await active_service_bindings(agent_id):
        enabled.update(known & await native_service_codes_for_agent_connection(tool, connection.id))
    return enabled


@dataclass(frozen=True)
class _NativePolicy:
    codes: frozenset[str]
    blocked: frozenset[str]
    allowed: frozenset[str] | None


async def _native_policies(bindings: ActiveServiceBindings, *, conversation_only: bool) -> frozenset[_NativePolicy]:
    from app.connection.facade import get_disabled_function_names_many

    eligible: list[tuple[ActiveConnectionRef, frozenset[str], frozenset[str] | None]] = []
    registry = load_mcp_tools()
    names = frozenset(tool.name for tool in registry)
    families = frozenset(tool.service_code for tool in registry)
    for ref, service in bindings:
        allowed = names.intersection(conversation_tool_names(service, source="native")) if conversation_only else None
        if allowed is not None and not allowed:
            continue
        codes = families & await native_service_codes_for_agent_connection(service, ref.id)
        if codes:
            eligible.append((ref, codes, allowed))
    disabled = await get_disabled_function_names_many([ref for ref, _, _ in eligible])
    return frozenset(_NativePolicy(codes, names.intersection(disabled.get(ref.id, ())), allowed)
                     for ref, codes, allowed in eligible)


@lru_cache(maxsize=256)
def _native_catalog(definitions: tuple[McpToolDefinition, ...], policies: frozenset[_NativePolicy],
                    conversation_only: bool) -> tuple[McpToolDefinition, ...]:
    """Cache only immutable registry entries. Equal effective inputs can share the base across agents."""
    policies_by_code: dict[str, list[_NativePolicy]] = {}
    for policy in policies:
        for code in policy.codes:
            policies_by_code.setdefault(code, []).append(policy)
    candidates = (item for item in definitions if item.conversation_policy != "forbidden") if conversation_only else (
        item for item in definitions if item.task_enabled)
    return tuple(item for item in candidates if any(
        item.name not in policy.blocked and (policy.allowed is None or item.name in policy.allowed)
        for policy in policies_by_code.get(item.service_code, ())
    ))


async def get_disabled_internal_function_names(agent_id: int) -> set[str]:
    """All blocked native names, including specialist media without a usable model."""
    from app.llm import available_media_functions

    rules = await _native_policies(await active_service_bindings(agent_id), conversation_only=False)
    names_by_code = mcp_tool_names_by_service_code()
    offered: set[str] = set()
    enabled: set[str] = set()
    for rule in rules:
        names = {name for code in rule.codes for name in names_by_code.get(code, ())}
        offered.update(names)
        enabled.update(names - rule.blocked)
    return (offered - enabled) | (set(SPECIALIST_MEDIA_TOOLS) - await available_media_functions(agent_id))


async def list_enabled_native_mcp_definitions(
    agent_id: int,
    *,
    runtime: RuntimeName,
    allowed_tool_names: Collection[str] | None = None,
    conversation_only: bool = False,
    resources: dict[str, Any] | None = None,
    task_id: UUID | None = None,
    _bindings: ActiveServiceBindings | None = None,
) -> tuple[McpToolDefinition, ...]:
    """Return the exact native function definitions visible to an agent.

    This is the shared authorization projection used by both the MCP server and agent-facing
    capability advertising. Keeping it here prevents prompts from naming an inactive,
    runtime-incompatible, connection-disabled, or task-scoped function.
    """
    from app.agent import effective_tool_profile

    allowed_names = frozenset(allowed_tool_names) if allowed_tool_names is not None else None
    registry = load_mcp_tools()
    bindings = _bindings if _bindings is not None else await active_service_bindings(agent_id)
    if allowed_names is not None:
        # A lookup for one family needs no account policies from other families.
        # Protocol-backed services can supply native tools under a different code.
        families = {item.service_code for item in registry if item.name in allowed_names}
        bindings = tuple((ref, service) for ref, service in bindings
                         if not families.isdisjoint(native_service_codes_for_service(service)))
    if not bindings:
        return ()
    policies = await _native_policies(bindings, conversation_only=conversation_only)
    base = _native_catalog(registry, policies, conversation_only)
    if allowed_names is not None:
        base = tuple(item for item in base if item.name in allowed_names)
    if not base:
        return ()
    profile = await effective_tool_profile(agent_id, runtime)
    definitions = [definition for definition in base if profile.supports(definition.required_capabilities)]
    media_names = {item.name for item in definitions if item.name in SPECIALIST_MEDIA_TOOLS}
    if media_names:
        from app.llm import available_media_functions

        media = await available_media_functions(agent_id, candidates=media_names)
        definitions = [item for item in definitions if item.name not in SPECIALIST_MEDIA_TOOLS or item.name in media]
    if task_id is not None and any(definition.service_code == "messenger" for definition in definitions):
        from app.messenger import inbound_task_connection

        if await inbound_task_connection(task_id, agent_id=agent_id, platform="mail") is not None:
            definitions = [definition for definition in definitions if definition.service_code != "messenger"]
    ctx = McpToolContext(
        agent_id=agent_id, runtime=runtime, resources=dict(resources or {}), task_id=task_id,
        conversation_only=conversation_only,
    )
    from app.agent.facade import admin_available
    from .management_scope import administration_scope

    discovery = {"agent": AGENT_DISCOVERY_TOOLS, "service": SERVICE_DISCOVERY_TOOLS}
    usage_only = {
        code for code, names in discovery.items()
        if any(item.service_code == code and item.name not in names for item in definitions)
        and (await administration_scope(agent_id, code)).level == "usage"
    }

    # Several catalog entries require the same delegation. Keep this snapshot
    # local to discovery; the native call performs its own live authorization.
    admin_permissions: dict[tuple[tuple[str, ...], bool], bool] = {}

    async def permitted(definition: McpToolDefinition) -> bool:
        code = definition.service_code
        name = definition.name
        if code in usage_only and name not in discovery[code]:
            return False
        if code != "agent" or name in AGENT_DISCOVERY_TOOLS:
            return True
        privileges = ["AGENT_EDIT"]
        if name.startswith("agent_connection_") or name == "agent_service_list":
            privileges.append("CONNECTION_EDIT")
        if name.startswith(("agent_team_", "agent_group_")):
            privileges.append("TEAM_ACCESS")
        if name == "agent_team_set":
            privileges.append("TEAM_MEMBERS_EDIT")
        if name.startswith("agent_group_") and name != "agent_group_list":
            privileges.append("TEAM_EDIT")
        if name == "agent_harness_blockers":
            privileges.append("TASK_EDIT")
        global_scope = name in {f"agent_{kind}_{op}" for kind in ("group", "title") for op in ("create", "update", "delete")}
        permission = (tuple(privileges), global_scope)
        if permission not in admin_permissions:
            admin_permissions[permission] = await admin_available(agent_id, *privileges, global_scope=global_scope)
        return admin_permissions[permission]

    visible = [
        definition for definition in definitions
        if await permitted(definition)
        and (definition.available_when is None or await definition.available_when(ctx))
    ]
    return tuple(sorted(visible, key=lambda item: (item.service_code, item.name)))


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
        task_id=task_id,
        resources=resources,
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
    from pydantic import ConfigDict, validate_call

    # Recovery receives JSON arguments just like MCP. Materialize typed inputs
    # before authorization/execution instead of passing dictionaries to models.
    validated = validate_call(config=ConfigDict(arbitrary_types_allowed=True))(_wrap_tool(definition, ctx))
    return await validated(**arguments)


async def build_agent_galaris_fastmcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
    allowed_tool_names: Collection[str] | None = None,
    conversation_only: bool = False,
    _bindings: ActiveServiceBindings | None = None,
) -> FastMCP:
    """Build native MCP filtered by active connections and disabled functions."""
    resolved_resources = dict(resources or {})
    definitions = await list_enabled_native_mcp_definitions(
        agent_id,
        runtime=runtime,
        allowed_tool_names=allowed_tool_names,
        conversation_only=conversation_only,
        resources=resolved_resources,
        task_id=task_id,
        _bindings=_bindings,
    )
    if (
        any(definition.service_code == "console" for definition in definitions)
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
    mcp = _MediaFilteredFastMCP(f"Galaris tools — Agent {agent_id}", agent_id=agent_id, runtime=runtime, conversation_only=conversation_only)
    for definition in definitions:
        tool = _native_tool_template(definition).bind(ctx)
        if definition.name == "rest_request":
            # Conversation runs can expose REST without mounting services_list.
            tool.description = f"{definition.description}\n{await _rest_connection_choices(ctx, _bindings)}"
        mcp.add_tool(tool)
        mcp.native_execution_names.add(definition.name)
    # An already mounted task can acquire one of these functions later.
    # Keep the definition until the first visible listing or explicit lookup.
    from app.agent import resolve_tool_profile
    present = {definition.name for definition in definitions}
    profile = resolve_tool_profile(runtime)
    for definition in load_mcp_tools():
        if (definition.service_code in {"multimedia", "agent", "service"} and definition.name not in present
                and profile.supports(definition.required_capabilities)
                and (allowed_tool_names is None or definition.name in allowed_tool_names)
                and not conversation_only):
            mcp.deferred_tools[definition.name] = (definition, ctx)
            mcp.native_execution_names.add(definition.name)
    return mcp


async def _rest_connection_choices(ctx: McpToolContext, bindings: ActiveServiceBindings | None) -> str:
    """Advertise only REST accounts eligible for this run, without resolving credentials."""
    from app.connection import facade as connections
    if bindings is None:
        bindings = await active_service_bindings(ctx.agent_id)
    candidates = {row.id: tool for row, tool in bindings if tool.rest
                  and (not ctx.conversation_only or "rest_request" in conversation_tool_names(tool, source="native"))}
    modes = await connections.resolve_function_states_many(candidates.keys(), "rest_request")
    eligible = [identifier for identifier in candidates if modes.get(identifier) in {"ask", "enabled"}]
    addresses = await connections.account_emails_for_connections([i for i in eligible if candidates[i].mail is not None])
    choices: list[str] = []
    for identifier in eligible:
        choice = f"service_code={candidates[identifier].code}"
        if email := addresses.get(identifier):
            choice += f", account_email={email}"
        choices.append(choice)
    return "Available accounts: " + "; ".join(sorted(choices))


class _MediaFilteredFastMCP(FastMCP):
    def __init__(self, name: str, *, agent_id: int, runtime: RuntimeName = "internal", conversation_only: bool = False) -> None:
        super().__init__(name)  # pyright: ignore[reportUnknownMemberType]
        self.media_agent_id = agent_id
        self.runtime = runtime
        self.conversation_only = conversation_only
        self.native_execution_names: set[str] = set()
        self.deferred_tools: dict[str, tuple[McpToolDefinition, McpToolContext]] = {}
        self.add_middleware(ToolArgumentsMiddleware(self.native_execution_names))
        self.add_middleware(ExecutionEvidenceMiddleware(self.native_execution_names))

    def _mount_deferred_tool(self, name: str) -> None:
        pending = self.deferred_tools.get(name)
        if pending is not None:
            definition, ctx = pending
            self.add_tool(_native_tool_template(definition).bind(ctx))
            del self.deferred_tools[name]

    async def _get_tool(self, name: str, version: VersionSpec | None = None) -> Tool | None:
        self._mount_deferred_tool(name)
        return await super()._get_tool(name, version)

    async def _get_tool_by_hash(self, tool_hash: str, tool_name: str) -> Tool | None:
        self._mount_deferred_tool(tool_name)
        return await super()._get_tool_by_hash(tool_hash, tool_name)

    async def _list_tools(self) -> Sequence[Tool]:
        # Filter at provider collection, before FastMCP applies transforms and
        # dispatches the results to middleware. Each listing takes one snapshot.
        tools = await super()._list_tools()
        from core.database import get_db_session

        mounted = {tool.name for tool in tools}
        registered = self.native_execution_names | mounted
        dynamic = {
            d.name for d in load_mcp_tools() if d.name in registered and (
                d.service_code in {"multimedia", "agent", "service"} or d.name in {"team_list", "team_members"})
        }
        if not dynamic:
            return tools

        # In-process MCP discovery can inherit the agent's run session. Keep the
        # live authorization read short so generation doesn't retain that transaction.
        async with get_db_session():
            visible = {definition.name for definition in await list_enabled_native_mcp_definitions(
                self.media_agent_id, runtime=self.runtime, allowed_tool_names=dynamic, conversation_only=self.conversation_only)}
        newly_visible = visible - mounted
        if newly_visible:
            for name in sorted(newly_visible):
                self._mount_deferred_tool(name)
            tools = await super()._list_tools()
        return [tool for tool in tools if tool.name not in dynamic or tool.name in visible]


def _resolve_auth_headers(mcp_config: McpConfig, params: dict[str, Any], *, oauth: bool = False) -> dict[str, str]:
    from app.services.mcp import _build_auth_headers  # pyright: ignore[reportPrivateUsage]

    headers = resolve_mapping_references({key: value for key, value in (mcp_config.headers or {}).items()
                                         if not oauth or key.lower() != "authorization"}, params)
    if not oauth:
        headers.update(_build_auth_headers(mcp_config.auth, params))
    return headers


def _external_transport(tool: Any, params: dict[str, Any]) -> Any:
    from app.services.mcp import _inject_url_param  # pyright: ignore[reportPrivateUsage]
    from app.connection.facade import mcp_oauth_auth

    mcp = tool.mcp
    if mcp.type in {"sse", "http"}:
        url = resolve_connection_references(mcp.url or "", params)
        oauth = mcp_oauth_auth(params, url) if mcp.auth.type == "oauth" else None
        if mcp.auth.type != "oauth" and mcp.auth.url_param:
            url = _inject_url_param(url, mcp.auth, params)
        transport = SSETransport if mcp.type == "sse" else StreamableHttpTransport
        return transport(url, headers=_resolve_auth_headers(mcp, params, oauth=oauth is not None), auth=oauth)
    if mcp.type == "stdio":
        if not mcp.command:
            raise ValueError(t("services.errors.stdio_command_missing"))
        return StdioTransport(
            command=mcp.command,
            args=mcp.args or [],
            env=resolve_mapping_references(mcp.env or {}, params) or None,
        )
    raise ValueError(
        render_prompt(
            t("services.errors.unsupported_mcp_type"),
            type=mcp.type,
        )
    )


class MountedAgentMcp(FastMCP):
    """Agent server with access to its local catalog without discovering remote tools."""

    native_server: FastMCP
    initial_conversation_names: frozenset[str] | None = None
    initial_task_context: str | None = None

    async def native_tool_names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in await self.native_server.list_tools())


async def request_mcp_presentation(
    presentation: McpPresentation, *, agent_id: int, user_id: int, room_id: UUID,
    arguments: dict[str, JsonValue] | None = None,
) -> str | McpTable:
    """Use only the original, currently enabled read tool or its declared UI resource."""
    from jsonschema import validators  # pyright: ignore[reportMissingTypeStubs]
    from mcp.types import TextResourceContents
    from .authorization import AuthorizationAction, claim_action, tool_authorization_configuration
    from .mcp_presentation import MCP_APP_MIME, MAX_APP_HTML_BYTES, app_read_tool, app_resource_uri, presented_table

    uri = presentation.resource_uri
    if uri is None:
        raise PermissionError("The result has no interactive view")
    service, params, _ = await resolve_live_connection(
        agent_id, presentation.connection_id, presentation.service_id,
        function_name=presentation.tool_name, conversation_only=True,
    )
    if service.mcp is None or service.mcp.type != "http":
        raise PermissionError("The connection no longer uses Streamable HTTP")
    async with Client(_external_transport(service, params), init_timeout=5, timeout=10,
                      extensions=[MCP_APP_EXTENSION]) as client:
        tool = next((candidate for candidate in await client.list_tools() if candidate.name == presentation.tool_name), None)
        if tool is None or app_resource_uri(tool) != uri or not app_read_tool(tool):
            raise PermissionError("The original read tool or view is unavailable")
        action = AuthorizationAction(
            agent_id=agent_id, service_id=presentation.service_id, connection_id=presentation.connection_id,
            name=tool.name, arguments=arguments or {}, runtime="internal", context_key=f"principal:chat:{room_id}",
            callback_key=str(uuid4()), approver_user_id=user_id,
            configuration={"tool": tool_authorization_configuration(service), "params": params, "schema": tool.input_schema},
        )
        if arguments is not None:
            cast(Any, validators).validator_for(tool.input_schema)(tool.input_schema).validate(arguments)
        await claim_action(action, enabled_only=True)
        if arguments is None:
            await claim_action(replace(action, name=uri, arguments={"uri": uri}, kind="resource"), enabled_only=True)
            contents = await client.read_resource(uri)
            if len(contents) != 1:
                raise ValueError("Expected one MCP App document")
            content = contents[0]
            if (not isinstance(content, TextResourceContents) or str(content.uri) != uri
                    or content.mime_type != MCP_APP_MIME or not 0 < len(content.text.encode()) <= MAX_APP_HTML_BYTES):
                raise ValueError("Unsupported MCP App document")
            return content.text
        result = await client.call_tool(tool.name, arguments)
        table = presented_table(result.structured_content)
        if result.is_error or table is None:
            raise ValueError("The MCP tool did not return a valid table")
        return table


async def build_agent_mcp(
    agent_id: int,
    *,
    runtime: RuntimeName = "internal",
    task_id: UUID | None = None,
    resources: dict[str, Any] | None = None,
    discovery_failures: set[str] | None = None,
    conversation_only: bool = False,
    allowed_tool_names: Collection[str] | None = None,
    allow_stdio: bool = True,
    include_task_context: bool = False,
) -> MountedAgentMcp:
    """Build an agent's aggregate native and external MCP server."""
    presentation_sink = cast(McpPresentationSink | None, (resources or {}).get("mcp_presentation_sink"))

    mcp = MountedAgentMcp(f"Galaris — Agent {agent_id}")
    server_ref = weakref.ref(mcp)

    async def run_tool_names() -> frozenset[str]:
        # Query this run's mounted server, not a fresh agent-wide configuration.
        # This includes deferred tools and namespaced external MCP tools.
        # Registered callbacks can outlive the run. The caller owns its server.
        server = server_ref()
        if server is None:
            raise ToolCallRejectedError("The MCP server for this run is no longer available")
        return frozenset(tool.name for tool in await server.list_tools())

    bindings = await active_service_bindings(agent_id)
    if include_task_context:
        from .agent_registry import task_context_from_bindings
        mcp.initial_task_context = await task_context_from_bindings(bindings)
    mcp.native_server = await build_agent_galaris_fastmcp(
        agent_id,
        runtime=runtime,
        task_id=task_id,
        resources={**(resources or {}), "run_tool_names": run_tool_names},
        allowed_tool_names=allowed_tool_names,
        conversation_only=conversation_only,
        _bindings=bindings,
    )
    mcp.mount(mcp.native_server)
    if conversation_only and isinstance(mcp.native_server, _MediaFilteredFastMCP):
        # Conversations mount only the currently enabled definitions. The prompt
        # can reuse that inventory while subsequent discovery and calls stay live.
        mcp.initial_conversation_names = frozenset(mcp.native_server.native_execution_names)

    for connection, tool in bindings:
        if not tool.mcp:
            continue
        if conversation_only and not conversation_tool_names(tool, source="external"):
            continue
        if not allow_stdio and tool.mcp.type == "stdio":
            if discovery_failures is not None:
                discovery_failures.add(tool.code)
            continue
        try:
            proxy = FastMCP(tool.code)
            proxy.add_middleware(ToolArgumentsMiddleware())
            from .external_authorization import ExternalAuthorizationMiddleware
            from .mcp_authorization import authorization_context_key
            proxy.add_middleware(ExternalAuthorizationMiddleware(
                agent_id, connection.id, connection.service_id, runtime=runtime,
                context_key=authorization_context_key(task_id, resources or {}),
                runtime_grant_id=UUID(str(resources["runtime_grant_id"])) if resources and resources.get("runtime_grant_id") else None,
                conversation_only=conversation_only,
                presentation_sink=presentation_sink if tool.mcp.type == "http" else None,
                source_label=tool.label,
            ))
            # Capture identities only. An old run must not capture old credentials.
            def live_factory(agent: int, connection_id: int, service_id: int, conversational: bool,
                             mcp_apps: bool) -> Callable[[], Awaitable[Client[Any]]]:
                async def client() -> Client[Any]:
                    from .live_external import resolve_live_connection

                    current, current_params, _ = await resolve_live_connection(agent, connection_id, service_id, conversation_only=conversational)
                    return Client(_external_transport(current, current_params),
                                  extensions=[MCP_APP_EXTENSION] if mcp_apps else None)
                return client

            mcp_apps = presentation_sink is not None and tool.mcp.type == "http"
            proxy.add_provider(_ResilientProxyProvider(
                live_factory(agent_id, connection.id, connection.service_id, conversation_only, mcp_apps),
                discovery_source=tool.code,
                discovery_failures=discovery_failures,
                live_connection=(agent_id, connection.id, connection.service_id, conversation_only),
                mcp_apps=mcp_apps,
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
    from app.services import service

    servers: list[Any] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await service.get_service_by_id(connection.service_id)
        if not tool or not tool.mcp:
            continue
        try:
            from .live_external import LiveConnectionToolset

            server = LiveConnectionToolset(agent_id, connection.id, connection.service_id)
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
    from app.services.mcp import build_mcp_server

    server = build_mcp_server(tool, params, prefix_tools=False)
    if not server:
        raise ValueError(await tr("services.errors.server_creation_failed"))
    async with server:
        tools = await server.list_tools()
    return [(tool.name, tool.description or "") for tool in tools]


async def list_external_mcp_capabilities(tool: ServiceConfiguration, params: dict[str, Any], *,
                                         include_resources: bool = True) -> list[tuple[str, str, Literal["tool", "resource", "prompt"]]]:
    result: list[tuple[str, str, Literal["tool", "resource", "prompt"]]] = []
    async with Client(_external_transport(tool, params)) as client:
        capabilities = client.server_capabilities
        if capabilities is None:
            raise RuntimeError("MCP server capabilities were not negotiated")
        tools = await client.list_tools()
        result.extend((item.name, item.description or "", "tool") for item in tools)
        if include_resources and capabilities.resources is not None:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            result.extend((str(item.uri), item.description or "", "resource") for item in resources)
            result.extend((item.uri_template, item.description or "", "resource") for item in templates)
        if capabilities.prompts is not None:
            prompts = await client.list_prompts()
            result.extend((item.name, item.description or "", "prompt") for item in prompts)
    return result


async def list_internal_mcp_functions(
    agent_id: int,
    service_code: str,
    *,
    runtime: RuntimeName = "internal",
    tool: Any | None = None,
) -> list[tuple[str, str]]:
    """List native functions declared by a built-in service."""
    del agent_id, runtime
    codes = native_service_codes_for_service(tool) if tool is not None else native_service_codes_for_connection(service_code)
    # Administration must retain blocked capabilities so humans can restore them.
    return [(definition.name, definition.description) for definition in load_mcp_tools() if definition.service_code in codes]


async def list_agent_mcp_tools(agent_id: int) -> list[dict[str, Any]]:
    """Return an agent's MCP catalog grouped by application tool."""
    from app.agent import agent_service, effective_tool_profile, validate_agent_driver
    from app.connection import facade as connection_service
    from app.services import service

    agent = await agent_service.get(agent_id)
    runtime: RuntimeName = validate_agent_driver(
        getattr(agent, "agent_driver", None),
        require_available=False,
    )
    profile = await effective_tool_profile(agent_id, runtime)
    connections = await connection_service.get_connections_by_agent(agent_id)
    native_by_tool = mcp_tools_by_service_code()
    from app.llm import available_media_functions
    media_functions: frozenset[str] = await available_media_functions(agent_id) if "multimedia" in native_by_tool else frozenset()
    admin_names = {definition.name for code, discovery in (("agent", AGENT_DISCOVERY_TOOLS), ("service", SERVICE_DISCOVERY_TOOLS))
                   for definition in native_by_tool.get(code, []) if definition.name not in discovery}
    permitted_admin: set[str] = {definition.name for definition in await list_enabled_native_mcp_definitions(
        agent_id, runtime=runtime, allowed_tool_names=admin_names)} if admin_names else set()
    admin_context = McpToolContext(agent_id=agent_id, runtime=runtime)
    records = await service.get_all_service_records()

    groups: list[dict[str, Any]] = []
    record_connections = [(record, connection) for record in records
        for connection in ([row for row in connections if row.service_id == record.id] or [None])]
    addresses = await connection_service.account_emails_for_connections(
        [connection.id for record, connection in record_connections if connection and getattr(record, "mail_config", None) is not None])
    for record, connection in record_connections:
        tool = service._to_internal(record)  # pyright: ignore[reportPrivateUsage]
        native_definitions = [
            definition
            for native_code in sorted(native_service_codes_for_service(tool))
            for definition in native_by_tool.get(native_code, [])
        ]
        has_native = bool(native_definitions)
        has_external = bool(tool.mcp)
        if not (has_native or has_external):
            continue

        active = bool(connection and connection.active)
        active_codes: frozenset[str] = frozenset()
        disabled: set[str] = set()
        if connection is not None:
            active_codes = await native_service_codes_for_agent_connection(tool, connection.id)
            disabled = await connection_service.get_disabled_function_names(connection)

        mcp_tools: list[dict[str, Any]] = []
        error = ""
        if has_native:
            for definition in native_definitions:
                if definition.name in SPECIALIST_MEDIA_TOOLS and definition.name not in media_functions:
                    continue
                if definition.name in admin_names and definition.available_when is not None and not await definition.available_when(admin_context):
                    continue
                runtime_supported = profile.supports(definition.required_capabilities)
                mcp_tools.append({
                    "name": definition.name,
                    "description": definition.description,
                    "enabled": active and runtime_supported and definition.name not in disabled
                    and definition.service_code in active_codes
                    and (definition.name not in admin_names or definition.name in permitted_admin),
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
                error = t("services.introspection_failed")

        groups.append({
            "service_id": record.id,
            "service_code": record.code,
            "service_label": record.label,
            "service_description": record.description or "",
            "connection_id": connection.id if connection is not None else None,
            "mail_address": addresses.get(connection.id, "") if connection else "",
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
    return sorted(groups, key=lambda item: cast(str, item["service_code"]))
