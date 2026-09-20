"""Adapt the Galaris MCP catalog to Pydantic AI toolsets."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, cast
from uuid import UUID

from loguru import logger
from fastmcp import Client

from app.agent.contracts import normalize_tool_name
from app.tools.contracts import EXECUTION_META_KEY, current_tool_execution
from app.tools.agent_registry import (
    build_agent_galaris_fastmcp,
    build_galaris_fastmcp,
)


_MCP_TOOL_MAX_RETRIES = 3


class ExecutionEvidenceClient(Client[Any]):
    """Keep MCP's native content mapping while observing its execution receipts."""

    def __init__(self, server: Any) -> None:
        super().__init__(server, init_timeout=5, timeout=300)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        execution = current_tool_execution()
        if execution is not None:
            kwargs["meta"] = {
                **(kwargs.get("meta") or {}),
                EXECUTION_META_KEY: {"operation_id": str(execution.operation_id)},
            }
        result = cast(Any, await super().call_tool(name, arguments, **kwargs))
        raw_meta: object = result.meta
        if execution is not None and isinstance(raw_meta, dict):
            evidence: Any = cast(dict[str, Any], raw_meta).get(EXECUTION_META_KEY)
            if (
                isinstance(evidence, dict)
                and cast(dict[str, Any], evidence).get("operation_id")
                == str(execution.operation_id)
                and cast(dict[str, Any], evidence).get("tool_name") == name
                and cast(dict[str, Any], evidence).get("outcome") == "rejected"
            ):
                execution.outcome = "rejected"
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
) -> Any:
    """Build the small deny-by-default native toolset for a short conversation round."""

    from pydantic_ai.mcp import MCPToolset

    from app.tools import mcp_loader

    return MCPToolset(
        ExecutionEvidenceClient(
            await mcp_loader.build_agent_mcp(
                agent_id,
                runtime="internal",
                task_id=None,
                resources=resources,
                conversation_only=True,
                allowed_tool_names=allowed_tool_names,
            )
        ),
        id=f"conversation-{agent_id}",
        max_retries=1,
        cache_tools=False,
    )


async def build_agent_mcp_toolset(
    agent_id: int,
    *,
    task_id: UUID | None = None,
    eager_tool_names: set[str] | None = None,
    expected_catalog_version: str | None = None,
    resources: dict[str, Any] | None = None,
) -> Any:
    from pydantic_ai.mcp import MCPToolset
    from app.tools import mcp_loader

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
        from app.tools import (
            catalog_entry_from_definition,
            catalog_from_entries,
        )
        from app.tools.metrics import observe_catalog_snapshot

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
    from app.tools import mcp_loader

    return await mcp_loader.get_agent_mcp_servers(agent_id)


__all__ = [
    "build_agent_galaris_toolset",
    "build_agent_mcp_toolset",
    "build_conversation_toolset",
    "build_galaris_toolset",
    "get_agent_mcp_servers",
]
