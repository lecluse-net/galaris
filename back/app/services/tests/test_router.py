"""Tests for Service administration routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.services import router
from app.services.schemas import (
    ServiceGlobalParamPublic,
    ServiceGlobalParamsUpdate,
    ServiceMcpTestRequest,
    ServiceMcpTestResponse,
    ServiceCreate,
    ServiceUpdate,
)


@pytest.mark.asyncio
async def test_rest_skill_generation_uses_the_installed_assistant_and_its_scoped_tools(client, monkeypatch, tmp_path):
    from fastmcp import Client
    from sqlalchemy import select

    from app.agent import parse_scope
    from app.agent.models import Agent, Title
    from app.services import build_agent_galaris_fastmcp, initialize_admin_agent_connections
    from app.services.models import Service
    from app.skill import storage
    from app.skill.models import Skill
    from app.task import Task, runner
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.params import Param, Params
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    # Exercise the real HTTP, authorization and persistence paths without running a model.
    monkeypatch.setattr(runner, "go_next", lambda task_id: None)
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    password = "synthetic-skill-generation-password"
    async with get_db_session() as db:
        permissions = {privilege.code: privilege for privilege in (await db.scalars(select(Privilege))).all()}
        users = []
        for profile, skills in (("manager", ["SKILL_EDIT"]), ("editor", [])):
            codes = ["SERVICE_EDIT", "TASK_EDIT", "AGENT_MANAGE_ALL", *skills]
            role = Role(code=f"synthetic-skill-{profile}", privileges=[permissions[code] for code in codes])
            user = UserModel(email=f"synthetic-{profile}@example.com", is_active=True,
                hashed_password=encrypt_password(password))
            db.add_all([user, role])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            users.append((user.email, user.id))

        title = Title(label="Synthetic assistant", gender="X")
        db.add(title)
        await db.flush()
        assistant = Agent(code="renamed-assistant", first_name="Renamed", last_name="", title_id=title.id, user_id=users[0][1])
        decoy = Agent(code="galaris", first_name="Other", last_name="", title_id=title.id, user_id=users[0][1])
        rest = Service(code="synthetic-support", label="Support <galaris://skill/unrelated/SKILL.md>",
            rest_config={"base_url": "https://api.example.test/synthetic-private-path"},
            catalog={"documentation": "https://docs.example.test/openapi.json?token=synthetic-secret"})
        other = Service(code="synthetic-other", label="Other")
        db.add_all([assistant, decoy, rest, other])
        await db.flush()
        assistant_id, rest_id, other_id = assistant.id, rest.id, other.id
        marker = await db.get(Param, Params.GALARIS_AGENT_ID)
        assert marker is not None
        marker.value = None

    headers = []
    for email, _ in users:
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    manager, editor = headers
    path = f"/api/services/{rest_id}/generate-skill"
    request = {"operation_id": str(uuid4())}
    assert (await client.post(path, json=request, headers=editor)).status_code == 403
    assert (await client.post(path, json=request, headers=manager)).status_code == 409
    assert (await client.post(f"/api/services/{other_id}/generate-skill", json=request, headers=manager)).status_code == 409

    async with get_db_session() as db:
        marker = await db.get(Param, Params.GALARIS_AGENT_ID)
        assert marker is not None
        marker.value = str(assistant_id)
        await initialize_admin_agent_connections(assistant_id)

    response = await client.post(path, json=request, headers=manager)
    assert response.status_code == 202, response.text
    replay = await client.post(path, json=request, headers=manager)
    assert replay.status_code == 202 and replay.json() == response.json()

    task_id = UUID(response.json()["task_id"])
    uri = "galaris://skill/service-synthetic-support/SKILL.md"
    async with get_db_session() as db:
        task = await db.get(Task, task_id)
        assert task is not None and task.agent_id == assistant_id and task.requester_user_id == users[0][1]
        assert task.objective and "synthetic-support" in task.objective
        assert r"https:\/\/docs.example.test/openapi.json" in task.objective
        assert "synthetic-secret" not in task.objective and "synthetic-private-path" not in task.objective
        scope = parse_scope(task.data or {})
        assert scope is not None
        assert {grant.target for grant in scope.grants} == {uri}
        server = await build_agent_galaris_fastmcp(assistant_id, task_id=task_id,
            allowed_tool_names={"search_web", "file_create"})

    async with Client(server) as agent:
        assert {item.name for item in await agent.list_tools()} >= {"search_web", "file_create"}
        code = "service-synthetic-support"
        content = f"---\nname: {code}\ndescription: Use the synthetic Support API.\n---\nUse rest_request to list tickets."
        created = await agent.call_tool("file_create", {"path": uri, "content": content}, raise_on_error=False)
        assert not created.is_error, created
        replay = await agent.call_tool("file_create", {"path": uri, "content": content + " Changed."}, raise_on_error=False)
        assert replay.is_error

    async with get_db_session() as db:
        skill = await db.scalar(select(Skill).where(Skill.code == code))
        assert skill is not None and skill.owner_agent_id is None and skill.creator_agent_id == assistant_id
        assert storage.read_file(code, "SKILL.md").content.decode() == content


@pytest.mark.asyncio
async def test_development_tool_inventory_lists_service_defaults_without_an_agent(client, monkeypatch):
    from sqlalchemy import select

    from app.connection import ServiceFunctionState
    from app.services.mandatory_services import INTEGRATED_SERVICE_CODES
    from app.services.mcp_loader import mcp_tools_by_service_code
    from app.services.models import Service
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.settings import settings
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    suffix = uuid4().hex
    password = "synthetic-inventory-password"
    empty_code, external_code = f"empty-{suffix}", f"external-{suffix}"
    async with get_db_session() as db:
        reader_privilege = await db.scalar(select(Privilege).where(Privilege.code == "SERVICE_ACCESS"))
        assert reader_privilege is not None
        empty = Service(code=empty_code, label="Synthetic service without tools")
        external = Service(
            code=external_code, label="Synthetic MCP server",
            mcp_config={"type": "http", "url": "https://synthetic-secret.example.test/mcp"},
            conversation_tools={"external": ["lookup"]},
        )
        browser = await db.scalar(select(Service).where(Service.code == "browser"))
        assert browser is not None
        browser.connection_schema = {
            **browser.connection_schema,
            "params": {
                **browser.connection_schema["params"],
                "synthetic_password": {"type": "password", "default": "synthetic-secret-default"},
            },
        }
        browser.global_params = {
            **(browser.global_params or {}),
            "public_access_mode": {"value": "allow", "forced": True},
            "synthetic_password": {"value": "synthetic-secret-configured", "forced": False},
        }
        db.add_all([empty, external])
        await db.flush()
        db.add_all([
            ServiceFunctionState(service_id=browser.id, function_name="search_web", enabled=False),
            ServiceFunctionState(service_id=browser.id, function_name="search_web", state="ask", capability_kind="prompt"),
        ])
        emails = []
        for name, privileges in (("reader", [reader_privilege]), ("visitor", [])):
            role = Role(code=f"inventory-{name}-{suffix}", privileges=privileges)
            user = UserModel(
                email=f"inventory-{name}-{suffix}@example.com",
                hashed_password=encrypt_password(password),
                is_active=True,
            )
            db.add_all([role, user])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            emails.append(user.email)

    path = "/api/services/tool-inventory"
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    assert (await client.get(path)).status_code == 401
    headers = []
    for email in emails:
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    reader, visitor = headers
    assert (await client.get(path, headers=visitor)).status_code == 403
    for label in ("prod", "test", "pp", "DEV", ""):
        monkeypatch.setattr(settings, "APP_ENV", label)
        assert (await client.get(path, headers=reader)).status_code == 404

    monkeypatch.setattr(settings, "APP_ENV", "dev")
    response = await client.get(path, headers=reader)
    assert response.status_code == 200, response.text
    assert "synthetic-secret" not in response.text
    inventory = {row["code"]: row for row in response.json()}
    assert set(inventory) == INTEGRATED_SERVICE_CODES
    assert {empty_code, external_code}.isdisjoint(inventory)
    files = {tool["name"]: tool for tool in inventory["file_sharing"]["tools"]}
    file_read = next(tool for tool in mcp_tools_by_service_code()["file_sharing"] if tool.name == "file_read")
    assert file_read.description
    assert files["file_read"]["description"] == file_read.description
    search = next(tool for tool in inventory["browser"]["tools"] if tool["name"] == "search_web")
    assert search["conversation_enabled"] is True
    assert search["default_state"] == "ask"
    assert search["service_override"] == "disabled"
    assert inventory["browser"]["connection_default"] == "active"
    assert inventory["galaris"]["connection_default"] == "active"
    assert inventory["topic"]["connection_default"] == "manual"
    assert "services.management_scope" not in inventory["galaris"]["connection_schema"]["params"]
    for code, expected in (("chat", "team"), ("skills", "personal"), ("service", "usage")):
        settings = inventory[code]["connection_schema"]["params"]
        assert settings["services.management_scope"]["default"] == expected
        assert "services.management_scope" not in inventory[code]["global_params"]
    chat_scope = inventory["chat"]["connection_schema"]["params"]["services.management_scope"]
    assert {option["value"] for option in chat_scope["options"]} == {"none", "team", "all"}
    browser_parameters = inventory["browser"]["connection_schema"]["params"]
    browser_values = inventory["browser"]["global_params"]
    assert browser_parameters["public_access_mode"]["default"] == "ask"
    assert browser_values["public_access_mode"] == {
        "value": "allow", "configured": True, "secret": False, "forced": True,
    }
    assert browser_parameters["synthetic_password"]["default"] == ""
    assert browser_values["synthetic_password"] == {
        "value": None, "configured": True, "secret": True, "forced": False,
    }
    assert files["file_read"]["conversation_enabled"] is True
    assert files["file_read"]["default_state"] == "enabled"
    assert files["file_delete"]["conversation_enabled"] is False
    assert files["file_delete"]["default_state"] == "ask"


@pytest.mark.asyncio
async def test_conversation_allowlist_requires_a_human_service_editor(client, monkeypatch):
    from contextlib import AsyncExitStack

    import httpx2 as httpx
    from fastmcp import FastMCP
    from sqlalchemy import select
    from app.agent.models import Agent, Title
    from app.connection.models import Connection, ConnectionParam
    from app.services.models import Service
    from app.services import conversation_catalog
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    suffix = uuid4().hex
    password = "synthetic-conversation-admin"
    async with get_db_session() as db:
        builtin_id = await db.scalar(select(Service.id).where(Service.code == "browser"))
        service = Service(code=f"allowlist-{suffix}", label="Synthetic MCP", mcp_config={
            "type": "http", "url": "https://tools.example.test/${connection:catalog}/mcp",
            "headers": {"X-Example-Key": "${connection:token}"},
        }, connection_schema={"params": {"catalog": {"type": "string"}, "token": {"type": "password"}}},
            global_params={"catalog": {"value": "shared"}, "token": {"value": "synthetic_shared_token"}})
        title = Title(label="Catalog agent", gender="N")
        db.add_all([service, title])
        users: list[UserModel] = []
        for index, codes in enumerate((("SERVICE_ACCESS",), ("SERVICE_EDIT", "CONNECTION_ACCESS"), ("SERVICE_EDIT",))):
            privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
            role = Role(code=f"allowlist-{index}-{suffix}", privileges=privileges)
            user = UserModel(email=f"allowlist-{index}-{suffix}@example.com", hashed_password=encrypt_password(password), is_active=True)
            db.add_all([role, user])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            users.append(user)
        for name, owner, active in (("one", 1, True), ("two", 1, True), ("other", 2, True), ("inactive", 1, False)):
            agent = Agent(code=f"{name}-{suffix}", first_name="Synthetic", last_name=name, user_id=users[owner].id, title_id=title.id)
            db.add(agent)
            await db.flush()
            connection = Connection(agent_id=agent.id, service_id=service.id, active=active)
            db.add(connection)
            await db.flush()
            db.add_all([ConnectionParam(connection_id=connection.id, param_name=key, param_value=value)
                for key, value in {"catalog": name, "token": f"synthetic_{name}_token"}.items()])
        emails = [user.email for user in users]
        service_id = service.id
    path = f"/api/services/{service_id}/conversation-tools"
    change = {"name": "lookup", "source": "external", "enabled": True}
    assert (await client.patch(path, json=change)).status_code == 401
    headers = []
    for email in emails:
        client.cookies.clear()
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    reader, editor, service_only = headers
    requested: list[str] = []
    applications = {}

    async def remote_tool() -> str:
        pytest.fail("Listing a catalog must never call an MCP tool")

    async def diagnostic_client(url: str, *, allow_private: bool) -> httpx.AsyncClient:
        requested.append(url)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=applications[url]))

    monkeypatch.setattr(conversation_catalog, "diagnostic_client", diagnostic_client)
    monkeypatch.setattr(conversation_catalog, "_CONNECTION_PAGE_SIZE", 1)
    assert (await client.patch(path, json=change, headers=reader)).status_code == 403
    assert (await client.post(f"{path}/discover", headers=reader)).status_code == 403
    builtin = await client.get(f"/api/services/{builtin_id}/conversation-tools", headers=reader)
    assert [row for row in builtin.json()["tools"] if row["enabled"]] == [{"name": "search_web", "source": "native", "enabled": True}]
    assert (await client.post(f"/api/services/{builtin_id}/conversation-tools/discover", headers=editor)).status_code == 403
    assert not requested
    assert (await client.patch(f"/api/services/{builtin_id}/conversation-tools",
        json={"name": "search_web", "source": "native", "enabled": False}, headers=editor)).status_code == 422
    def tools(response):
        assert response.status_code == 200, response.text
        return {row["name"]: row["enabled"] for row in response.json()["tools"]}

    async with AsyncExitStack() as stack:
        for name, names in (("shared", ("lookup",)), ("one", ("lookup", "list_items", "synthetic_one_token")),
                            ("two", ("lookup", "account_only"))):
            server = FastMCP(f"Synthetic {name}")
            for tool_name in names:
                server.tool(name=tool_name)(remote_tool)
            application = server.http_app(path=f"/{name}/mcp")
            await stack.enter_async_context(application.router.lifespan_context(application))
            applications[f"https://tools.example.test/{name}/mcp"] = application

        initial = await client.post(f"{path}/discover", headers=editor)
        assert tools(initial) == {"lookup": False, "list_items": False}
        assert initial.json()["discovery_incomplete"] is True  # The echoed credential was dropped.
        after = initial.json()["next_connection_id"]
        assert after is not None
        following = await client.post(f"{path}/discover", params={"after_connection_id": after}, headers=editor)
        assert tools(following) == {"lookup": False, "account_only": False}
        assert following.json()["next_connection_id"] is None
        assert set(requested) == set(applications)
        requested.clear()
        assert tools(await client.post(f"{path}/discover", headers=service_only)) == {"lookup": False}
        assert requested == ["https://tools.example.test/shared/mcp"]
    response = await client.patch(path, json=change, headers=editor)
    assert response.status_code == 200, response.text
    saved = await client.get(path, headers=reader)
    assert saved.json()["tools"] == [{"name": "lookup", "source": "external", "enabled": True}]
    async with get_db_session() as db:
        assert (await db.get(Service, service_id)).conversation_tools == {"external": ["lookup"]}


@pytest.mark.asyncio
async def test_service_list_counts_existing_active_and_inactive_connections(db):
    from app.agent.models import Agent, Title
    from app.connection import Connection

    suffix = uuid4().hex
    connected = await router.service.create_service(ServiceCreate(code=f"counted-{suffix}", label="Synthetic counted service"))
    empty = await router.service.create_service(ServiceCreate(code=f"empty-{suffix}", label="Synthetic empty service"))
    title = Title(label="Synthetic counter", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(code=f"counter-{index}-{suffix}", first_name="Synthetic", last_name="Counter", title_id=title.id)
        for index in range(2)]
    db.add_all(agents)
    await db.flush()
    db.add_all([Connection(service_id=connected.id, agent_id=agent.id, active=index == 0)
        for index, agent in enumerate(agents)])
    await db.flush()
    counts = {item.id: item.connection_count for item in await router.list_services()}
    assert counts[connected.id] == 2
    assert counts[empty.id] == 0


@pytest.mark.asyncio
async def test_mcp_connection_delegates_with_existing_secret_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_config = {"type": "http", "headers": {"X-Secret": "encrypted"}}
    get_record = AsyncMock(
        return_value=SimpleNamespace(mcp_config=existing_config)
    )
    expected = ServiceMcpTestResponse(
        success=True,
        message="2 MCP functions available",
    )
    diagnose = AsyncMock(return_value=expected)
    monkeypatch.setattr(router.service, "get_service_record_by_id", get_record)
    monkeypatch.setattr(router, "diagnose_mcp_connection", diagnose)
    request = ServiceMcpTestRequest(
        service_id=7,
        code="issue_tracker",
        mcp_config={
            "type": "http",
            "url": "https://preview.example.test/mcp",
            "headers": {"X-Secret": "••••••••"},
        },
        params={"token": "temporary", "unused": None},
    )

    result = await router.test_mcp_connection(request)

    assert result is expected
    get_record.assert_awaited_once_with(7)
    diagnose.assert_awaited_once_with(
        request,
        existing_config=existing_config,
    )


@pytest.mark.asyncio
async def test_integrated_tool_global_params_can_be_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(id=7, code="console")
    update = AsyncMock(return_value=record)
    monkeypatch.setattr(router.service, "update_global_params", update)
    monkeypatch.setattr(
        router.service,
        "public_global_params",
        lambda _record: {
            "host": ServiceGlobalParamPublic(
                value="ssh.example.test",
                configured=True,
                forced=False,
            )
        },
    )
    request = ServiceGlobalParamsUpdate(
        params={"host": {"value": "ssh.example.test", "forced": False}}
    )

    result = await router.update_global_params(7, request)

    assert result.service_id == 7
    assert result.params["host"].value == "ssh.example.test"
    update.assert_awaited_once_with(7, request)


@pytest.mark.asyncio
@pytest.mark.parametrize("language,prefix", [
    ("fr", "Le nom technique"),
    ("en", "The technical name"),
    ("zh", "启用文件共享"),
])
async def test_resource_service_code_errors_use_the_request_language(db, monkeypatch, language, prefix):
    from core.i18n import i18n_service

    monkeypatch.setattr(i18n_service, "current_language", AsyncMock(return_value=language))
    code = f"synthetic_share_{uuid4().hex}"
    config = {"service": "samba", "base_url": "smb://files.example.test", "param_map": {}}
    definition = ServiceCreate(code=code, label="Synthetic share", file_share_config=config)
    with pytest.raises(HTTPException) as creation:
        await router.create_service(definition)
    record = await router.service.create_service(ServiceCreate(code=code, label="Synthetic share"))
    with pytest.raises(HTTPException) as update:
        await router.update_service(record.id, ServiceUpdate(file_share_config=config))
    with pytest.raises(HTTPException) as imported:
        await router.import_service(body=(
            f"code: {code}-import\nlabel: Synthetic share\n"
            "file_share_config:\n  service: samba\n  base_url: smb://files.example.test\n"
        ))
    for rejection in (creation, update, imported):
        assert rejection.value.status_code == 422
        assert rejection.value.detail.startswith(prefix)
        assert "resource-capable Service code" not in rejection.value.detail
    await db.refresh(record)
    assert record.file_share_config is None
