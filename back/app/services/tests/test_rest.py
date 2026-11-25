"""REST journeys use real connection persistence and a synthetic HTTP service."""

import asyncio
import base64
import json
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import connection_service
from app.connection.models import ConnectionParam
from app.services import RestConfig, RestError, RestRequest, execute_rest_request, service
from app.services import mcp_loader
from app.services.authorization import AUTHORIZATION_META_KEY, answer_action
from app.services.authorization_models import ActionAuthorization
from app.services.projections import to_public
from app.services.schemas import ServiceCreate, ServiceGlobalParamsUpdate, ServiceUpdate
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel

@pytest_asyncio.fixture
async def api_server():
    requests = []

    async def handle(reader, writer):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode().split("\r\n")
            method, target, _ = lines[0].split(" ")
            headers = {name.lower(): value for line in lines[1:] if ": " in line for name, value in [line.split(": ", 1)]}
            content = await reader.readexactly(int(headers.get("content-length", "0")))
            item = {"method": method, "target": target, "headers": headers, "content": content.decode(errors="replace")}
            requests.append({**item, "raw": content})
            status, extra = "200 OK", ""
            if target.startswith("/v1/redirect"):
                status, extra = "302 Found", "Location: http://other.example.test/secret\r\n"
            elif target.startswith("/v1/denied"):
                status = "403 Forbidden"
            if target.startswith("/v1/slow"):
                await asyncio.sleep(1.1)
            body = (b"x" * 2048 if target.startswith("/v1/large") else
                    b"plain result" if target.startswith("/v1/text") else json.dumps(item).encode())
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n{extra}Set-Cookie: synthetic=secret\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
    async with server:
        yield base, requests


async def create_rest_setup(db, api_server, manager_id=None):
    base, requests = api_server
    title = Title(label="Synthetic REST operator", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(user_id=manager_id, title_id=title.id, code=f"rest-{uuid4().hex}", first_name=name,
                    last_name="Synthetic", agent_driver="internal") for name in ("First", "Second")]
    db.add_all(agents)
    await db.flush()
    tool = await service.create_service(ServiceCreate(code=f"rest-{uuid4().hex}", label="Synthetic API",
        rest_config={"base_url": "${connection:api_url}", "auth": {"type": "bearer"}},
        connection_schema={"params": {"api_url": {"type": "string", "required": False},
            "api_token": {"type": "password", "required": False},
            "login": {"type": "string", "required": False}}}))
    await service.update_global_params(tool.id, ServiceGlobalParamsUpdate(params={
        "api_url": {"value": base}, "api_token": {"value": "synthetic-global-token"}}))
    connections = [await connection_service.get_or_create_connection(tool.id, agent.id) for agent in agents]
    await connection_service.set_params_bulk(connections[1].id, {"api_token": "synthetic-local-token"})
    return tool, agents, connections, requests


@pytest_asyncio.fixture
async def rest_setup(db, api_server):
    return await create_rest_setup(db, api_server)


@pytest_asyncio.fixture
async def rest_approval_setup(committed_database, api_server):
    # A one-use approval is committed in its own transaction before the MCP call returns.
    async with get_db_session() as db:
        manager = UserModel(email="rest-approver@example.test", hashed_password="synthetic")
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
        role = Role(code="rest-approver", privileges=[privilege])
        db.add_all([manager, role])
        await db.flush()
        db.add(Assignment(user_id=manager.id, role_id=role.id))
        yield db, await create_rest_setup(db, api_server, manager.id)


@pytest.mark.asyncio
async def test_agent_discovers_and_calls_rest_on_the_authorized_connection(rest_approval_setup):
    db, (tool, agents, connections, requests) = rest_approval_setup
    agent_id = agents[1].id
    selected = connections[1].id
    catalog = await mcp_loader.list_agent_mcp_tools(agent_id)
    group = next(entry for entry in catalog if entry["service_code"] == tool.code)
    from app.services.mcp import list_mcp_tools
    catalog_text = await list_mcp_tools(mcp_loader.McpToolContext(agent_id, "internal"))
    assert tool.code in catalog_text and "connection_id=" not in catalog_text
    assert any(item["name"] == "rest_request" and item["enabled"] for item in group["mcp_tools"])
    assert (await connection_service.resolve_function(connections[1], "rest_request"))["effective_state"] == "ask"
    second = await service.create_service(ServiceCreate(code=f"rest_{uuid4().hex}", label="Other synthetic API",
        rest_config={"base_url": "https://unused.example.test"}))
    other = await connection_service.get_or_create_connection(second.id, agent_id)
    await connection_service.set_connection_function_state(other.id, "rest_request", "disabled")
    server = await mcp_loader.build_agent_galaris_fastmcp(agent_id, allowed_tool_names={"rest_request"})
    async with Client(server) as client:
        mounted, = await client.list_tools()
        assert mounted.name == "rest_request" and tool.code in mounted.description
        assert set(mounted.input_schema["properties"]) == {"service_code", "account_email", "request"}
        assert second.code not in mounted.description
        request = {"method": "POST", "path": "invoices", "params": {"draft": True}, "json_body": {"amount": 12}}

        async def call(service_code, payload, meta=None):
            return await client.call_tool("rest_request", {"service_code": service_code, "request": payload},
                raise_on_error=False, meta=meta)

        pending = await call(tool.code, request)
        control = pending.meta[AUTHORIZATION_META_KEY]
        assert control["status"] == "pending"
        decision = await db.get(ActionAuthorization, UUID(control["request_id"]))
        assert decision.connection_id == selected
        assert await answer_action(decision.id, user_id=decision.approver_user_id, approved=True)
        resume = {AUTHORIZATION_META_KEY: {"continuation": control["continuation"]}}
        assert (await call(tool.code, {**request, "path": "changed"}, resume)).is_error
        assert (await call(second.code, request)).is_error
        assert (await call("unconnected", request)).is_error
        legacy = await client.call_tool("rest_request", {"connection_id": selected, "service_code": tool.code,
            "request": request}, raise_on_error=False)
        assert legacy.is_error
        assert not requests
        result = await call(tool.code, request, resume)
        assert result.structured_content["status_code"] == 200
        assert result.structured_content["body"]["headers"]["authorization"] == "Bearer [redacted]"
        assert requests[-1]["headers"]["authorization"] == "Bearer synthetic-local-token"
        assert requests[-1]["target"] == "/v1/invoices?draft=true"
        assert json.loads(requests[-1]["content"]) == {"amount": 12}
        assert (await call(tool.code, request, resume)).is_error
        await connection_service.set_connection_function_state(selected, "rest_request", "enabled")
        denied = await call(tool.code, {"path": "denied"})
        assert denied.structured_content["status_code"] == 403
        assert requests[-1]["content"] == ""
        await connection_service.set_connection_active(selected, False)
        assert (await call(tool.code, request)).is_error
        assert len(requests) == 2


@pytest.mark.asyncio
async def test_agent_uploads_raw_and_multipart_files_with_live_access(rest_setup, monkeypatch):
    from email.parser import BytesParser
    from email.policy import default
    from app.file_share import ResourceContext, resource_create

    tool, agents, connections, requests = rest_setup
    actor = ResourceContext(agents[0].id, "internal")
    binary = bytes(range(256))
    source = await resource_create(actor, "file://", binary, name="synthetic.bin")
    foreign = await resource_create(ResourceContext(agents[1].id, "internal"), "file://", binary, name="private.bin")
    await connection_service.set_connection_function_state(connections[0].id, "rest_request", "enabled")
    server = await mcp_loader.build_agent_galaris_fastmcp(actor.agent_id, allowed_tool_names={"rest_request"})
    async with Client(server) as client:
        async def send(**body):
            return await client.call_tool("rest_request", {"service_code": tool.code,
                "request": {"method": "POST", "path": "upload", "params": {"page": 2}, **body}}, raise_on_error=False)

        assert not (await send(file_uri=source.uri)).is_error
        received = requests[-1]
        assert received["raw"] == binary and received["target"] == "/v1/upload?page=2"
        assert received["headers"]["content-type"] == "application/octet-stream"
        part = {"field": "attachment", "uri": source.uri}
        assert not (await send(form={"label": ["a", "b"]}, files=[part, {**part, "filename": "copy.pdf", "content_type": "application/pdf"}])).is_error
        received = requests[-1]
        mime = BytesParser(policy=default).parsebytes(b"Content-Type: " + received["headers"]["content-type"].encode()
            + b"\r\n\r\n" + received["raw"])
        assert [(p.get_param("name", header="content-disposition"), p.get_filename(), p.get_payload(decode=True))
                for p in mime.iter_parts()] == [("label", None, b"a"), ("label", None, b"b"),
                    ("attachment", "synthetic.bin", binary), ("attachment", "copy.pdf", binary)]
        assert list(mime.iter_parts())[-1].get_content_type() == "application/pdf"
        assert not (await send(form={"label": ["a", "b"]})).is_error
        assert parse_qs(requests[-1]["raw"].decode()) == {"label": ["a", "b"]}
        assert (await send(files=[part, {**part, "uri": foreign.uri}])).is_error
        assert (await send(file_uri=source.uri, json_body=None)).is_error
        monkeypatch.setattr("app.services.rest_uploads.MAX_UPLOAD_BYTES", len(binary))
        assert (await send(files=[part, part])).is_error
        assert len(requests) == 3


@pytest.mark.asyncio
async def test_rest_upload_approval_is_bound_to_the_file_content(rest_approval_setup):
    from app.file_share import ResourceContext, resource_create, resource_write

    db, (tool, agents, _, requests) = rest_approval_setup
    actor = ResourceContext(agents[0].id, "internal")
    doc = await resource_create(actor, "document://", b"<p>Original</p>", name="Synthetic note")
    server = await mcp_loader.build_agent_galaris_fastmcp(actor.agent_id, allowed_tool_names={"rest_request"})
    args = {"service_code": tool.code, "request": {"method": "PUT", "file_uri": doc.uri}}
    async with Client(server) as client:
        pending = await client.call_tool("rest_request", args, raise_on_error=False)
        receipt = pending.meta[AUTHORIZATION_META_KEY]
        decision = await db.get(ActionAuthorization, UUID(receipt["request_id"]))
        assert await answer_action(decision.id, user_id=decision.approver_user_id, approved=True)
        await resource_write(actor, doc.uri, b"<p>Replacement</p>", expected_revision=1)
        await db.commit()
        changed = await client.call_tool("rest_request", args, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": receipt["continuation"]}})
        assert changed.is_error and not requests
        pending = await client.call_tool("rest_request", args, raise_on_error=False)
        receipt = pending.meta[AUTHORIZATION_META_KEY]
        decision = await db.get(ActionAuthorization, UUID(receipt["request_id"]))
        assert await answer_action(decision.id, user_id=decision.approver_user_id, approved=True)
        approved = await client.call_tool("rest_request", args, raise_on_error=False,
            meta={AUTHORIZATION_META_KEY: {"continuation": receipt["continuation"]}})
        assert not approved.is_error
        assert len(requests) == 1 and b"Replacement" in requests[0]["raw"]


@pytest.mark.asyncio
async def test_rest_selects_the_authorized_mailbox_of_a_shared_service(rest_setup):
    tool, agents, accounts, requests = rest_setup
    await service.update_service(tool.id, ServiceUpdate(mail_config={}))
    first = accounts[0]
    second = await connection_service.create_connection(tool.id, agents[0].id)
    for row, email in ((first, "first@example.org"), (second, "second@example.org")):
        await connection_service.set_param(row.id, "email_address", email)
        await connection_service.set_connection_function_state(row.id, "rest_request", "enabled")
    await connection_service.set_param(second.id, "api_token", "second-account-token")
    server = await mcp_loader.build_agent_galaris_fastmcp(agents[0].id, allowed_tool_names={"rest_request"})
    async with Client(server) as client:
        mounted, = await client.list_tools()
        assert all(email in mounted.description for email in ("first@example.org", "second@example.org"))
        args = {"service_code": tool.code, "request": {"path": "items"}}
        ambiguous = await client.call_tool("rest_request", args, raise_on_error=False)
        assert ambiguous.is_error and not requests
        selected = await client.call_tool("rest_request", {**args, "account_email": "SECOND@example.org"})
        assert selected.structured_content["status_code"] == 200
        assert requests[-1]["headers"]["authorization"] == "Bearer second-account-token"
        await connection_service.set_connection_function_state(second.id, "rest_request", "disabled")
        assert (await client.call_tool("rest_request", {**args, "account_email": "second@example.org"}, raise_on_error=False)).is_error
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_conversation_rest_discovery_respects_each_services_opt_in(rest_setup):
    tool, agents, connections, requests = rest_setup
    agent_id = agents[0].id
    second = await service.create_service(ServiceCreate(code=f"rest_{uuid4().hex}", label="Task-only API",
        rest_config={"base_url": "https://unused.example.test"}))
    task_only = await connection_service.get_or_create_connection(second.id, agent_id)
    await connection_service.set_connection_function_state(task_only.id, "rest_request", "enabled")
    await service.set_conversation_tool(tool.id, "rest_request", source="native", enabled=True)
    server = await mcp_loader.build_agent_galaris_fastmcp(agent_id, conversation_only=True,
        allowed_tool_names={"rest_request"})
    async with Client(server) as client:
        mounted, = await client.list_tools()
        assert tool.code in mounted.description
        assert second.code not in mounted.description
        denied = await client.call_tool("rest_request", {"service_code": second.code, "request": {}}, raise_on_error=False)
        assert denied.is_error and not requests


@pytest.mark.asyncio
async def test_rest_credentials_inherit_override_and_remain_write_only(db, rest_setup):
    tool, agents, connections, requests = rest_setup
    for agent in agents:
        result = await execute_rest_request(agent_id=agent.id, service_code=tool.code,
            request=RestRequest(method="POST", path="/invoices", params={"draft": True}, json_body={"amount": 12}))
        assert result.status_code == 200
        assert result.body["headers"]["authorization"] == "Bearer [redacted]"
        assert result.body["method"] == "POST"
        assert json.loads(result.body["content"]) == {"amount": 12}
        assert "set-cookie" not in result.headers
    assert [item["headers"]["authorization"] for item in requests] == [
        "Bearer synthetic-global-token", "Bearer synthetic-local-token"]
    encrypted = await db.scalar(select(ConnectionParam.param_value).where(
        ConnectionParam.connection_id == connections[1].id, ConnectionParam.param_name == "api_token"))
    assert encrypted != "synthetic-local-token"
    public = to_public(tool)
    assert public.has_api and public.rest_config.base_url == "${connection:api_url}"
    assert public.global_params["api_token"].configured and public.global_params["api_token"].value is None
    exported = service.serialize_to_yaml(tool)
    assert "rest_config:" in exported
    assert "synthetic-global-token" not in exported and "synthetic-local-token" not in exported
    await service.import_from_yaml_string(exported, overwrite=True)
    assert (await service.get_service_record(tool.code)).rest_config == tool.rest_config


@pytest.mark.asyncio
async def test_rest_requires_live_matching_connection_and_enabled_capability(rest_setup):
    tool, agents, connections, requests = rest_setup
    with pytest.raises(PermissionError):
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code,
            connection_id=connections[1].id, request=RestRequest())
    await connection_service.set_connection_active(connections[0].id, False)
    with pytest.raises(PermissionError):
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest())
    await service.update_service(tool.id, ServiceUpdate(rest_config=None))
    with pytest.raises(RestError, match="not enabled"):
        await execute_rest_request(agent_id=agents[1].id, service_code=tool.code, request=RestRequest())
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_type", ["none", "basic", "header", "query"])
async def test_rest_authentication_modes_and_remote_errors(rest_setup, auth_type):
    tool, agents, connections, requests = rest_setup
    await connection_service.set_params_bulk(connections[0].id, {"login": "synthetic-user"})
    await service.update_service(tool.id, ServiceUpdate(rest_config={"base_url": "${connection:api_url}",
        "auth": {"type": auth_type, "password_param": "api_token"}}))
    result = await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest(path="denied"))
    assert result.status_code == 403  # The third-party service enforces its token's permissions.
    sent = requests[-1]
    if auth_type == "basic":
        expected = base64.b64encode(b"synthetic-user:synthetic-global-token").decode()
        assert sent["headers"]["authorization"] == f"Basic {expected}"
        assert "synthetic-global-token" not in result.model_dump_json()
    elif auth_type == "header":
        assert sent["headers"]["x-api-key"] == "synthetic-global-token"
    elif auth_type == "query":
        assert parse_qs(urlsplit(sent["target"]).query) == {"api_key": ["synthetic-global-token"]}
    else:
        assert "authorization" not in sent["headers"]


@pytest.mark.asyncio
async def test_rest_redirects_size_timeout_text_and_explicit_json_null(rest_setup):
    tool, agents, _, requests = rest_setup
    async def call(**kwargs):
        return await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest(**kwargs))
    assert (await call(path="redirect")).status_code == 302
    assert len(requests) == 1
    assert (await call(path="text")).body == "plain result"
    await call(method="POST", json_body=None)
    assert requests[-1]["content"] == "null"
    await service.update_service(tool.id, ServiceUpdate(rest_config={**tool.rest_config, "max_response_bytes": 1024, "timeout": 1}))
    with pytest.raises(RestError, match="size limit"):
        await call(path="large")
    with pytest.raises(RestError, match="timed out"):
        await call(path="slow")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["https://other.example.test", "//other.example.test", "../secret", "%2e%2e/secret", "%252e%252e/secret", "a\\b", "x?token=y", "x#fragment"])
async def test_rest_credentials_cannot_be_redirected_by_request_paths(rest_setup, path):
    tool, agents, _, requests = rest_setup
    with pytest.raises(RestError):
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest(path=path))
    assert requests == []


@pytest.mark.asyncio
async def test_rest_rejects_public_credentials_and_preserves_omitted_config(rest_setup):
    tool, _, _, _ = rest_setup
    original = dict(tool.rest_config)
    await service.update_service(tool.id, ServiceUpdate(label="Renamed synthetic API"))
    assert tool.rest_config == original
    with pytest.raises(ValueError, match="password type"):
        await service.update_service(tool.id, ServiceUpdate(rest_config={**original, "auth": {"type": "bearer", "param": "login"}}))
    with pytest.raises(ValueError, match="declared"):
        await service.update_service(tool.id, ServiceUpdate(rest_config={**original, "header_params": {"X-Missing": "unknown"}}))
    with pytest.raises(ValidationError):
        RestConfig(base_url="https://example.test?token=literal-secret")


@pytest.mark.asyncio
async def test_rest_live_secret_rotation_headers_and_missing_credentials(rest_setup):
    tool, agents, connections, requests = rest_setup
    await service.update_service(tool.id, ServiceUpdate(rest_config={**tool.rest_config,
        "header_params": {"X-Account": "login"}}))
    with pytest.raises(RestError, match="missing"):
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest())
    assert requests == []
    await connection_service.set_params_bulk(connections[0].id, {"login": "synthetic-account", "api_token": 'synthetic-rotated-"token'})
    result = await execute_rest_request(agent_id=agents[0].id, service_code=tool.code,
        request=RestRequest(headers={"X-Account": "caller", "Authorization": "caller"}))
    assert requests[-1]["headers"]["x-account"] == "synthetic-account"
    assert requests[-1]["headers"]["authorization"] == 'Bearer synthetic-rotated-"token'
    assert result.body["headers"]["authorization"] == "Bearer [redacted]"
    assert result.body["headers"]["x-account"] == "synthetic-account"


@pytest.mark.asyncio
async def test_rest_forced_globals_apply_without_mcp_function_permissions(rest_setup):
    tool, agents, connections, requests = rest_setup
    await connection_service.set_connection_function_state(connections[1].id, "synthetic_operation", "disabled")
    await service.update_global_params(tool.id, ServiceGlobalParamsUpdate(params={
        "api_token": {"value": "synthetic-forced-token", "forced": True}}))
    response = await execute_rest_request(agent_id=agents[1].id, service_code=tool.code,
        request=RestRequest(method="DELETE", path="records/7"))
    assert response.status_code == 200
    assert requests[-1]["headers"]["authorization"] == "Bearer synthetic-forced-token"
    assert requests[-1]["method"] == "DELETE"


@pytest.mark.asyncio
async def test_rest_query_credentials_are_not_exported_in_http_telemetry(rest_setup):
    tool, agents, _, _ = rest_setup
    # A private provider avoids reconfiguring Logfire for later MCP scenarios.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = HTTPXClientInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    try:
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest())
        spans_before_query = len(exporter.get_finished_spans())
        assert spans_before_query > 0
        await service.update_service(tool.id, ServiceUpdate(rest_config={**tool.rest_config, "auth": {"type": "query"}}))
        await execute_rest_request(agent_id=agents[0].id, service_code=tool.code, request=RestRequest())
        assert len(exporter.get_finished_spans()) == spans_before_query
        exported = repr([dict(span.attributes or {}) for span in exporter.get_finished_spans()])
        assert "synthetic-global-token" not in exported and "api_key=" not in exported
    finally:
        instrumentor.uninstrument()
        provider.shutdown()
