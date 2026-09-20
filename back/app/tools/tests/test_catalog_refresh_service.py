from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.tools import catalog_refresh_service
from app.tools.catalog import (
    AgentToolCatalog,
    catalog_entry_from_definition,
    catalog_from_entries,
)
from app.tools.tool_search_service import ToolIndexRefreshResult


def _catalog(agent_id: int, name: str) -> AgentToolCatalog:
    return catalog_from_entries(
        agent_id=agent_id,
        runtime="internal",
        entries=[
            catalog_entry_from_definition(
                runtime="internal",
                name=name,
                description=f"Description for {name}",
                parameters_json_schema={},
            )
        ],
    )


@pytest.mark.asyncio
async def test_full_refresh_reconciles_index_only_after_complete_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog_refresh_service,
        "_agent_runtime_scopes",
        AsyncMock(return_value=[(1, "internal"), (2, "internal")]),
    )

    async def fake_build(
        agent_id: int,
        *,
        runtime: str,
        discovery_failures: set[str],
    ) -> AgentToolCatalog:
        assert runtime == "internal"
        if agent_id == 1:
            discovery_failures.add("remote_unavailable")
            return _catalog(agent_id, "search_web")
        raise RuntimeError("agent catalog failed")

    monkeypatch.setattr(
        catalog_refresh_service,
        "build_effective_tool_catalog",
        fake_build,
    )
    refresh_index = AsyncMock(
        return_value=ToolIndexRefreshResult(
            documents_indexed=1,
            embeddings_refreshed=1,
            documents_pruned=0,
            semantic_available=True,
        )
    )
    monkeypatch.setattr(
        catalog_refresh_service,
        "refresh_catalog_index",
        refresh_index,
    )

    result = await catalog_refresh_service.refresh_tool_catalogs(
        force_embeddings=True,
        prune_stale=True,
    )

    assert result.agents_scanned == 2
    assert result.agents_refreshed == 1
    assert result.agent_failures == 1
    assert result.source_failures == 1
    assert result.complete is False
    assert refresh_index.await_args.kwargs == {
        "force_embeddings": True,
        "prune_stale": False,
    }


@pytest.mark.asyncio
async def test_targeted_refresh_does_not_force_or_prune_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog_refresh_service,
        "_agent_runtime_scopes",
        AsyncMock(return_value=[(7, "internal")]),
    )
    monkeypatch.setattr(
        catalog_refresh_service,
        "build_effective_tool_catalog",
        AsyncMock(return_value=_catalog(7, "weather_forecast")),
    )
    refresh_index = AsyncMock(
        return_value=ToolIndexRefreshResult(
            documents_indexed=1,
            embeddings_refreshed=0,
            documents_pruned=0,
            semantic_available=True,
        )
    )
    monkeypatch.setattr(
        catalog_refresh_service,
        "refresh_catalog_index",
        refresh_index,
    )

    result = await catalog_refresh_service.refresh_agent_tool_catalog(7)

    assert result.complete is True
    assert refresh_index.await_args.kwargs == {
        "force_embeddings": False,
        "prune_stale": False,
    }
