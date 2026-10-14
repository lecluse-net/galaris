"""REST journeys use real connection persistence and a synthetic HTTP service."""

import asyncio
import base64
import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import connection_service
from app.connection.models import ConnectionParam
from app.tools import RestConfig, RestError, RestRequest, execute_rest_request, tool_service
from app.tools.projections import to_public
from app.tools.schemas import ToolCreate, ToolGlobalParamsUpdate, ToolUpdate

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
            item = {"method": method, "target": target, "headers": headers, "content": content.decode()}
            requests.append(item)
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


@pytest_asyncio.fixture
async def rest_setup(db, api_server):
    base, requests = api_server
    title = Title(label="Synthetic REST operator", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"rest-{uuid4().hex}", first_name=name,
                    last_name="Synthetic", agent_driver="internal") for name in ("First", "Second")]
    db.add_all(agents)
    await db.flush()
    tool = await tool_service.create_tool(ToolCreate(code=f"rest_{uuid4().hex}", label="Synthetic API",
        rest_config={"base_url": "${connection:api_url}", "auth": {"type": "bearer"}},
        connection_schema={"params": {"api_url": {"type": "string", "required": False},
            "api_token": {"type": "password", "required": False},
            "login": {"type": "string", "required": False}}}))
    await tool_service.update_global_params(tool.id, ToolGlobalParamsUpdate(params={
        "api_url": {"value": base}, "api_token": {"value": "synthetic-global-token"}}))
    connections = [await connection_service.get_or_create_connection(tool.id, agent.id) for agent in agents]
    await connection_service.set_params_bulk(connections[1].id, {"api_token": "synthetic-local-token"})
    return tool, agents, connections, requests


@pytest.mark.asyncio
async def test_rest_credentials_inherit_override_and_remain_write_only(db, rest_setup):
    tool, agents, connections, requests = rest_setup
    for agent in agents:
        result = await execute_rest_request(agent_id=agent.id, tool_code=tool.code,
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
    exported = tool_service.serialize_to_yaml(tool)
    assert "rest_config:" in exported
    assert "synthetic-global-token" not in exported and "synthetic-local-token" not in exported
    await tool_service.import_from_yaml_string(exported, overwrite=True)
    assert (await tool_service.get_tool_record(tool.code)).rest_config == tool.rest_config


@pytest.mark.asyncio
async def test_rest_requires_live_matching_connection_and_enabled_capability(rest_setup):
    tool, agents, connections, requests = rest_setup
    with pytest.raises(PermissionError):
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code,
            connection_id=connections[1].id, request=RestRequest())
    await connection_service.set_connection_active(connections[0].id, False)
    with pytest.raises(PermissionError):
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest())
    await tool_service.update_tool(tool.id, ToolUpdate(rest_config=None))
    with pytest.raises(RestError, match="not enabled"):
        await execute_rest_request(agent_id=agents[1].id, tool_code=tool.code, request=RestRequest())
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_type", ["none", "basic", "header", "query"])
async def test_rest_authentication_modes_and_remote_errors(rest_setup, auth_type):
    tool, agents, connections, requests = rest_setup
    await connection_service.set_params_bulk(connections[0].id, {"login": "synthetic-user"})
    await tool_service.update_tool(tool.id, ToolUpdate(rest_config={"base_url": "${connection:api_url}",
        "auth": {"type": auth_type, "password_param": "api_token"}}))
    result = await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest(path="denied"))
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
        return await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest(**kwargs))
    assert (await call(path="redirect")).status_code == 302
    assert len(requests) == 1
    assert (await call(path="text")).body == "plain result"
    await call(method="POST", json_body=None)
    assert requests[-1]["content"] == "null"
    await tool_service.update_tool(tool.id, ToolUpdate(rest_config={**tool.rest_config, "max_response_bytes": 1024, "timeout": 1}))
    with pytest.raises(RestError, match="size limit"):
        await call(path="large")
    with pytest.raises(RestError, match="timed out"):
        await call(path="slow")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["https://other.example.test", "//other.example.test", "../secret", "%2e%2e/secret", "%252e%252e/secret", "a\\b", "x?token=y", "x#fragment"])
async def test_rest_credentials_cannot_be_redirected_by_request_paths(rest_setup, path):
    tool, agents, _, requests = rest_setup
    with pytest.raises(RestError):
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest(path=path))
    assert requests == []


@pytest.mark.asyncio
async def test_rest_rejects_public_credentials_and_preserves_omitted_config(rest_setup):
    tool, _, _, _ = rest_setup
    original = dict(tool.rest_config)
    await tool_service.update_tool(tool.id, ToolUpdate(label="Renamed synthetic API"))
    assert tool.rest_config == original
    with pytest.raises(ValueError, match="password type"):
        await tool_service.update_tool(tool.id, ToolUpdate(rest_config={**original, "auth": {"type": "bearer", "param": "login"}}))
    with pytest.raises(ValueError, match="declared"):
        await tool_service.update_tool(tool.id, ToolUpdate(rest_config={**original, "header_params": {"X-Missing": "unknown"}}))
    with pytest.raises(ValidationError):
        RestConfig(base_url="https://example.test?token=literal-secret")


@pytest.mark.asyncio
async def test_rest_live_secret_rotation_headers_and_missing_credentials(rest_setup):
    tool, agents, connections, requests = rest_setup
    await tool_service.update_tool(tool.id, ToolUpdate(rest_config={**tool.rest_config,
        "header_params": {"X-Account": "login"}}))
    with pytest.raises(RestError, match="missing"):
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest())
    assert requests == []
    await connection_service.set_params_bulk(connections[0].id, {"login": "synthetic-account", "api_token": 'synthetic-rotated-"token'})
    result = await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code,
        request=RestRequest(headers={"X-Account": "caller", "Authorization": "caller"}))
    assert requests[-1]["headers"]["x-account"] == "synthetic-account"
    assert requests[-1]["headers"]["authorization"] == 'Bearer synthetic-rotated-"token'
    assert result.body["headers"]["authorization"] == "Bearer [redacted]"
    assert result.body["headers"]["x-account"] == "synthetic-account"


@pytest.mark.asyncio
async def test_rest_forced_globals_apply_without_mcp_function_permissions(rest_setup):
    tool, agents, connections, requests = rest_setup
    await connection_service.set_connection_function_state(connections[1].id, "synthetic_operation", "disabled")
    await tool_service.update_global_params(tool.id, ToolGlobalParamsUpdate(params={
        "api_token": {"value": "synthetic-forced-token", "forced": True}}))
    response = await execute_rest_request(agent_id=agents[1].id, tool_code=tool.code,
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
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest())
        spans_before_query = len(exporter.get_finished_spans())
        assert spans_before_query > 0
        await tool_service.update_tool(tool.id, ToolUpdate(rest_config={**tool.rest_config, "auth": {"type": "query"}}))
        await execute_rest_request(agent_id=agents[0].id, tool_code=tool.code, request=RestRequest())
        assert len(exporter.get_finished_spans()) == spans_before_query
        exported = repr([dict(span.attributes or {}) for span in exporter.get_finished_spans()])
        assert "synthetic-global-token" not in exported and "api_key=" not in exported
    finally:
        instrumentor.uninstrument()
        provider.shutdown()
