"""Adapt the Galaris MCP catalog to Pydantic AI toolsets."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

import anyio
from anyio.lowlevel import RunVar
from loguru import logger
from fastmcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, TextContent
from core import settings

from app.agent.contracts import normalize_tool_name
from app.services.contracts import EXECUTION_META_KEY, TOOL_ARGUMENTS_META_KEY, current_tool_execution
from app.services.agent_registry import (
    AgentToolAdvertisement,
    build_agent_galaris_fastmcp,
    build_agent_tool_advertisement,
    build_galaris_fastmcp,
)


_MCP_TOOL_MAX_RETRIES = 3
_task_mount_slots = RunVar[anyio.CapacityLimiter]("galaris_task_mcp_mount_slots")
_conversation_mount_slots = RunVar[anyio.CapacityLimiter]("galaris_conversation_mcp_mount_slots")


@asynccontextmanager
async def _mount_session(limiter: RunVar[anyio.CapacityLimiter], limit: int) -> AsyncGenerator[None, None]:
    """Admit a local catalog read before opening its SQL transaction."""
    from core.database import get_db, get_db_session

    try:
        caller = get_db()
    except RuntimeError:
        caller = None
    if caller is not None and caller.in_transaction():
        # A transactional caller may need its uncommitted configuration. Do
        # not queue it while it holds a connection or commit on its behalf.
        yield
        return

    slots = limiter.get(None)
    if slots is None:
        slots = anyio.CapacityLimiter(limit)
        limiter.set(slots)
    async with slots, get_db_session():
        yield


class ExecutionEvidenceClient(Client[Any]):
    """Keep MCP's native content mapping while observing its execution receipts."""

    def __init__(self, server: Any) -> None:
        super().__init__(server, init_timeout=5, timeout=300)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        from app.services.facade import AUTHORIZATION_META_KEY, AuthorizationRequired, AuthorizationClosed

        execution = current_tool_execution()
        if execution is not None:
            kwargs["meta"] = {
                **(kwargs.get("meta") or {}),
                EXECUTION_META_KEY: {"operation_id": str(execution.operation_id)},
                **({AUTHORIZATION_META_KEY: {"continuation": execution.authorization_continuation}}
                   if execution.authorization_continuation else {}),
            }
        kwargs["raise_on_error"] = False
        try:
            result = cast(Any, await super().call_tool(name, arguments, **kwargs))
        except MCPError as exc:
            if exc.error.code != CONNECTION_CLOSED:
                raise
            # The SDK would turn this into ModelRetry, acknowledging a business
            # failure. Keep the call pending: recovery owns replay/uncertainty.
            raise asyncio.CancelledError("MCP transport closed during tool execution") from exc
        except (anyio.ClosedResourceError, anyio.BrokenResourceError) as exc:
            raise asyncio.CancelledError("MCP transport closed during tool execution") from exc
        raw_meta: object = result.meta
        if isinstance(raw_meta, dict) and TOOL_ARGUMENTS_META_KEY in cast(dict[str, Any], raw_meta):
            # Pydantic AI otherwise treats all text blocks as redundant with the
            # structured result. Enrich only this model-facing projection; preserve
            # structured fields even when the provider's text is only a summary.
            # Multimodal results already use the content blocks, including the warning.
            if result.structured_content is not None and all(
                isinstance(part, TextContent) for part in result.content
            ):
                result.structured_content = {
                    "result": result.structured_content,
                    "argument_warning": cast(dict[str, Any], raw_meta)[TOOL_ARGUMENTS_META_KEY],
                }
        if isinstance(raw_meta, dict):
            control = cast(dict[str, Any], raw_meta).get(AUTHORIZATION_META_KEY)
            if isinstance(control, dict):
                authorization_control = cast(dict[str, Any], control)
                identifier = UUID(str(authorization_control["request_id"]))
                if execution is not None:
                    execution.outcome = "rejected"
                if authorization_control.get("disposition") == "authorization_required":
                    continuation = authorization_control.get("continuation")
                    raise AuthorizationRequired(identifier, continuation if isinstance(continuation, str) else None)
                raise AuthorizationClosed(identifier, str(authorization_control.get("status") or "invalidated"))
        if execution is not None and isinstance(raw_meta, dict):
            raw_evidence: Any = cast(dict[str, Any], raw_meta).get(EXECUTION_META_KEY)
            evidence = cast(dict[str, Any], raw_evidence) if isinstance(raw_evidence, dict) else {}
            if (evidence and not result.is_error
                and evidence.get("operation_id") == str(execution.operation_id)
                and evidence.get("tool_name") == name
                and evidence.get("wait_for_children") is True):
                execution.wait_for_children = True
            if (
                evidence.get("operation_id")
                == str(execution.operation_id)
                and evidence.get("tool_name") == name
                and evidence.get("outcome") == "rejected"
            ):
                execution.outcome = "rejected"
                execution.permission_rejected = evidence.get("permission_rejected") is True
                execution.arguments_rejected = evidence.get("arguments_rejected") is True
                rejection = evidence.get("scope_rejection")
                if rejection in {"clarify", "deny"}:
                    execution.scope_rejection = rejection
        if result.is_error and result.structured_content is not None:
            # Pydantic AI prefers structured error content. Some servers supply only
            # a code (or {}) there and put the actionable cause in text blocks.
            # Preserve both rather than hiding the diagnostic behind sparse JSON.
            error_text = "\n".join(part.text for part in result.content if isinstance(part, TextContent))
            if error_text:
                result.structured_content = {"error": error_text, "details": result.structured_content}
        return result


def build_galaris_toolset(agent_id: int) -> Any:
    from pydantic_ai.mcp import MCPToolset

    return MCPToolset(
        ExecutionEvidenceClient(build_galaris_fastmcp(agent_id, runtime="internal")),
        id=f"galaris-{agent_id}",
        max_retries=_MCP_TOOL_MAX_RETRIES,
        cache_tools=False,
    )


async def build_agent_galaris_toolset(
    agent_id: int,
    *,
    task_id: UUID | None = None,
) -> Any:
    from pydantic_ai.mcp import MCPToolset

    return MCPToolset(
        ExecutionEvidenceClient(
            await build_agent_galaris_fastmcp(
                agent_id,
                runtime="internal",
                task_id=task_id,
            )
        ),
        id=f"galaris-{agent_id}",
        max_retries=_MCP_TOOL_MAX_RETRIES,
        cache_tools=False,
    )


async def build_conversation_toolset(
    agent_id: int,
    *,
    resources: dict[str, Any],
    allowed_tool_names: Collection[str] | None = None,
) -> tuple[Any, AgentToolAdvertisement]:
    """Build the round toolset and advertise its mounted native functions."""

    from pydantic_ai.mcp import MCPToolset

    from app.services import mcp_loader

    async with _mount_session(_conversation_mount_slots, settings.AGENT_MCP_CONVERSATION_MOUNT_CONCURRENCY):
        server = await mcp_loader.build_agent_mcp(
            agent_id, runtime="internal", task_id=None, resources=resources,
            conversation_only=True, allowed_tool_names=allowed_tool_names, include_task_context=True,
        )
        names = server.initial_conversation_names
        advertisement = await build_agent_tool_advertisement(
            agent_id, runtime="internal", conversation_only=True, include_task_only_tools=True,
            mounted_native_tool_names=names if names is not None else await server.native_tool_names(),
            mounted_task_context=server.initial_task_context,
        )
    toolset = MCPToolset(
        ExecutionEvidenceClient(server),
        id=f"conversation-{agent_id}",
        max_retries=1,
        cache_tools=False,
    )
    return toolset, advertisement


async def build_agent_mcp_toolset(
    agent_id: int,
    *,
    task_id: UUID | None = None,
    eager_tool_names: set[str] | None = None,
    expected_catalog_version: str | None = None,
    resources: dict[str, Any] | None = None,
) -> Any:
    from pydantic_ai.mcp import MCPToolset
    from app.services import mcp_loader

    async with _mount_session(_task_mount_slots, settings.AGENT_MCP_MOUNT_CONCURRENCY):
        mcp = await mcp_loader.build_agent_mcp(
            agent_id,
            runtime="internal",
            task_id=task_id,
            resources=resources,
        )
    toolset = MCPToolset(
        ExecutionEvidenceClient(mcp),
        id=f"agent-mcp-{agent_id}",
        max_retries=_MCP_TOOL_MAX_RETRIES,
        cache_tools=False,
    )
    if eager_tool_names is None and not expected_catalog_version:
        return toolset
    tools = await mcp.list_tools()
    if expected_catalog_version:
        from app.services import (
            catalog_entry_from_definition,
            catalog_from_entries,
        )
        from app.services.metrics import observe_catalog_snapshot

        catalog = catalog_from_entries(
            agent_id=agent_id,
            runtime="internal",
            entries=[
                catalog_entry_from_definition(
                    runtime="internal",
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=getattr(tool, "parameters", {}),
                )
                for tool in tools
            ],
        )
        missing_count = len((eager_tool_names or set()) - catalog.names)
        matches = catalog.version == expected_catalog_version
        observe_catalog_snapshot(
            matches=matches,
            missing_eager_tools=missing_count,
        )
        if not matches:
            logger.warning(
                "Agent {} tool catalog changed between planning ({}) and "
                "execution ({}); {} eager tool(s) are unavailable",
                agent_id,
                expected_catalog_version[:12],
                catalog.version[:12],
                missing_count,
            )
    if eager_tool_names is None:
        return toolset
    deferred_names = sorted(
        tool.name for tool in tools if normalize_tool_name(tool.name) not in eager_tool_names
    )
    if not deferred_names:
        return toolset
    return toolset.defer_loading(deferred_names)


async def get_agent_mcp_servers(agent_id: int) -> list[Any]:
    """Compatibility entry point for manual Pydantic AI scripts."""
    from app.services import mcp_loader

    return await mcp_loader.get_agent_mcp_servers(agent_id)


__all__ = [
    "build_agent_galaris_toolset",
    "build_agent_mcp_toolset",
    "build_conversation_toolset",
    "build_galaris_toolset",
    "get_agent_mcp_servers",
]
