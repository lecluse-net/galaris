"""Explicit reconciliation of live MCP catalogs and their shared search index."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select

from core.database import get_db

from .catalog import AgentToolCatalog, build_effective_tool_catalog
from .tool_search_service import refresh_catalog_index


@dataclass(frozen=True)
class ToolCatalogRefreshResult:
    agents_scanned: int
    agents_refreshed: int
    agent_failures: int
    source_failures: int
    tools_discovered: int
    documents_indexed: int
    embeddings_refreshed: int
    documents_pruned: int
    semantic_available: bool
    degradation_reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.agent_failures == 0 and self.source_failures == 0


async def _agent_runtime_scopes(
    agent_ids: Collection[int] | None,
) -> list[tuple[int, str]]:
    from app.agent.models import Agent

    query = select(Agent.id, Agent.agent_driver).order_by(Agent.id)
    query = Agent.histo_filter(query)
    if agent_ids is not None:
        if not agent_ids:
            return []
        query = query.where(Agent.id.in_(sorted(agent_ids)))
    rows = await get_db().execute(query)
    return [(int(row[0]), str(row[1] or "internal")) for row in rows.all()]


async def refresh_tool_catalogs(
    *,
    agent_ids: Collection[int] | None = None,
    force_embeddings: bool,
    prune_stale: bool,
) -> ToolCatalogRefreshResult:
    """Reload remote definitions, rebuild effective catalogs and reconcile the index."""

    from app.agent import validate_agent_driver

    scopes = await _agent_runtime_scopes(agent_ids)
    catalogs: list[AgentToolCatalog] = []
    agent_failures = 0
    source_failures = 0
    for agent_id, configured_runtime in scopes:
        failures: set[str] = set()
        try:
            runtime = validate_agent_driver(
                configured_runtime,
                require_available=False,
            )
            catalog = await build_effective_tool_catalog(
                agent_id,
                runtime=runtime,
                discovery_failures=failures,
            )
        except Exception:
            agent_failures += 1
            logger.exception(
                "Tool catalog refresh failed for agent {}",
                agent_id,
            )
            continue
        catalogs.append(catalog)
        source_failures += len(failures)
        if failures:
            logger.warning(
                "Tool catalog refresh for agent {} skipped {} unavailable "
                "external source(s)",
                agent_id,
                len(failures),
            )

    complete_discovery = agent_failures == 0 and source_failures == 0
    index_result = await refresh_catalog_index(
        catalogs,
        force_embeddings=force_embeddings,
        prune_stale=(
            prune_stale
            and bool(scopes)
            and complete_discovery
        ),
    )
    result = ToolCatalogRefreshResult(
        agents_scanned=len(scopes),
        agents_refreshed=len(catalogs),
        agent_failures=agent_failures,
        source_failures=source_failures,
        tools_discovered=sum(len(catalog.entries) for catalog in catalogs),
        documents_indexed=index_result.documents_indexed,
        embeddings_refreshed=index_result.embeddings_refreshed,
        documents_pruned=index_result.documents_pruned,
        semantic_available=index_result.semantic_available,
        degradation_reason=index_result.degradation_reason,
    )
    logger.info(
        "Tool catalogs refreshed: agents={}/{}, sources_failed={}, "
        "tools={}, documents={}, embeddings={}, pruned={}",
        result.agents_refreshed,
        result.agents_scanned,
        result.source_failures,
        result.tools_discovered,
        result.documents_indexed,
        result.embeddings_refreshed,
        result.documents_pruned,
    )
    return result


async def refresh_agent_tool_catalog(
    agent_id: int,
) -> ToolCatalogRefreshResult:
    """Targeted reconciliation after a connection or authorization change."""

    return await refresh_tool_catalogs(
        agent_ids={agent_id},
        force_embeddings=False,
        prune_stale=False,
    )


async def refresh_agents_tool_catalogs(
    agent_ids: Sequence[int],
) -> ToolCatalogRefreshResult:
    return await refresh_tool_catalogs(
        agent_ids=set(agent_ids),
        force_embeddings=False,
        prune_stale=False,
    )


async def refresh_all_tool_catalogs() -> ToolCatalogRefreshResult:
    """Force a complete remote reload and full index reconciliation."""

    return await refresh_tool_catalogs(
        force_embeddings=True,
        prune_stale=True,
    )


__all__ = [
    "ToolCatalogRefreshResult",
    "refresh_agent_tool_catalog",
    "refresh_agents_tool_catalogs",
    "refresh_all_tool_catalogs",
    "refresh_tool_catalogs",
]
