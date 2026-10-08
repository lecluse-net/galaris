"""Tests for connection REST endpoints using the EAV architecture."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..models import Connection, ConnectionFunctionState
from .. import router
from ..router import list_connections
from ..schemas import CapabilityKind, FunctionState, FunctionStateUpdate
from app.tools import ToolCatalogRefreshResult
from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.tools.models import Tool


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
async def test_connection_function_update_does_not_wait_for_catalog_discovery(
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
    set_state.assert_awaited_once_with(11, "remote_search", "disabled", capability_kind="tool")
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_function_update_does_not_wait_for_catalog_discovery(
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
    refresh.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("capability_kind", ["tool", "resource", "prompt"])
@pytest.mark.parametrize("state", ["enabled", "ask", "disabled"])
async def test_global_choice_inherits_only_selected_connection_atomically(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capability_kind: CapabilityKind,
    state: FunctionState,
) -> None:
    title = Title(label="Synthetic policy", gender="X")
    tool = Tool(code="synthetic-policy", label="Synthetic policy")
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"synthetic-policy-{index}",
                    first_name="Synthetic", last_name=f"Policy {index}", agent_driver="internal")
              for index in range(2)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(tool_id=tool.id, agent_id=agent.id, active=True) for agent in agents]
    db.add_all(connections)
    await db.commit()
    selected, other = connections
    name = "synthetic://policy" if capability_kind == "resource" else "synthetic_read"
    other_kind: CapabilityKind = "resource" if capability_kind == "tool" else "tool"
    await router.connection_service.set_tool_function_state(tool.id, name, "enabled", capability_kind=capability_kind)
    for connection, mode in [(selected, "disabled"), (other, "ask")]:
        await router.connection_service.set_connection_function_state(connection.id, name, mode, capability_kind=capability_kind)
    await router.connection_service.set_connection_function_state(selected.id, name, "disabled", capability_kind=other_kind)
    await router.connection_service.set_connection_function_state(selected.id, "synthetic_other", "disabled", capability_kind=capability_kind)
    refresh = AsyncMock()
    monkeypatch.setattr(router, "_refresh_agent_indexes", refresh)
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, frozenset({selected.agent_id}))))
    update = router.CapabilityStateUpdate(function_name=name, state=state, capability_kind=capability_kind,
                                          global_policy=True, inherit_connection=True)
    with pytest.raises(HTTPException) as denied:
        await router.set_capability_policy(selected.id, update)
    assert denied.value.status_code == 403
    initial = await router.connection_service.resolve_function(selected, name, capability_kind=capability_kind)
    assert (initial["global_state"], initial["connection_state"]) == ("enabled", "disabled")

    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, None)))
    legacy = await router.set_capability_policy(selected.id, update.model_copy(update={"inherit_connection": False}))
    assert legacy.connection_state == "disabled" and legacy.local_override_count == 2
    for _ in range(2):
        result = await router.set_capability_policy(selected.id, update)
        assert (result.global_state, result.connection_state, result.effective_state) == (state, "default", state)
        assert result.local_override_count == 1
        assert (await router.connection_service.resolve_function(other, name, capability_kind=capability_kind))["connection_state"] == "ask"
        assert (await router.connection_service.resolve_function(selected, name, capability_kind=other_kind))["connection_state"] == "disabled"
        assert (await router.connection_service.resolve_function(selected, "synthetic_other", capability_kind=capability_kind))["connection_state"] == "disabled"

    # Fail only once the local override has been removed: an intermediate global
    # commit would leak the new global rule and make the rollback assertion fail.
    selected_id = selected.id
    await router.connection_service.set_connection_function_state(selected_id, name, "disabled", capability_kind=capability_kind)
    def reject_commit_after_reset(session: Session) -> None:
        local = session.scalar(select(ConnectionFunctionState).where(
            ConnectionFunctionState.connection_id == selected_id,
            ConnectionFunctionState.function_name == name,
            ConnectionFunctionState.capability_kind == capability_kind,
        ))
        if local is None:
            raise RuntimeError("Synthetic policy commit failure")

    event.listen(db.sync_session, "before_commit", reject_commit_after_reset)
    try:
        failing = update.model_copy(update={"state": "disabled" if state == "enabled" else "enabled"})
        with pytest.raises(RuntimeError, match="Synthetic policy commit failure"):
            await router.set_capability_policy(selected_id, failing)
    finally:
        event.remove(db.sync_session, "before_commit", reject_commit_after_reset)
        await db.rollback()
    await db.refresh(selected)
    preserved = await router.connection_service.resolve_function(selected, name, capability_kind=capability_kind)
    assert (preserved["global_state"], preserved["connection_state"]) == (state, "disabled")
