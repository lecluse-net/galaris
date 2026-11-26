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
from app.services import ToolCatalogRefreshResult
from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.services.models import Service


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True], ids=["create", "update"])
async def test_ssh_configuration_survives_tool_catalog_failure(client, monkeypatch, tmp_path, existing):
    from uuid import uuid4

    import asyncssh

    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user import UserModel, auth_service, refresh_session_service

    suffix = uuid4().hex
    async with get_db_session() as db:
        privileges = list(await db.scalars(
            select(Privilege).where(Privilege.code.in_(["CONNECTION_EDIT", "AGENT_MANAGE_ALL"])),
        ))
        role = Role(code=f"ssh-editor-{suffix}", privileges=privileges)
        user = UserModel(email=f"ssh-editor-{suffix}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic SSH editor", gender="X")
        db.add_all([role, user, title])
        tool = await db.scalar(select(Service).where(Service.code == "console"))
        assert tool is not None
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        agent = Agent(user_id=user.id, title_id=title.id, code=f"ssh-editor-{suffix}", first_name="Synthetic", last_name="SSH")
        db.add(agent)
        await db.flush()
        metadata = {"agent_id": agent.id, "service_id": tool.id, "active": False}
        connection_id = None
        if existing:
            connection = Connection(**metadata)
            db.add(connection)
            await db.flush()
            connection_id = connection.id
        refresh = await refresh_session_service.create_refresh_session(user.id)
        token = await auth_service.create_access_token_for_user(
            user, session_family=await refresh_session_service.family_for_token(refresh),
        )
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(router, "refresh_agent_tool_catalog", AsyncMock(side_effect=RuntimeError("Synthetic discovery failure")))

    authorized_key = None

    class Server(asyncssh.SSHServer):
        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            return username == "synthetic" and authorized_key is not None and key == authorized_key

    def run_command(process):
        if process.command == '''printf '%s' "$HOME"''':
            process.stdout.write("/synthetic")
            process.exit(0)
        else:
            process.exit(127)

    (tmp_path / "synthetic").mkdir()
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    async with asyncssh.listen(
        "127.0.0.1", 0, server_factory=Server, server_host_keys=[host_key], process_factory=run_command,
        sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(tmp_path)),
    ) as server:
        target = {"host": "127.0.0.1", "port": server.get_port()}
        scanned = await client.post("/api/console/host-key/scan", headers=headers, json=target)
        assert scanned.status_code == 200, scanned.text
        assert scanned.json()["fingerprint"] == host_key.get_fingerprint()
        payload = {**metadata, "params": {
            "host": target["host"], "port": str(target["port"]), "username": "synthetic",
            "known_host_key": scanned.json()["key"],
        }}
        if connection_id is None:
            saved = await client.post("/api/connections", headers=headers, json=payload)
            assert saved.status_code == 201, saved.text
            connection_id = saved.json()["id"]
        else:
            saved = await client.patch(f"/api/connections/{connection_id}", headers=headers, json=payload)
            assert saved.status_code == 200, saved.text
        assert saved.json()["active"] is False
        console = f"/api/console/connections/{connection_id}"
        generated = await client.post(f"{console}/generate-key", headers=headers)
        assert generated.status_code == 200, generated.text
        authorized_key = asyncssh.import_public_key(generated.json()["public_key"])
        configured = await client.get(f"/api/connections/{connection_id}/params", headers=headers)
        assert configured.status_code == 200, configured.text
        assert configured.json()["params"]["private_key"] is None
        assert "private_key" in configured.json()["configured_params"]

        tested = await client.post(f"{console}/test", headers=headers)
        assert tested.status_code == 200, tested.text
        status = tested.json()["status"]
        assert status["authenticated"] and status["host_key_verified"] and status["home_writable"], status


@pytest.mark.asyncio
async def test_dashboard_scope_delegation_is_human_global_local_and_bounded(client):
    from uuid import uuid4
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user import UserModel, auth_service, refresh_session_service as sessions

    suffix = uuid4().hex
    async with get_db_session() as db:
        users, headers = [], []
        for index, codes in enumerate([
            ["PERMISSION_ACCESS", "CONNECTION_EDIT", "AGENT_MANAGE_ALL"],
            ["PERMISSION_ACCESS", "CONNECTION_EDIT"], ["PERMISSION_ACCESS", "AGENT_MANAGE_ALL"],
        ]):
            role = Role(code=f"scope-dashboard-{suffix}-{index}", privileges=list(await db.scalars(
                select(Privilege).where(Privilege.code.in_(codes)))))
            user = UserModel(email=f"scope-dashboard-{suffix}-{index}@example.test", hashed_password="synthetic")
            db.add_all([role, user]); await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            users.append(user)
        title = Title(label="Synthetic scope dashboard", gender="X")
        tool = await db.scalar(select(Service).where(Service.code == "contact"))
        assert tool is not None
        tool.global_params = {"services.management_scope": {"value": "all", "forced": True}}
        db.add(title); await db.flush()
        agent = Agent(user_id=users[1].id, title_id=title.id, code=f"scope-dashboard-{suffix}", first_name="Synthetic", last_name="Agent")
        db.add(agent); await db.flush()
        connection = Connection(service_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection); await db.flush()
        for user in users:
            refresh = await sessions.create_refresh_session(user.id)
            token = await auth_service.create_access_token_for_user(user, session_family=await sessions.family_for_token(refresh))
            headers.append({"Authorization": f"Bearer {token}"})
        path = f"/api/connections/{connection.id}/management-scope"
        catalog_path = f"/api/services/agents/{agent.id}/permissions"
    async def scope():
        response = await client.get(catalog_path, headers=headers[0])
        assert response.status_code == 200, response.text
        return next(row for row in response.json()["connections"] if row["service_id"] == tool.id)
    initial = await scope()
    assert initial["can_disable"] is False
    assert initial["management_scope"]["value"] == "personal"
    assert initial["management_scope"]["configured"] is None
    assert {option["value"] for option in initial["management_scope"]["options"]} == {"personal", "team", "all"}
    assert initial["parameter_sources"]["services.management_scope"] == "software"
    assert (await client.put(path, json={"value": "all"})).status_code == 401
    for actor in headers[1:]:
        assert (await client.put(path, headers=actor, json={"value": "all"})).status_code == 403
    for invalid in [{"value": "usage"}, {"value": ""}, {"value": "all", "active": False}]:
        assert (await client.put(path, headers=headers[0], json=invalid)).status_code == 422
    assert (await client.put(path, headers=headers[0], json={"value": "team"})).status_code == 204
    changed = await scope()
    assert changed["can_disable"] is False
    assert changed["management_scope"]["value"] == changed["management_scope"]["configured"] == "team"
    assert changed["parameter_sources"]["services.management_scope"] == "connection"
    # This narrow exception must not unlock any other property of a protected service.
    protected = await client.patch(f"/api/connections/{connection.id}", headers=headers[0], json={"active": False})
    assert protected.status_code == 403, protected.text
    assert (await client.put(path, headers=headers[0], json={"value": None})).status_code == 204
    assert (await scope())["management_scope"]["value"] == "personal"
    async with get_db_session():
        assert await router.connection_service.get_management_scope(agent.id, connection_id=connection.id) == "personal"


@pytest.mark.asyncio
async def test_overview_http_shows_team_connections_without_management_access(client):
    from uuid import uuid4
    from app.agent.dialogue_service import set_agent_membership
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.team import TeamModel, set_human_membership
    from core.user import UserModel, encrypt_password

    suffix = uuid4().hex
    password = "Synthetic-overview-password-123"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_ACCESS"))
        assert privilege is not None
        edit = await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_EDIT"))
        assert edit is not None
        role = Role(code=f"overview-{suffix}", privileges=[privilege, edit])
        empty_role = Role(code=f"overview-denied-{suffix}", privileges=[])
        users = [UserModel(email=f"overview-{suffix}-{index}@example.com", hashed_password=encrypt_password(password))
                 for index in range(3)]
        title = Title(label="Synthetic overview HTTP", gender="X")
        tool = Service(code=f"overview-http-{suffix}", label="Synthetic HTTP connector")
        db.add_all([role, empty_role, *users, title, tool])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=selected.id, is_default=True)
                    for user, selected in zip(users, [role, empty_role, empty_role], strict=True)])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"overview-http-{suffix}-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        connections = [Connection(agent_id=agent.id, service_id=tool.id, active=True) for agent in agents]
        db.add_all(connections)
        await db.flush()
        own, team_connection, outside = [connection.id for connection in connections]
        team = TeamModel(name="Synthetic connection team")
        db.add_all([team, ConnectionParam(connection_id=team_connection, param_name="host",
                                         param_value="private.example.test")])
        await db.flush()
        await set_human_membership(team.id, users[0].id, True)
        await set_agent_membership(team.id, agents[1].id, True)
        team_id = team.id
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
            rows = response.json()
            assert [row["id"] for row in rows] == [own, team_connection]
            assert rows[0]["managed"] and rows[0]["params"] == {}
            assert not rows[1]["managed"] and rows[1]["params"] == {} and rows[1]["configured_params"] == []
            assert (await client.get(path, headers=headers, params={"limit": 501})).status_code == 422
            diagnostic = await client.post(f"/api/connections/{own}/test", headers=headers)
            assert diagnostic.status_code == 200, diagnostic.text
            assert diagnostic.json()["status"] == "unsupported"
            detail_url = f"/api/connections/{team_connection}"
            detail = await client.get(detail_url, headers=headers)
            assert detail.status_code == 200 and detail.json()["managed"] is False
            assert (await client.get(f"/api/connections/{outside}", headers=headers)).status_code == 404
            assert (await client.get(f"{detail_url}/params", headers=headers)).status_code == 404
            assert (await client.post(f"{detail_url}/test", headers=headers)).status_code == 404
            assert (await client.patch(detail_url, headers=headers, json={"active": False})).status_code == 404
            assert (await client.delete(detail_url, headers=headers)).status_code == 404
            async with get_db_session():
                await set_human_membership(team_id, users[0].id, False)
            assert [row["id"] for row in (await client.get(path, headers=headers)).json()] == [own]
            assert (await client.get(detail_url, headers=headers)).status_code == 404
        else:
            assert (await client.post(f"/api/connections/{own}/test", headers=headers)).status_code == 403
    assert (await client.post(f"/api/connections/{own}/test")).status_code == 401


@pytest.mark.asyncio
async def test_overview_batches_parameters_preserves_scope_and_hides_historized_agents(db, monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4

    title = Title(label="Synthetic connections", gender="X")
    tool = Service(code=f"overview_{uuid4().hex}", label="Synthetic connector", connection_schema={
        "params": {"host": {"type": "string"}, "token": {"type": "password"}},
    })
    tool.icon = {"media_type": "image/svg+xml", "encoding": "text", "data": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3"/></svg>'}
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"overview-{index}-{uuid4().hex}", first_name=f"Synthetic {index}", last_name="Overview",
                    agent_driver="internal") for index in range(20)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(service_id=tool.id, agent_id=agent.id, active=index != 1)
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
    listed = await router.list_connections(service_id=tool.id, agent_id=None, active_only=False, skip=0, limit=500)
    assert connections[-1].id not in {row.id for row in listed}

    # Authorization choices also exclude historized agents, before pagination.
    # Leave an inactive connection between the historized and first live rows.
    agents[0].deleted_at = datetime.now(timezone.utc)
    await db.flush()
    options = await router.permission_connection_options(skip=0, limit=500)
    assert all(row.service_icon == tool.icon for row in options)
    assert "synthetic-legacy-secret" not in str(options)
    service_choices = await router.connection_service.connection_tool_options(include_globals=False)
    choice = next(item for item in service_choices if item["id"] == tool.id)
    assert choice["icon"] == tool.icon and choice["global_params"] == {}
    assert [row.id for row in options] == [connection.id for connection in connections[2:-1]]
    assert [row.id for row in await router.permission_connection_options(skip=0, limit=1)] == [connections[2].id]
    assert [row.id for row in await router.permission_connection_options(skip=1, limit=1)] == [connections[3].id]

    async def visible_catalogue():
        return await router.current_management_scope()

    monkeypatch.setattr(router, "current_dialogue_scope", visible_catalogue)

    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, frozenset({agents[1].id, agents[-1].id}))))
    assert [row.id for row in await router.list_connection_overviews(skip=0, limit=500)] == [connections[1].id]
    assert await router.list_connection_overviews(skip=1, limit=1) == []
    assert await router.permission_connection_options(skip=0, limit=500) == []
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, frozenset({agents[2].id, agents[-1].id}))))
    assert [row.id for row in await router.permission_connection_options(skip=0, limit=500)] == [connections[2].id]
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(7, frozenset())))
    assert await router.list_connection_overviews(skip=0, limit=500) == []
    assert await router.permission_connection_options(skip=0, limit=500) == []


@pytest.fixture(autouse=True)
def optional_tool_policy(monkeypatch, request):
    # These routing units use optional connectors. System-service refusals have DB coverage.
    if "db" not in request.fixturenames and "client" not in request.fixturenames:
        monkeypatch.setattr(router.connection_service, "require_editable_tool", AsyncMock())


@pytest.mark.asyncio
async def test_list_connections_uses_stable_bounded_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    expected = [
        Connection(id=501, service_id=35, agent_id=1, active=True),
        Connection(id=502, service_id=35, agent_id=2, active=True),
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
        service_id=None,
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
        "sync_integrated_service_connections",
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
    monkeypatch.setattr(router, "_require_permission_state", AsyncMock())
    connection = Connection(id=11, service_id=35, agent_id=7, active=True)
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
    monkeypatch.setattr(router, "_require_permission_state", AsyncMock())
    connection = Connection(id=11, service_id=35, agent_id=7, active=True)
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
        "set_service_function_state",
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
    monkeypatch.setattr(router, "_require_permission_state", AsyncMock())
    title = Title(label="Synthetic policy", gender="X")
    tool = Service(code="synthetic-policy", label="Synthetic policy")
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"synthetic-policy-{index}",
                    first_name="Synthetic", last_name=f"Policy {index}", agent_driver="internal")
              for index in range(2)]
    db.add_all(agents)
    await db.flush()
    connections = [Connection(service_id=tool.id, agent_id=agent.id, active=True) for agent in agents]
    db.add_all(connections)
    await db.commit()
    selected, other = connections
    name = "synthetic://policy" if capability_kind == "resource" else "synthetic_read"
    other_kind: CapabilityKind = "resource" if capability_kind == "tool" else "tool"
    await router.connection_service.set_service_function_state(tool.id, name, "enabled", capability_kind=capability_kind)
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
