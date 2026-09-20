"""Tests for connection REST endpoints using the EAV architecture."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection
from .. import router
from ..router import list_connections
from ..schemas import FunctionStateUpdate
from app.tools import ToolCatalogRefreshResult
from app.agent import AgentManagementScope


@pytest.fixture(autouse=True)
def optional_tool_policy(monkeypatch):
    # These routing units use optional connectors. System-service refusals have DB coverage.
    monkeypatch.setattr(router.connection_service, "require_editable_tool", AsyncMock())


@pytest.mark.asyncio
async def test_list_connections_uses_stable_bounded_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    expected = [
        Connection(id=501, tool_id=35, agent_id=1, active=True),
        Connection(id=502, tool_id=35, agent_id=2, active=True),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = expected
    db.execute.return_value = result
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, None)),
    )

    rows = await list_connections(
        tool_id=None,
        agent_id=None,
        active_only=True,
        skip=500,
        limit=500,
        db=db,
    )

    assert rows == expected
    statement = db.execute.await_args.args[0]
    sql = str(statement)
    assert "connections.active = true" in sql
    assert "ORDER BY connections.id" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql
    assert sorted(statement.compile().params.values()) == [500, 500]


@pytest.mark.asyncio
async def test_unified_refresh_syncs_connections_and_rebuilds_catalogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(router, "get_db", lambda: db)
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, None)),
    )
    monkeypatch.setattr(
        router,
        "sync_integrated_tool_connections",
        AsyncMock(return_value=2),
    )
    monkeypatch.setattr(
        router,
        "refresh_all_tool_catalogs",
        AsyncMock(
            return_value=ToolCatalogRefreshResult(
                agents_scanned=3,
                agents_refreshed=3,
                agent_failures=0,
                source_failures=0,
                tools_discovered=120,
                documents_indexed=45,
                embeddings_refreshed=45,
                documents_pruned=4,
                semantic_available=True,
            )
        ),
    )

    result = await router._refresh_connections_and_tool_catalogs()  # pyright: ignore[reportPrivateUsage]

    assert result.created == 2
    assert result.agents_refreshed == 3
    assert result.documents_indexed == 45
    assert result.complete is True
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_connection_function_update_refreshes_affected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(id=11, tool_id=35, agent_id=7, active=True)
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, frozenset({7}))),
    )
    monkeypatch.setattr(
        router.connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    set_state = AsyncMock()
    monkeypatch.setattr(
        router.connection_service,
        "set_connection_function_state",
        set_state,
    )
    monkeypatch.setattr(
        router.connection_service,
        "resolve_function",
        AsyncMock(
            return_value={
                "name": "remote_search",
                "connection_state": "disabled",
                "global_state": "default",
                "effective": False,
            }
        ),
    )
    refresh = AsyncMock()
    monkeypatch.setattr(router, "_refresh_agent_indexes", refresh)

    result = await router.set_connection_function(
        11,
        "remote_search",
        FunctionStateUpdate(state="disabled"),
    )

    assert result.effective is False
    set_state.assert_awaited_once_with(11, "remote_search", "disabled")
    refresh.assert_awaited_once_with([7])


@pytest.mark.asyncio
async def test_global_function_update_refreshes_every_connected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Connection(id=11, tool_id=35, agent_id=7, active=True)
    monkeypatch.setattr(
        router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, None)),
    )
    monkeypatch.setattr(
        router.connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    monkeypatch.setattr(
        router.connection_service,
        "set_tool_function_state",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router.connection_service,
        "resolve_function",
        AsyncMock(
            return_value={
                "name": "remote_search",
                "connection_state": "default",
                "global_state": "disabled",
                "effective": False,
            }
        ),
    )
    monkeypatch.setattr(
        router.connection_service,
        "get_agent_ids_by_tool",
        AsyncMock(return_value=[2, 7, 9]),
    )
    refresh = AsyncMock()
    monkeypatch.setattr(router, "_refresh_agent_indexes", refresh)

    result = await router.set_connection_function_global(
        11,
        "remote_search",
        FunctionStateUpdate(state="disabled"),
    )

    assert result.effective is False
    refresh.assert_awaited_once_with([2, 7, 9])
