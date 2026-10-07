"""Synthetic ToolAdmin journeys use real persistence and replace no domain service."""

import asyncio
import json
import socket
from uuid import uuid4
from uuid import UUID

import pytest
import pytest_asyncio
import uvicorn
from fastmcp import FastMCP, Client
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import connection_service
from app.connection.models import Connection, ConnectionParam
from app.connection import mcp as connection_mcp
from app.tools import mcp, mandatory_tools, tool_service, admin_service
from app.tools.admin_candidates import prepare_candidate, resolve_candidate
from app.tools.admin_contracts import AdministrationContext, AdministrationError, CandidateRequest
from app.tools.models import Tool
from app.tools.mcp_loader import McpToolContext, build_agent_galaris_fastmcp, build_agent_mcp
from app.tools.schemas import ConnectionParamDef, ToolCreate, ToolGlobalParamsUpdate
from core.database import get_db_session
from core.user.models import User


@pytest_asyncio.fixture
async def delegated(db):
    title = Title(label="Synthetic Tool operator", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"tool-operator-{uuid4().hex}", first_name=name,
                    last_name="Synthetic", agent_driver="internal") for name in ("Operator", "Recipient")]
    db.add_all(agents)
    await db.flush()
    tool = await db.scalar(select(Tool).where(Tool.code == "tool_admin"))
    assert tool is not None
    grant = Connection(tool_id=tool.id, agent_id=agents[0].id, active=True)
    db.add(grant)
    await db.flush()
    # Exercise domain behavior under an explicit human function policy; the
    # one-use MCP approval boundary has its own real persistence scenarios.
    from app.tools.mcp_loader import load_mcp_tools
    for definition in load_mcp_tools():
        if definition.tool_code == "tool_admin":
            await connection_service.set_connection_function_state(grant.id, definition.name, "enabled")
    await db.commit()
    return McpToolContext(agents[0].id, "internal"), agents[1].id, grant.id


def result(value):
    data = json.loads(value)
    assert data["success"], data
    return data


@pytest.mark.parametrize("definition", [
    {"options": [{"value": ""}]},
    {"options": [{"value": "one"}, {"value": "one"}]},
    {"default": "other", "options": [{"value": "one"}]},
    {"type": "password", "options": [{"value": "one"}]},
    {"type": "integer", "options": [{"value": "text"}]},
])
def test_invalid_fixed_choices_are_rejected(definition):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ConnectionParamDef.model_validate(definition)


@pytest.mark.asyncio
async def test_parameter_labels_choices_and_yaml_roundtrip(delegated, db):
    _, recipient, _ = delegated
    definition = {"type": "string", "label": "Service region", "default": "eu",
                  "options": [{"value": "eu", "label": "Europe"}, {"value": "us", "label": "United States"}]}
    record = await tool_service.create_tool(ToolCreate.model_validate({
        "code": f"synthetic_{uuid4().hex}", "label": "Fixed choices",
        "connection_schema": {"params": {"region": definition, "legacy": {"type": "string"}}},
    }))
    loaded = await tool_service.get_tool_by_id(record.id)
    assert loaded is not None
    assert loaded.connection.params["region"].label == "Service region"
    assert loaded.connection.params["legacy"].options == []
    exported = tool_service.serialize_to_yaml(record)
    imported, created = await tool_service.import_from_yaml_string(exported, overwrite=True)
    assert not created
    assert imported.connection_schema["params"]["region"]["options"] == definition["options"]
    assert imported.connection_schema["params"]["region"]["label"] == "Service region"
    connection = Connection(tool_id=record.id, agent_id=recipient, active=False)
    db.add(connection)
    await db.commit()
    await connection_service.set_params_bulk(connection.id, {"region": "us", "legacy": "free text"})
    assert await connection_service.get_param(connection.id, "region") == "us"
    with pytest.raises(ValueError, match="fixed options"):
        await connection_service.set_params_bulk(connection.id, {"legacy": "must not persist", "region": "other"})
    assert await connection_service.get_param(connection.id, "legacy") == "free text"
    await tool_service.update_global_params(record.id, ToolGlobalParamsUpdate.model_validate({"params": {"region": {"value": "us"}}}))
    with pytest.raises(ValueError, match="fixed options"):
        await tool_service.update_global_params(record.id, ToolGlobalParamsUpdate.model_validate({"params": {"region": {"value": "other"}}}))
    globals_, _ = await tool_service.get_runtime_global_params(record.id)
    assert globals_["region"] == "us"


@pytest.mark.asyncio
async def test_tool_connection_lifecycle_and_conflicts(delegated, db):
    ctx, recipient, _ = delegated
    created = result(await mcp.tool_admin_create(ctx, definition={
        "code": f"synthetic_{uuid4().hex}", "label": "Synthetic custom integration",
        "connection_schema": {"params": {"count": {"type": "integer", "default": "2"}, "token": {"type": "password"}}},
    }))
    tool_id, version = created["tool"]["id"], created["version"]
    for capability in ("mcp", "task", "file_share", "messenger", "listener"):
        filtered = result(await mcp.tool_admin_list(ctx, search=created["tool"]["code"], capability=capability))
        assert filtered["total"] == 0
    assert result(await mcp.tool_admin_list(ctx, search="tool_admin", capability="mcp"))["total"] == 1
    changed = result(await mcp.tool_admin_global_params_set(ctx, tool_id, {"count": {"value": "3"}}, version))
    stale = json.loads(await mcp.tool_admin_update(ctx, tool_id, {"label": "Stale"}, version))
    assert stale["error"]["kind"] == "conflict"
    connected = result(await connection_mcp.tool_admin_connection_create(ctx, tool_id, recipient, changed["version"]))
    connection_id = connected["connection"]["id"]
    assert connected["connection"]["active"] is False
    assert connected["connection"]["effective_params"]["count"]["value"] == "3"
    current = result(await mcp.tool_admin_get(ctx, tool_id))
    duplicate = json.loads(await connection_mcp.tool_admin_connection_create(ctx, tool_id, recipient, current["version"]))
    assert duplicate["error"]["kind"] == "conflict"
    blocked = json.loads(await mcp.tool_admin_delete(ctx, tool_id, current["version"]))
    assert blocked["error"]["kind"] == "dependencies_blocking"
    patched = result(await connection_mcp.tool_admin_connection_params_set(ctx, connection_id,
                     {"count": {"value": "4"}}, connected["version"]))
    assert patched["connection"]["effective_params"]["count"]["origin"] == "local"
    inherited = result(await connection_mcp.tool_admin_connection_param_delete(ctx, connection_id, "count", patched["version"]))
    assert inherited["connection"]["effective_params"]["count"]["value"] == "3"
    active = result(await connection_mcp.tool_admin_connection_update(ctx, connection_id, True, inherited["version"]))
    revoked = result(await connection_mcp.tool_admin_connection_function_set(ctx, connection_id, "lookup", "disabled", active["version"]))
    assert revoked["function"]["effective"] is False
    global_state = result(await mcp.tool_admin_get(ctx, tool_id))
    await mcp.tool_admin_function_set(ctx, tool_id, "lookup", "disabled", global_state["version"])
    current_connection = result(await connection_mcp.tool_admin_connection_get(ctx, connection_id))
    overridden = result(await connection_mcp.tool_admin_connection_function_set(ctx, connection_id, "lookup", "enabled", current_connection["version"]))
    assert overridden["function"]["global_state"] == "disabled"
    assert overridden["function"]["effective"] is True
    deleted = result(await connection_mcp.tool_admin_connection_delete(ctx, connection_id, overridden["version"]))
    assert deleted["persisted"]
    assert await db.get(Connection, connection_id) is None
    current = result(await mcp.tool_admin_get(ctx, tool_id))
    result(await mcp.tool_admin_delete(ctx, tool_id, current["version"]))
    assert await db.get(Tool, tool_id) is None


@pytest.mark.asyncio
async def test_direct_tool_dependencies_are_visible_and_block_deletion(delegated, db):
    from app.process.models import ProcessDefinition
    from app.messenger.models import MessengerUser

    ctx, _, _ = delegated
    created = result(await mcp.tool_admin_create(ctx, definition={
        "code": f"referenced_{uuid4().hex}", "label": "Synthetic referenced Tool",
    }))
    tool_id = created["tool"]["id"]
    workflow = ProcessDefinition(tool_id=tool_id, engine_process_id="synthetic-workflow", label="Synthetic workflow")
    identity = MessengerUser(tool_id=tool_id, external_id="synthetic-identity", display_name="Synthetic identity")
    db.add_all([workflow, identity])
    await db.commit()
    workflow_id, identity_id = workflow.id, identity.id
    impact = result(await mcp.tool_admin_impact(ctx, tool_id))
    assert impact["deletion_blocked"]
    assert {row["table"] for row in impact["references"]["items"]} == {"process_definitions", "messenger_users"}
    assert impact["version"] != created["version"]
    assert json.loads(await mcp.tool_admin_delete(ctx, tool_id, created["version"]))["error"]["kind"] == "conflict"
    blocked = json.loads(await mcp.tool_admin_delete(ctx, tool_id, impact["version"]))
    assert blocked["error"]["kind"] == "dependencies_blocking"
    with pytest.raises(ValueError):
        await tool_service.delete_tool(tool_id)
    assert await db.get(ProcessDefinition, workflow_id) is not None
    assert await db.get(MessengerUser, identity_id) is not None
    assert await db.get(Tool, tool_id) is not None


@pytest.mark.asyncio
async def test_batches_are_atomic_and_secret_literals_never_replace_values(delegated, db):
    ctx, recipient, _ = delegated
    created = result(await mcp.tool_admin_create(ctx, definition={"code": f"synthetic_{uuid4().hex}", "label": "Atomic",
        "connection_schema": {"params": {"first": {"type": "string"}, "count": {"type": "integer"}, "token": {"type": "password"}}}}))
    tool_id = created["tool"]["id"]
    connected = result(await connection_mcp.tool_admin_connection_create(ctx, tool_id, recipient, created["version"]))
    identifier = connected["connection"]["id"]
    with pytest.raises(ValueError):
        await connection_service.set_params_bulk(identifier, {"first": "must-not-persist", "count": "invalid"})
    assert (await connection_service.get_params_for_api(identifier))[1] == {}
    await connection_service.set_param(identifier, "token", "synthetic-secret-rotate-001")
    from core.util import SECRET_MASK
    await connection_service.set_param(identifier, "token", SECRET_MASK)
    assert await connection_service.get_param(identifier, "token") == "synthetic-secret-rotate-001"
    current = result(await connection_mcp.tool_admin_connection_get(ctx, identifier))
    assert "synthetic-secret" not in json.dumps(current)
    assert current["connection"]["effective_params"]["token"]["configured"]
    rejected = json.loads(await connection_mcp.tool_admin_connection_params_set(ctx, identifier,
                        {"token": {"value": "replacement"}}, current["version"]))
    assert rejected["error"]["kind"] == "configuration_invalid"
    assert await connection_service.get_param(identifier, "token") == "synthetic-secret-rotate-001"
    state = result(await mcp.tool_admin_get(ctx, tool_id))
    forced = result(await mcp.tool_admin_global_params_set(ctx, tool_id, {"count": {"value": "7", "forced": True}}, state["version"]))
    assert forced["tool"]["global_params"]["count"]["forced"]
    with pytest.raises(ValueError):
        await connection_service.set_params_bulk(identifier, {"first": "also-not-persisted", "count": "8"})
    assert "first" not in (await connection_service.get_params_for_api(identifier))[1]


@pytest.mark.asyncio
async def test_delegation_cannot_be_self_assigned_and_sync_preserves_disable(delegated, db):
    ctx, _, grant_id = delegated
    for code in ("tool_admin", "agent_admin", "galaris_admin", "process_admin", "goal_management", "console", "galaris"):
        tool = await db.scalar(select(Tool).where(Tool.code == code))
        before = result(await mcp.tool_admin_get(ctx, tool.id))
        denied = json.loads(await mcp.tool_admin_conversation_set(ctx, tool.id, True, before["version"]))
        assert denied["error"]["kind"] == "access_denied"
    await connection_service.set_connection_function_state(grant_id, "tool_admin_list", "disabled")
    denied = json.loads(await mcp.tool_admin_list(ctx))
    assert denied["error"]["kind"] == "access_denied"
    await connection_service.set_connection_active(grant_id, False)
    await mandatory_tools.sync_integrated_tool_connections(ctx.agent_id)
    assert not (await connection_service.get_connection(grant_id)).active
    assert not (await db.scalar(select(Tool).where(Tool.code == "tool_admin"))).conversation_enabled


@pytest_asyncio.fixture
async def existing_stdio(delegated, db):
    ctx, recipient, _ = delegated
    tool = Tool(code=f"stdio_{uuid4().hex}", label="Synthetic executable",
                mcp_config={"type": "stdio", "command": "synthetic-never-run", "args": ["synthetic-args"], "env": {"VALUE": "synthetic-env"}},
                connection_schema={"params": {"script": {"type": "string", "default": "synthetic-default"}}},
                global_params={"script": {"value": "synthetic-global", "forced": False}})
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=recipient, active=False)
    db.add(connection)
    await db.flush()
    db.add(ConnectionParam(connection_id=connection.id, param_name="script", param_value="synthetic-local"))
    await db.commit()
    return ctx, tool.id, connection.id, recipient


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["definition", "global_params", "conversation", "function", "connection", "local_params", "create_connection"])
async def test_existing_stdio_is_read_only(existing_stdio, operation):
    ctx, tool_id, connection_id, _ = existing_stdio
    current = result(await mcp.tool_admin_get(ctx, tool_id))
    connected = result(await connection_mcp.tool_admin_connection_get(ctx, connection_id))
    version, local_version = current["version"], connected["version"]
    calls = {
        "definition": lambda: mcp.tool_admin_update(ctx, tool_id, {"label": "Changed"}, version),
        "global_params": lambda: mcp.tool_admin_global_params_set(ctx, tool_id, {"script": {"value": "Changed"}}, version),
        "conversation": lambda: mcp.tool_admin_conversation_set(ctx, tool_id, True, version),
        "function": lambda: mcp.tool_admin_function_set(ctx, tool_id, "lookup", "disabled", version),
        "connection": lambda: connection_mcp.tool_admin_connection_update(ctx, connection_id, False, local_version),
        "local_params": lambda: connection_mcp.tool_admin_connection_params_set(ctx, connection_id, {"script": {"value": "Changed"}}, local_version),
        "create_connection": lambda: connection_mcp.tool_admin_connection_create(ctx, tool_id, ctx.agent_id, version),
    }
    denied = json.loads(await calls[operation]())
    assert denied["error"]["kind"] == "access_denied"
    assert result(await mcp.tool_admin_get(ctx, tool_id))["version"] == version
    assert result(await connection_mcp.tool_admin_connection_get(ctx, connection_id))["version"] == local_version


@pytest.mark.asyncio
async def test_stdio_configuration_is_redacted_and_refresh_never_launches_it(existing_stdio, db, monkeypatch):
    from app.tools import mcp_loader

    ctx, tool_id, connection_id, recipient = existing_stdio
    current = result(await mcp.tool_admin_get(ctx, tool_id))
    connected = result(await connection_mcp.tool_admin_connection_get(ctx, connection_id))
    encoded = json.dumps([current, connected])
    for literal in ("synthetic-never-run", "synthetic-args", "synthetic-env", "synthetic-default", "synthetic-global", "synthetic-local"):
        assert literal not in encoded
    assert current["tool"]["mcp_config"]["type"] == "stdio"
    assert current["allowed_actions"] == []
    connection = await db.get(Connection, connection_id)
    connection.active = True
    await db.commit()
    attempts = []

    def refuse_transport(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("An administrative refresh must not construct an executable transport")

    monkeypatch.setattr(mcp_loader, "_external_transport", refuse_transport)
    refreshed = result(await mcp.tool_admin_catalog_refresh(ctx, tool_id=tool_id))
    assert not attempts
    assert not refreshed["refresh"]["complete"]
    batch = await admin_service.refresh_batch([recipient], actor=AdministrationContext(
        agent_id=ctx.agent_id, function_name="tool_admin_catalog_refresh"))
    assert not attempts
    assert not batch["complete"] and batch["source_failures"] == 1
    assert batch["documents_pruned"] == 0


@pytest_asyncio.fixture(params=["http", "sse"])
async def synthetic_mcp(request, monkeypatch):
    from sse_starlette.sse import AppStatus

    # Each fixture starts a new server in the same process. SSE's shutdown
    # watcher can retain the preceding server's exit flag between test loops.
    monkeypatch.setattr(AppStatus, "should_exit", False)
    transport = request.param
    server = FastMCP("Synthetic diagnostics")
    class CapturedCalls(list):
        headers = []
    calls = CapturedCalls()
    calls.server = server

    @server.tool()
    async def lookup(value: str = "") -> str:
        """Read a synthetic value."""
        from fastmcp.server.dependencies import get_http_request
        calls.headers.append(get_http_request().headers.get("authorization"))
        calls.append(value)
        return value

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    path = "/sse" if transport == "sse" else "/mcp"
    url = f"http://127.0.0.1:{sock.getsockname()[1]}{path}"
    application = uvicorn.Server(uvicorn.Config(server.http_app(transport=transport, path=path),
        log_level="error", lifespan="on", timeout_graceful_shutdown=1))
    task = asyncio.create_task(application.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not application.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield url, calls
    finally:
        application.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


@pytest.mark.asyncio
async def test_mcp_server_recovers_after_previous_server_exit(previous_server_exit, synthetic_mcp):
    url, _calls = synthetic_mcp
    async with Client(url) as client:
        assert 'lookup' in {tool.name for tool in await client.list_tools()}


@pytest.fixture
def previous_server_exit(monkeypatch):
    from sse_starlette.sse import AppStatus
    monkeypatch.setattr(AppStatus, 'should_exit', True)


@pytest.mark.asyncio
async def test_secure_candidate_test_create_and_inactive_connection_test(delegated, db, synthetic_mcp):
    ctx, recipient, _ = delegated
    url, calls = synthetic_mcp
    from fastmcp.tools import Tool as RemoteTool

    async def echo_schema(value: str = "") -> str:
        calls.append(value)
        return value

    remote = RemoteTool.from_function(echo_schema, name="lookup")
    remote.parameters["properties"]["synthetic-candidate-token-001"] = {"type": "string"}
    calls.server.add_tool(remote)
    definition = {"code": f"synthetic_{uuid4().hex}", "label": "Prepared MCP",
        "mcp_config": {"type": "sse" if url.endswith("/sse") else "http", "url": url, "auth": {"type": "bearer", "param": "token"}},
        "connection_schema": {"params": {"token": {"type": "password"}}}}
    prepared = prepare_candidate(CandidateRequest(agent_id=ctx.agent_id, definition=definition,
                                 params={"token": "synthetic-candidate-token-001"}))
    reference = prepared["reference"]
    with pytest.raises(AdministrationError):
        resolve_candidate(reference, recipient)
    before = len((await db.scalars(select(Tool))).all())
    tested = result(await mcp.tool_admin_mcp_test(ctx, candidate_reference=reference))
    assert tested["diagnostic"]["success"], tested
    assert tested["diagnostic"]["tested_at"]
    assert [item["name"] for item in tested["diagnostic"]["tools"]] == ["lookup"]
    assert calls == []
    assert len((await db.scalars(select(Tool))).all()) == before
    assert "synthetic-candidate-token" not in json.dumps(tested)
    created = result(await mcp.tool_admin_create(ctx, candidate_reference=reference))
    tool_id = created["tool"]["id"]
    assert "synthetic-candidate-token" not in json.dumps(created)
    connection = result(await connection_mcp.tool_admin_connection_create(ctx, tool_id, recipient, created["version"]))
    identifier = connection["connection"]["id"]
    tested = result(await connection_mcp.tool_admin_connection_test(ctx, identifier))
    assert tested["diagnostic"]["success"] and calls == []
    assert not (await connection_service.get_connection(identifier)).active
    detail = result(await mcp.tool_admin_function_get(ctx, tool_id, "lookup", identifier))
    assert "value" in detail["function"]["input_schema"]["properties"]
    assert "synthetic-candidate-token-001" not in json.dumps(detail)
    available = result(await connection_mcp.tool_admin_connection_function_list(ctx, identifier))
    assert available["items"][0]["effective"] and not available["items"][0]["available"]


@pytest.mark.asyncio
async def test_diagnostic_bounds_large_remote_catalogue(delegated, db, synthetic_mcp):
    ctx, _, _ = delegated
    url, calls = synthetic_mcp

    async def diagnostic_only(value: str = "") -> str:
        calls.append(value)
        return value

    for index in range(501):
        calls.server.tool(name=f"synthetic_{index:03}", description="x" * 9000 if index == 0 else "Synthetic function")(diagnostic_only)
    prepared = prepare_candidate(CandidateRequest(agent_id=ctx.agent_id, definition={
        "code": f"synthetic_{uuid4().hex}", "label": "Bounded catalogue",
        "mcp_config": {"type": "sse" if url.endswith("/sse") else "http", "url": url},
    }))
    diagnostic = result(await mcp.tool_admin_mcp_test(ctx, candidate_reference=prepared["reference"],
                        limit=20))["diagnostic"]
    assert diagnostic["success"] and diagnostic["truncated"], diagnostic
    assert diagnostic["total"] == 500 and len(diagnostic["tools"]) == 20
    assert calls == []
    large = next(item for item in diagnostic["tools"] if item["name"] == "synthetic_000")
    assert large["truncated"] and len(large["description"]) <= 8192


@pytest.mark.asyncio
async def test_native_mounted_admin_revocation(committed_database):
    async with get_db_session() as db:
        title = Title(label="Synthetic mounted admin", gender="X")
        user = User(email=f"{uuid4().hex}@example.test", hashed_password="unused")
        db.add_all([title, user])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"synthetic-{uuid4().hex}", first_name="Admin", last_name="Synthetic", agent_driver="internal")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        tool = await db.scalar(select(Tool).where(Tool.code == "tool_admin"))
        grant = Connection(tool_id=tool.id, agent_id=agent_id, active=True)
        db.add(grant)
        await db.flush()
        grant_id = grant.id
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(agent_id, runtime="internal")
    async with Client(server) as client:
        assert not (await client.call_tool("tool_admin_list", {})).is_error
        async with get_db_session():
            await connection_service.set_connection_function_state(grant_id, "tool_admin_list", "disabled")
        assert (await client.call_tool("tool_admin_list", {}, raise_on_error=False)).is_error


@pytest.mark.asyncio
async def test_external_mounted_server_rechecks_permissions_and_credentials(committed_database, synthetic_mcp):
    url, calls = synthetic_mcp
    async with get_db_session() as db:
        title = Title(label="Synthetic external MCP", gender="X")
        user = User(email=f"{uuid4().hex}@example.test", hashed_password="unused")
        db.add_all([title, user])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"synthetic-{uuid4().hex}", first_name="External", last_name="Synthetic", agent_driver="internal")
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        tool = Tool(code=f"external_{uuid4().hex}", label="Synthetic external", mcp_config={"type": "sse" if url.endswith("/sse") else "http", "url": url,
                    "auth": {"type": "bearer", "param": "token"}},
                    connection_schema={"params": {"token": {"type": "password"}}})
        db.add(tool)
        await db.flush()
        code, tool_id = tool.code, tool.id
        connection = Connection(tool_id=tool_id, agent_id=agent_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id = connection.id
        await connection_service.set_param(connection_id, "token", "synthetic-initial-token")
    async with get_db_session():
        server = await build_agent_mcp(agent_id, runtime="internal")
    async with Client(server) as client:
        assert not (await client.call_tool(f"{code}_lookup", {"value": "first"})).is_error
        async with get_db_session():
            await connection_service.set_connection_function_state(connection_id, "lookup", "disabled")
        assert (await client.call_tool(f"{code}_lookup", {"value": "revoked"}, raise_on_error=False)).is_error
        assert calls == ["first"]
        async with get_db_session():
            await connection_service.set_connection_function_state(connection_id, "lookup", "default")
            await connection_service.set_param(connection_id, "token", "synthetic-rotated-token")
        assert not (await client.call_tool(f"{code}_lookup", {"value": "restored"})).is_error
        async with get_db_session():
            await connection_service.set_connection_active(connection_id, False)
        assert (await client.call_tool(f"{code}_lookup", {"value": "inactive"}, raise_on_error=False)).is_error
        assert calls == ["first", "restored"]
        assert calls.headers == ["Bearer synthetic-initial-token", "Bearer synthetic-rotated-token"]

    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage
    from app.tools.live_external import LiveConnectionToolset

    async with get_db_session():
        await connection_service.set_connection_active(connection_id, True)
    mounted = LiveConnectionToolset(agent_id, connection_id, tool_id)
    run_ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    tools = await mounted.get_tools(run_ctx)
    name = f"{code}_lookup"
    await mounted.call_tool(name, {"value": "pydantic-first"}, run_ctx, tools[name])
    async with get_db_session():
        await connection_service.set_param(connection_id, "token", "synthetic-pydantic-rotation")
    await mounted.call_tool(name, {"value": "pydantic-rotation"}, run_ctx, tools[name])
    assert calls.headers[-2:] == ["Bearer synthetic-rotated-token", "Bearer synthetic-pydantic-rotation"]
    async with get_db_session():
        await connection_service.set_connection_function_state(connection_id, "lookup", "disabled")
    with pytest.raises(PermissionError):
        await mounted.call_tool(name, {"value": "pydantic-revoked"}, run_ctx, tools[name])
    assert calls[-2:] == ["pydantic-first", "pydantic-rotation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "partial"])
async def test_mass_refresh_returns_direct_results_and_preserves_business_processes(delegated, db, outcome):
    from app.process.models import ProcessDefinition, ProcessRun
    from sqlalchemy import func

    ctx, recipient, grant_id = delegated
    tool = Tool(
        code=f"bulk_{uuid4().hex}", label="Synthetic mass refresh")
    db.add(tool)
    template = await db.get(Agent, recipient)
    agents = [Agent(title_id=template.title_id, code=f"refresh-{uuid4().hex}", first_name="Refresh",
                    last_name="Synthetic", agent_driver="internal") for _ in range(11)]
    db.add_all(agents)
    if outcome == "partial":
        agents[0].agent_driver = "synthetic-unavailable-runtime"
    await db.flush()
    db.add_all([Connection(tool_id=tool.id, agent_id=agent.id, active=False) for agent in agents])
    await db.commit()
    counts = [await db.scalar(select(func.count()).select_from(model))
              for model in (ProcessDefinition, ProcessRun)]
    refreshed = result(await mcp.tool_admin_catalog_refresh(ctx, tool_id=tool.id))["refresh"]
    assert "run_id" not in refreshed and "queued" not in refreshed
    assert refreshed["remaining_agent_ids"] == []
    if outcome == "partial":
        assert not refreshed["complete"] and refreshed["agents_refreshed"] == 10
        assert refreshed["failed_agent_ids"] == [agents[0].id]
        # Retrying just the failed connection completes the reconciliation.
        agents[0].agent_driver = "internal"
        await db.commit()
        connection = await db.scalar(select(Connection).where(Connection.agent_id == agents[0].id,
                                                              Connection.tool_id == tool.id))
        retried = result(await mcp.tool_admin_catalog_refresh(ctx, connection_ids=[connection.id]))["refresh"]
        assert retried["complete"] and retried["agents_refreshed"] == 1
    else:
        assert refreshed["complete"] and refreshed["agents_refreshed"] == 11
    assert [await db.scalar(select(func.count()).select_from(model))
            for model in (ProcessDefinition, ProcessRun)] == counts


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["timeout", "cancel", "revoke"])
async def test_direct_refresh_preserves_completed_agents_and_stops_on_interruption(
        delegated, db, monkeypatch, interruption):
    import asyncio
    from app.tools import catalog_refresh_service
    from app.tools.catalog import catalog_entry_from_definition, catalog_from_entries
    from app.tools.models import ToolSearchDocument

    ctx, recipient, grant_id = delegated
    identifiers = sorted([ctx.agent_id, recipient])
    calls = []
    build_catalog = catalog_refresh_service.build_effective_tool_catalog
    marker = catalog_entry_from_definition(runtime="internal", name=f"synthetic_refresh_{uuid4().hex}",
        description="Synthetic catalogue checkpoint", parameters_json_schema={})

    async def interrupted_discovery(agent_id, **kwargs):
        calls.append(agent_id)
        if interruption == "revoke" and len(calls) == 1:
            # Revocation is reached after a discovery slower than the timeout case's budget.
            await asyncio.sleep(1.1)
        if len(calls) == 2:
            if interruption == "timeout":
                await asyncio.Event().wait()
            elif interruption == "cancel":
                raise asyncio.CancelledError()
            else:
                await connection_service.set_connection_function_state(
                    grant_id, "tool_admin_catalog_refresh", "disabled")
        catalog = await build_catalog(agent_id, **kwargs)
        if len(calls) == 1:
            return catalog_from_entries(agent_id=agent_id, runtime=catalog.runtime,
                entries=[*catalog.entries, marker])
        return catalog

    monkeypatch.setattr(catalog_refresh_service, "build_effective_tool_catalog", interrupted_discovery)
    actor = AdministrationContext(agent_id=ctx.agent_id, function_name="tool_admin_catalog_refresh")
    if interruption == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await admin_service.refresh_catalogs(actor, identifiers)
        # Cancellation leaves the contextual session usable after rollback.
        assert await db.get(Agent, recipient)
    else:
        # The short deadline belongs only to the timeout scenario. Revocation
        # must reach the second discovery even when the first one is slow.
        if interruption == "timeout":
            refreshed = await admin_service.refresh_catalogs(actor, identifiers, timeout_seconds=1)
        else:
            refreshed = await admin_service.refresh_catalogs(actor, identifiers)
        assert not refreshed["complete"] and refreshed["agents_refreshed"] == 1
        assert refreshed["remaining_agent_ids"] == identifiers[1:]
        assert refreshed["error"] == ("access_denied" if interruption == "revoke" else "catalog_refresh_timeout")
    assert calls == identifiers
    assert await db.scalar(select(ToolSearchDocument.id).where(
        ToolSearchDocument.definition_fingerprint == marker.definition_fingerprint)) is not None


@pytest.mark.asyncio
async def test_candidate_credentials_stay_out_of_model_messages_and_checkpoints(delegated, db, synthetic_mcp):
    from unittest.mock import AsyncMock
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, TextPart
    from pydantic_ai.mcp import MCPToolset
    from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
    from app.harness.tests.test_checkpoint import _request

    ctx, _, _ = delegated
    url, calls = synthetic_mcp
    secret = "synthetic-private-model-candidate-token"
    # This scenario verifies secret confinement after an explicit human policy grant.
    # Deferred approval itself is exercised separately without permitting the effect.
    grant = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == ctx.agent_id, Tool.code == "tool_admin"))
    for function in ("tool_admin_mcp_test", "tool_admin_create"):
        await connection_service.set_connection_function_state(grant.id, function, "enabled")
    reference = prepare_candidate(CandidateRequest(agent_id=ctx.agent_id, definition={
        "code": f"model_{uuid4().hex}", "label": "Synthetic scripted operator",
        "mcp_config": {"type": "sse" if url.endswith("/sse") else "http", "url": url, "auth": {"type": "bearer", "param": "token"}},
        "connection_schema": {"params": {"token": {"type": "password"}}},
    }, params={"token": secret}))["reference"]
    observed = []
    def scripted_model(messages, info):
        observed.append(str(messages))
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        if len(returns) == 2:
            return ModelResponse(parts=[TextPart("The Tool was created.")])
        return ModelResponse(parts=[ToolCallPart("tool_admin_mcp_test" if not returns else "tool_admin_create",
                                {"candidate_reference": reference})])
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    server = await build_agent_galaris_fastmcp(ctx.agent_id, runtime="internal")
    agent = PydanticAgent(FunctionModel(scripted_model), toolsets=wrap_toolsets([MCPToolset(server)], journal))
    output = await agent.run("Test and create the human-prepared integration using its reference.")
    assert output.output == "The Tool was created."
    assert calls == []
    assert secret not in "".join(observed)
    assert save.await_count > 0
    assert all(secret not in str(call.args[0].data) for call in save.await_args_list)
    assert (await db.scalar(select(Tool).where(Tool.code.like("model_%")))) is not None


@pytest.mark.asyncio
async def test_concurrent_mutations_only_apply_one_examined_version(committed_database):
    async with get_db_session() as db:
        user = User(email=f"{uuid4().hex}@example.test", hashed_password="unused")
        title = Title(label="Synthetic concurrent operator", gender="M")
        db.add_all([user, title])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"conflict-{uuid4().hex}", first_name="Concurrent", last_name="Synthetic")
        tool = Tool(code=f"conflict_{uuid4().hex}", label="Examined configuration")
        db.add_all([agent, tool])
        await db.flush()
        admin = await db.scalar(select(Tool).where(Tool.code == "tool_admin"))
        grant = Connection(tool_id=admin.id, agent_id=agent.id, active=True)
        db.add(grant)
        await db.flush()
        await connection_service.set_connection_function_state(grant.id, "tool_admin_update", "enabled")
        agent_id, tool_id = agent.id, tool.id
    ctx = McpToolContext(agent_id, "internal")
    async with get_db_session():
        version = result(await mcp.tool_admin_get(ctx, tool_id))["version"]
    async def write(label):
        async with get_db_session():
            return json.loads(await mcp.tool_admin_update(ctx, tool_id, {"label": label}, version))
    outcomes = await asyncio.gather(write("First candidate"), write("Second candidate"))
    assert sum(item["success"] for item in outcomes) == 1
    assert next(item for item in outcomes if not item["success"])["error"]["kind"] == "conflict"
    winner = next(item for item in outcomes if item["success"])
    async with get_db_session():
        current = result(await mcp.tool_admin_get(ctx, tool_id))
        assert current["tool"]["label"] == winner["tool"]["label"]
