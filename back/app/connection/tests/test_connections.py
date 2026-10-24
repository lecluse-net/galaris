"""Tests for connection REST endpoints using the EAV architecture."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..models import Connection, ConnectionFunctionState, ConnectionParam
from .. import router
from ..router import list_connections
from ..schemas import CapabilityKind, FunctionState, FunctionStateUpdate
from app.tools import ToolCatalogRefreshResult
from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.tools.models import Tool


@pytest.mark.asyncio
async def test_overview_http_requires_privileges_and_limits_rows_to_managed_agents(client):
    from uuid import uuid4
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user import UserModel, encrypt_password

    suffix = uuid4().hex
    password = "Synthetic-overview-password-123"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_ACCESS"))
        assert privilege is not None
        role = Role(code=f"overview-{suffix}", privileges=[privilege])
        empty_role = Role(code=f"overview-denied-{suffix}", privileges=[])
        users = [UserModel(email=f"overview-{suffix}-{index}@example.com", hashed_password=encrypt_password(password))
                 for index in range(2)]
        title = Title(label="Synthetic overview HTTP", gender="X")
        tool = Tool(code=f"overview-http-{suffix}", label="Synthetic HTTP connector")
        db.add_all([role, empty_role, *users, title, tool])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=selected.id, is_default=True)
                    for user, selected in zip(users, [role, empty_role], strict=True)])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"overview-http-{suffix}-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        connections = [Connection(agent_id=agent.id, tool_id=tool.id, active=True) for agent in agents]
        db.add_all(connections)
        await db.flush()
        expected = connections[0].id
    path = "/api/connections/overview"
    assert (await client.get(path)).status_code == 401
    for index, expected_status in enumerate([200, 403]):
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": users[index].email, "password": password})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.get(path, headers=headers)
        assert response.status_code == expected_status, response.text
        if expected_status == 200:
            assert [row["id"] for row in response.json()] == [expected]
            assert response.json()[0]["params"] == {}
            assert (await client.get(path, headers=headers, params={"limit": 501})).status_code == 422


@pytest.mark.asyncio
async def test_overview_batches_parameters_preserves_scope_and_hides_historized_agents(db, monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4

    title = Title(label="Synthetic connections", gender="X")
    tool = Tool(code=f"overview_{uuid4().hex}", label="Synthetic connector", connection_schema={
        "params": {"host": {"type": "string"}, "token": {"type": "password"}},
    })
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"overview-{index}-{uuid4().hex}", first_name=f"Synthetic {index}", last_name="Overview",
                    agent_driver="internal") for index in range(20)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(tool_id=tool.id, agent_id=agent.id, active=index != 1)
                   for index, agent in enumerate(agents)]
    db.add_all(connections)
    await db.flush()
    for connection in connections:
        db.add_all([
            ConnectionParam(connection_id=connection.id, param_name="host", param_value="synthetic.example.test"),
            ConnectionParam(connection_id=connection.id, param_name="token", param_value="synthetic-legacy-secret"),
        ])
    await db.flush()
    queries = []

    def count_queries(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    bind = (await db.connection()).sync_connection
    event.listen(bind, "before_cursor_execute", count_queries)
    try:
        # Compare the former per-row read with the page projection under identical data.
        for connection in connections:
            await router.connection_service.get_params_for_api(connection.id)
        previous_count = len(queries)
        queries.clear()
        monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, None)))
        overview = await router.list_connection_overviews(skip=0, limit=500)
        batch_count = len(queries)
        assert batch_count <= 3
        assert previous_count >= len(connections) * 3
    finally:
        event.remove(bind, "before_cursor_execute", count_queries)

    rows = {row.id: row for row in overview}
    assert set(rows) == {connection.id for connection in connections}
    assert rows[connections[1].id].active is False
    assert rows[connections[0].id].params == {"host": "synthetic.example.test", "token": None}
    assert rows[connections[0].id].configured_params == ["token"]
    assert "synthetic-legacy-secret" not in str(overview)

    # A fresh snapshot includes changed and removed parameters, even in the same session.
    await db.execute(ConnectionParam.__table__.update().where(
        ConnectionParam.connection_id == connections[0].id, ConnectionParam.param_name == "host",
    ).values(param_value="updated.example.test"))
    await db.execute(ConnectionParam.__table__.delete().where(
        ConnectionParam.connection_id == connections[0].id, ConnectionParam.param_name == "token",
    ))
    agents[-1].deleted_at = datetime.now(timezone.utc)
    await db.flush()
    overview = await router.list_connection_overviews(skip=0, limit=500)
    assert connections[-1].id not in {row.id for row in overview}
    assert overview[0].params == {"host": "updated.example.test"}
    assert overview[0].configured_params == []
    listed = await router.list_connections(tool_id=tool.id, agent_id=None, active_only=False, skip=0, limit=500)
    assert connections[-1].id not in {row.id for row in listed}

    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, frozenset({agents[1].id, agents[-1].id}))))
    assert [row.id for row in await router.list_connection_overviews(skip=0, limit=500)] == [connections[1].id]
    assert await router.list_connection_overviews(skip=1, limit=1) == []
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, frozenset())))
    assert await router.list_connection_overviews(skip=0, limit=500) == []


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
    result.all.return_value = expected
    db.scalars.return_value = result
    monkeypatch.setattr(router.connection_service, "get_db", lambda: db)
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
    )

    assert rows == expected
    statement = db.scalars.await_args.args[0]
    sql = str(statement)
    assert "connections.active IS true" in sql
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
