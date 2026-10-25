"""Synthetic OAuth provider journeys through persistence and both MCP clients."""

import asyncio
import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx2 as httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection import connection_service, oauth_loopback, oauth_service
from app.connection.models import Connection, ConnectionOAuth
from app.connection.oauth_service import OAuthCallback, OAuthError, Grant
from app.connection.oauth_service import DevicePoll, OAuthStartOptions, RegisteredClient
from pydantic import SecretStr
from app.tools.models import Tool
from app.tools.mcp import build_mcp_server
from app.tools.mcp_loader import _external_transport
from app.tools.schemas import McpConfig
from app.tools.tests.test_tool_admin import synthetic_mcp  # noqa: F401 - shared real HTTP/SSE server
from app.tools import tool_service
from core.user import UserModel
from core.util import get_encryption_service
from core.database import get_db_session


@pytest_asyncio.fixture
async def oauth_connection(db, monkeypatch):
    return await prepare_connection(db, monkeypatch)


@pytest_asyncio.fixture
async def committed_oauth_connection(committed_database, monkeypatch):
    async with get_db_session() as db:
        return await prepare_connection(db, monkeypatch)


async def prepare_connection(db, monkeypatch):
    user = UserModel(email=f"oauth-{uuid4().hex}@example.com", hashed_password="unused")
    title = Title(label="Synthetic OAuth owner", gender="X")
    db.add_all([user, title])
    await db.flush()
    agent = Agent(user_id=user.id, title_id=title.id, code=f"oauth-{uuid4().hex}", first_name="OAuth", last_name="Synthetic")
    tool = Tool(code=f"oauth_{uuid4().hex}", label="Synthetic OAuth MCP",
                mcp_config={"type": "http", "url": "https://mcp.example.test/mcp", "auth": {"type": "none"}})
    db.add_all([agent, tool])
    await db.flush()
    connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
    db.add(connection)
    await db.commit()
    requests = []
    provider = {"token_count": 0, "fail": False, "pkce": True, "dcr": True, "rotate": True}

    def respond(request):
        requests.append(request)
        path = request.url.path
        if path in {"/mcp", "/sse"}:
            return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="https://mcp.example.test/.well-known/oauth-protected-resource", scope="tools.read"'})
        if path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={"resource": provider.get("server_url", tool.mcp_config["url"]), "authorization_servers": ["https://oauth.example.test"]})
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"issuer": "https://oauth.example.test", "authorization_endpoint": "https://oauth.example.test/authorize",
                "token_endpoint": "https://oauth.example.test/token", "registration_endpoint": "https://oauth.example.test/register" if provider["dcr"] else None,
                "response_types_supported": ["code"], "code_challenge_methods_supported": None if provider.get("pkce_unknown") else ["S256"] if provider["pkce"] else [],
                "token_endpoint_auth_methods_supported": [provider["registration_auth"]] if provider.get("registration_auth") else None,
                "client_id_metadata_document_supported": provider.get("cimd", False),
                "device_authorization_endpoint": "https://oauth.example.test/device" if provider.get("device") else None})
        if path == "/register":
            if "registration_response" in provider:
                return provider["registration_response"]
            body = json.loads(request.content)
            if provider.get("registration_auth") and body.get("token_endpoint_auth_method") != provider["registration_auth"]:
                return httpx.Response(400, json={"error": "invalid_client_metadata"})
            redirects = body.get("redirect_uris", [])
            if provider.get("loopback_only") and redirects and urlsplit(redirects[0]).hostname not in {"localhost", "127.0.0.1", "::1"}:
                return httpx.Response(400, json={"error": "invalid_redirect_uri"})
            return httpx.Response(201, json={"client_id": "synthetic-client", "redirect_uris": redirects,
                "token_endpoint_auth_method": provider.get("registration_auth", "none"),
                "client_secret": "synthetic-generated-secret" if provider.get("registration_auth") else None})
        if path == "/device":
            return httpx.Response(200, json={"device_code": "synthetic-private-device-code", "user_code": "SYNTHETIC-CODE",
                "verification_uri": "https://oauth.example.test/activate", "expires_in": 600, "interval": 5})
        if path == "/token":
            if parse_qs(request.content.decode()).get("grant_type") == [oauth_service.DEVICE_GRANT] and provider.get("device_errors"):
                return httpx.Response(400, json={"error": provider["device_errors"].pop(0)})
            if provider["fail"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "SYNTHETIC-PRIVATE-DATA"})
            provider["token_count"] += 1
            token = {"access_token": f"synthetic-access-{provider['token_count']}", "token_type": "Bearer", "expires_in": 3600}
            if provider["rotate"] or provider["token_count"] == 1:
                token["refresh_token"] = f"synthetic-refresh-{provider['token_count']}"
            return httpx.Response(200, json=token)
        raise AssertionError(str(request.url))

    async def network(url, server_url):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)

    monkeypatch.setattr(oauth_service, "_client", network)
    return connection, user.id, tool, requests, provider


def callback(start):
    query = parse_qs(urlsplit(start.authorization_url).query)
    return OAuthCallback(state=query["state"][0], code="synthetic-code"), query


@pytest.mark.asyncio
async def test_loopback_fallback_keeps_the_private_origin_and_reuses_its_client(db, oauth_connection, monkeypatch):
    connection, user_id, tool, requests, provider = oauth_connection
    monkeypatch.setattr(oauth_service.settings, "APP_HOST", "https://private.example.test")
    provider["loopback_only"] = True
    started = await oauth_service.start(connection, user_id)
    data, query = callback(started)
    assert query["redirect_uri"] == [oauth_loopback.REDIRECT_URI]
    assert started.local_script
    assert "https://private.example.test/connection/oauth-callback" in started.local_script
    assert "code_verifier" not in started.local_script
    registration = [request for request in requests if request.url.path == "/register"]
    assert len(registration) == 2
    assert all(json.loads(request.content)["client_name"] == "Galaris" for request in registration)
    await oauth_service.complete(connection, data, user_id)
    token_data = parse_qs(next(request for request in requests if request.url.path == "/token").content.decode())
    assert token_data["redirect_uri"] == [oauth_loopback.REDIRECT_URI]
    assert await oauth_service.access_token(connection.id, tool.mcp_config["url"]) == "synthetic-access-1"
    restarted = await oauth_service.start(connection, user_id)
    assert restarted.local_script
    registrations = [json.loads(request.content) for request in requests if request.url.path == "/register"]
    assert sum(body.get("redirect_uris") == [oauth_loopback.REDIRECT_URI] for body in registrations) == 1
    await oauth_service.disconnect(connection)
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.complete(connection, callback(restarted)[0], user_id)


@pytest.mark.asyncio
async def test_localhost_browser_gets_direct_oauth_without_a_script(oauth_connection, monkeypatch):
    connection, user_id, _, requests, provider = oauth_connection
    monkeypatch.setattr(oauth_service.settings, "APP_HOST", "https://private.example.test")
    provider["loopback_only"] = True
    started = await oauth_service.start(connection, user_id, OAuthStartOptions(browser_origin="http://localhost:8484"))
    data, query = callback(started)
    assert query["redirect_uri"] == ["http://localhost:8484/connection/oauth-callback"]
    assert not started.local_script
    assert started.method == "redirect"
    assert len([request for request in requests if request.url.path == "/register"]) == 1
    await oauth_service.complete(connection, data, user_id)
    assert (await oauth_service.status(connection)).connected
    with pytest.raises(OAuthError, match="configuration"):
        await oauth_service.start(connection, user_id, OAuthStartOptions(browser_origin="https://attacker.example.test"))


@pytest.mark.asyncio
async def test_device_flow_precedes_relay_and_obeys_polling_slowdown(db, oauth_connection, monkeypatch):
    connection, user_id, _, requests, provider = oauth_connection
    monkeypatch.setattr(oauth_service.settings, "APP_HOST", "https://private.example.test")
    provider.update(loopback_only=True, device=True, device_errors=["authorization_pending", "slow_down"])
    clock = [time.time()]
    monkeypatch.setattr(oauth_service.time, "time", lambda: clock[0])
    started = await oauth_service.start(connection, user_id)
    assert started.method == "device" and started.device and not started.local_script
    assert "synthetic-private-device-code" not in started.model_dump_json()
    data = DevicePoll(state=started.device.state)
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.poll_device(connection, data, user_id + 1)
    row = await db.get(ConnectionOAuth, connection.id)
    assert "synthetic-private-device-code" not in row.pending
    assert not (await oauth_service.poll_device(connection, data, user_id)).connected
    assert not any(request.url.path == "/token" for request in requests)
    clock[0] += 6
    assert (await oauth_service.poll_device(connection, data, user_id)).interval == 5
    clock[0] += 6
    assert (await oauth_service.poll_device(connection, data, user_id)).interval == 10
    calls = sum(request.url.path == "/token" for request in requests)
    assert not (await oauth_service.poll_device(connection, data, user_id)).connected
    assert sum(request.url.path == "/token" for request in requests) == calls
    clock[0] += 11
    assert (await oauth_service.poll_device(connection, data, user_id)).connected
    assert (await oauth_service.status(connection)).connected
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.poll_device(connection, data, user_id)
    assert sum(request.url.path == "/register" for request in requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["access_denied", "expired_token"])
async def test_device_refusal_is_terminal_without_script_fallback(db, oauth_connection, monkeypatch, error):
    connection, user_id, _, requests, provider = oauth_connection
    provider.update(device=True, pkce=False, device_errors=[error])
    started = await oauth_service.start(connection, user_id)
    assert started.device
    monkeypatch.setattr(oauth_service.time, "time", lambda: 9_999_999_999)
    with pytest.raises(OAuthError, match="authorization_denied" if error == "access_denied" else "invalid_state"):
        await oauth_service.poll_device(connection, DevicePoll(state=started.device.state), user_id)
    row = await db.get(ConnectionOAuth, connection.id)
    assert row.pending is None and row.grant is None
    assert sum(request.url.path == "/register" for request in requests) == 1


@pytest.mark.asyncio
async def test_device_concurrent_poll_and_disconnect_ignore_a_late_token(committed_oauth_connection, monkeypatch):
    connection, user_id, _, _, provider = committed_oauth_connection
    provider.update(device=True, pkce=False)
    async with get_db_session() as db:
        started = await oauth_service.start(connection, user_id)
        assert started.device
        row = await db.get(ConnectionOAuth, connection.id)
        pending = oauth_service.Pending.model_validate_json(get_encryption_service().decrypt(row.pending))
        pending.device.next_poll_at = 0
        row.pending = get_encryption_service().encrypt(pending.model_dump_json())
    data = DevicePoll(state=started.device.state)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []
    async def upstream(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"access_token": "synthetic-late-device-token", "token_type": "Bearer"})
    async def network(url, server_url):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(oauth_service, "_client", network)
    async def poll():
        async with get_db_session():
            try:
                await oauth_service.poll_device(connection, data, user_id)
            except OAuthError as exc:
                return str(exc)
    task = asyncio.create_task(poll())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with get_db_session():
            assert not (await oauth_service.poll_device(connection, data, user_id)).connected
        assert len(calls) == 1
        async with get_db_session():
            await oauth_service.disconnect(connection)
    finally:
        release.set()
        result = await asyncio.wait_for(task, 5)
    assert result == "invalid_state"
    async with get_db_session() as db:
        assert await db.get(ConnectionOAuth, connection.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("public_metadata", [True, False])
@pytest.mark.parametrize("local_browser", [False, True])
async def test_client_metadata_documents_and_dcr_fallback(oauth_connection, monkeypatch, public_metadata, local_browser):
    connection, user_id, _, requests, provider = oauth_connection
    monkeypatch.setattr(oauth_service.settings, "APP_HOST", "https://client.example.test:443")
    options = OAuthStartOptions(browser_origin="http://localhost:8484") if local_browser else OAuthStartOptions()
    callback_uri = oauth_service.redirect_uri(options.browser_origin)
    provider.update(cimd=True, dcr=not public_metadata)
    async def public_document(url, **kwargs):
        if not public_metadata:
            raise ValueError("Synthetic private origin")
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json=oauth_service.client_document(callback_uri).model_dump(mode="json", exclude_none=True))))
    monkeypatch.setattr(oauth_service, "mcp_http_client", public_document)
    started = await oauth_service.start(connection, user_id, options)
    data, query = callback(started)
    assert query["client_id"] == [oauth_service.client_document(callback_uri).client_id if public_metadata else "synthetic-client"]
    assert not started.local_script
    assert sum(request.url.path == "/register" for request in requests) == (0 if public_metadata else 1)
    await oauth_service.complete(connection, data, user_id)
    assert (await oauth_service.status(connection)).connected


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["client_secret_basic", "client_secret_post"])
@pytest.mark.parametrize("registration_denied", [None, 401, 403])
async def test_preregistered_client_is_requested_only_when_automatic_setup_is_unavailable(db, oauth_connection, method, registration_denied):
    connection, user_id, _, requests, provider = oauth_connection
    provider["dcr"] = registration_denied is not None
    if registration_denied:
        provider["registration_response"] = httpx.Response(registration_denied)
    configure = await oauth_service.start(connection, user_id)
    assert configure.method == "configure" and not configure.local_script
    assert await db.get(ConnectionOAuth, connection.id) is None
    before = len(requests)
    started = await oauth_service.start(connection, user_id, OAuthStartOptions(client=RegisteredClient(
        client_id="synthetic-registered-client", client_secret=SecretStr("synthetic-client-secret"), token_endpoint_auth_method=method)))
    assert "synthetic-client-secret" not in started.model_dump_json()
    await oauth_service.complete(connection, callback(started)[0], user_id)
    request = next(request for request in requests if request.url.path == "/token")
    if method == "client_secret_basic":
        assert request.headers["Authorization"].startswith("Basic ")
        assert "client_secret" not in parse_qs(request.content.decode())
    else:
        assert parse_qs(request.content.decode())["client_secret"] == ["synthetic-client-secret"]
        assert "Authorization" not in request.headers
    row = await db.get(ConnectionOAuth, connection.id)
    assert "synthetic-client-secret" not in row.grant
    assert not any(request.url.path == "/register" for request in requests[before:])


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["client_secret_basic", "client_secret_post"])
async def test_dynamic_registration_negotiates_the_advertised_client_authentication(oauth_connection, method):
    connection, user_id, _, requests, provider = oauth_connection
    provider["registration_auth"] = method
    started = await oauth_service.start(connection, user_id)
    assert not started.local_script and started.method == "redirect"
    assert "synthetic-generated-secret" not in started.model_dump_json()
    registrations = [json.loads(request.content) for request in requests if request.url.path == "/register"]
    assert [body["token_endpoint_auth_method"] for body in registrations] == ["none", method]
    await oauth_service.complete(connection, callback(started)[0], user_id)
    token = next(request for request in requests if request.url.path == "/token")
    if method == "client_secret_basic":
        assert token.headers["Authorization"].startswith("Basic ")
    else:
        assert parse_qs(token.content.decode())["client_secret"] == ["synthetic-generated-secret"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["https://mcp.example.test/mcp", "https://mcp.example.test/"])
@pytest.mark.parametrize("pkce_unknown", [False, True])
async def test_oauth_pkce_encryption_refresh_and_disconnect(db, oauth_connection, resource, pkce_unknown):
    connection, user_id, tool, requests, provider = oauth_connection
    provider["server_url"] = resource
    provider["pkce_unknown"] = pkce_unknown
    assert not (await oauth_service.status(connection)).connected
    started = await oauth_service.start(connection, user_id)
    data, query = callback(started)
    # Metadata URLs gain a trailing slash at the origin in the SDK model;
    # a valid RFC 9207 issuer without that slash must still match.
    data.iss = "https://oauth.example.test"
    assert query["resource"] == [resource]
    assert query["scope"] == ["tools.read"]
    assert query["code_challenge_method"] == ["S256"]
    row = await db.get(ConnectionOAuth, connection.id)
    assert data.state not in row.pending
    assert data.state != row.state_hash
    assert (await oauth_service.status(connection)).pending
    await oauth_service.complete(connection, data, user_id)
    token_request = next(item for item in requests if item.url.path == "/token")
    token_data = parse_qs(token_request.content.decode())
    assert token_data["resource"] == [resource]
    verifier = token_data["code_verifier"][0]
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=") == query["code_challenge"][0]
    row = await db.get(ConnectionOAuth, connection.id)
    assert "synthetic-access" not in row.grant and "synthetic-refresh" not in row.grant
    assert row.pending is None
    public = await connection_service.get_params_for_api(connection)
    assert "synthetic" not in repr(public[1:])
    assert "synthetic-access" not in (await oauth_service.status(connection)).model_dump_json()
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.complete(connection, data, user_id)
    grant = Grant.model_validate_json(get_encryption_service().decrypt(row.grant))
    grant.token_expires_at = time.time() - 1
    row.grant = get_encryption_service().encrypt(grant.model_dump_json())
    await db.commit()
    provider["rotate"] = False
    assert await oauth_service.access_token(connection.id, tool.mcp_config["url"]) == "synthetic-access-2"
    grant = Grant.model_validate_json(get_encryption_service().decrypt(row.grant))
    assert grant.token.refresh_token == "synthetic-refresh-1"
    refresh = parse_qs(requests[-1].content.decode())
    assert refresh["grant_type"] == ["refresh_token"]
    assert refresh["resource"] == [resource]
    await oauth_service.disconnect(connection)
    with pytest.raises(OAuthError, match="authorization_required"):
        await oauth_service.access_token(connection.id, tool.mcp_config["url"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["foreign_user", "wrong_state", "expired", "denied", "changed_url", "changed_agent", "inactive", "wrong_issuer", "provider_error"])
async def test_callback_rejects_invalid_or_stale_authorizations(db, oauth_connection, failure):
    connection, user_id, tool, requests, provider = oauth_connection
    data, _ = callback(await oauth_service.start(connection, user_id))
    if failure == "foreign_user":
        user_id += 10000
    elif failure == "wrong_state":
        data.state = "synthetic-unrelated-state-000000"
    elif failure == "expired":
        row = await db.get(ConnectionOAuth, connection.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    elif failure == "denied":
        data.error = "access_denied"
    elif failure == "changed_url":
        tool.mcp_config = {**tool.mcp_config, "url": "https://other.example.test/mcp"}
        await db.commit()
    elif failure == "changed_agent":
        agent = await db.get(Agent, connection.agent_id)
        other = Agent(user_id=user_id, title_id=agent.title_id, code=f"changed-{uuid4().hex}", first_name="Changed", last_name="Synthetic")
        db.add(other)
        await db.flush()
        connection.agent_id = other.id
        await db.commit()
    elif failure == "inactive":
        connection.active = False
        await db.commit()
    elif failure == "wrong_issuer":
        data.iss = "https://foreign.example.test"
    elif failure == "provider_error":
        provider["fail"] = True
    with pytest.raises(OAuthError) as error:
        await oauth_service.complete(connection, data, user_id)
    assert "SYNTHETIC-PRIVATE-DATA" not in str(error.value)
    assert not (await db.get(ConnectionOAuth, connection.id)).grant
    assert provider["token_count"] == 0
    if failure in {"denied", "provider_error"}:
        with pytest.raises(OAuthError, match="invalid_state"):
            await oauth_service.complete(connection, data, user_id)


@pytest.mark.asyncio
async def test_latest_authorization_wins_and_disconnect_prevents_late_completion(db, oauth_connection, monkeypatch):
    connection, user_id, tool, requests, provider = oauth_connection
    old, _ = callback(await oauth_service.start(connection, user_id))
    current, _ = callback(await oauth_service.start(connection, user_id))
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.complete(connection, old, user_id)
    exchange = oauth_service._exchange

    async def disconnect_during_exchange(*args):
        result = await exchange(*args)
        await oauth_service.disconnect(connection)
        return result

    monkeypatch.setattr(oauth_service, "_exchange", disconnect_during_exchange)
    with pytest.raises(OAuthError, match="invalid_state"):
        await oauth_service.complete(connection, current, user_id)
    assert await db.get(ConnectionOAuth, connection.id) is None


@pytest.mark.asyncio
async def test_automatic_registration_and_pkce_requirement(oauth_connection):
    connection, user_id, tool, requests, provider = oauth_connection
    provider["dcr"] = False
    assert (await oauth_service.start(connection, user_id)).method == "configure"
    provider["dcr"] = True
    data, query = callback(await oauth_service.start(connection, user_id))
    assert query["client_id"] == ["synthetic-client"]
    await oauth_service.complete(connection, data, user_id)
    provider["pkce"] = False
    with pytest.raises(OAuthError, match="pkce_required"):
        await oauth_service.start(connection, user_id)


@pytest.mark.asyncio
async def test_grant_isolated_between_connections_and_invalidated_by_config(db, oauth_connection):
    from app.connection.facade import mcp_oauth_auth
    connection, user_id, tool, requests, provider = oauth_connection
    data, _ = callback(await oauth_service.start(connection, user_id))
    await oauth_service.complete(connection, data, user_id)
    assert await oauth_service.access_token(connection.id, tool.mcp_config["url"]) == "synthetic-access-1"
    agent = await db.get(Agent, connection.agent_id)
    other_agent = Agent(user_id=user_id, title_id=agent.title_id, code=f"oauth-other-{uuid4().hex}", first_name="Other", last_name="Synthetic")
    db.add(other_agent)
    await db.flush()
    other = Connection(agent_id=other_agent.id, tool_id=tool.id, active=True)
    db.add(other)
    await db.commit()
    _, authorized_params = await connection_service.get_params_as_dict(connection)
    _, other_params = await connection_service.get_params_as_dict(other)
    assert mcp_oauth_auth(authorized_params, tool.mcp_config["url"]) is not None
    assert mcp_oauth_auth(other_params, tool.mcp_config["url"]) is None
    assert mcp_oauth_auth({"oauth_enabled": True, "connection_id": connection.id}, tool.mcp_config["url"]) is None
    with pytest.raises(OAuthError, match="authorization_required"):
        await oauth_service.access_token(other.id, tool.mcp_config["url"])
    tool.mcp_config = {**tool.mcp_config, "url": "https://other.example.test/mcp"}
    await db.commit()
    assert (await oauth_service.status(connection)).reconnect_required
    with pytest.raises(OAuthError, match="authorization_required"):
        await oauth_service.access_token(connection.id, tool.mcp_config["url"])


@pytest.mark.asyncio
async def test_real_http_and_sse_clients_discover_and_execute_with_oauth(committed_oauth_connection, synthetic_mcp):
    connection, user_id, tool, requests, provider = committed_oauth_connection
    url, calls = synthetic_mcp
    provider["server_url"] = url
    async with get_db_session() as db:
        tool = await db.get(Tool, tool.id)
        # OAuth overrides ordinary Tool credentials for this connection only.
        tool.mcp_config = {"type": "sse" if url.endswith("/sse") else "http", "url": url,
                           "auth": {"type": "bearer", "param": "unused_token"},
                           "headers": {"Authorization": "${connection:unused_token}"}}
        await db.commit()
        data, _ = callback(await oauth_service.start(connection, user_id))
        await oauth_service.complete(connection, data, user_id)
        current = await tool_service.get_tool_by_id(tool.id)
        _, params = await connection_service.get_params_as_dict(connection)
    # Internal harness discovery uses Pydantic AI; the aggregate proxy uses FastMCP.
    server = build_mcp_server(current, params, prefix_tools=False)
    async with server:
        assert "lookup" in {item.name for item in await server.list_tools()}
    async with Client(_external_transport(current, params)) as client:
        assert "lookup" in {item.name for item in await client.list_tools()}
        await client.call_tool("lookup", {"value": "synthetic OAuth call"})
    assert calls == ["synthetic OAuth call"]
    assert calls.headers == ["Bearer synthetic-access-1"]
    assert provider["token_count"] == 1
    from app.connection.facade import mcp_oauth_auth
    from app.tools.mcp_diagnostics import diagnose_mcp_connection
    from app.tools.schemas import ToolMcpTestRequest
    http_client = httpx.AsyncClient()
    try:
        diagnostic = await diagnose_mcp_connection(ToolMcpTestRequest(
            code=current.code, mcp_config=current.mcp), http_client=http_client,
            mcp_auth=mcp_oauth_auth(params, url))
    finally:
        await http_client.aclose()
    assert diagnostic.success, diagnostic
    assert "lookup" in {item.name for item in diagnostic.tools}


@pytest.mark.asyncio
async def test_concurrent_refresh_rotates_once_and_401_requires_reauthorization(committed_oauth_connection):
    from app.connection.oauth_runtime import ConnectionOAuthAuth
    connection, user_id, tool, requests, provider = committed_oauth_connection
    url = tool.mcp_config["url"]
    async with get_db_session() as db:
        data, _ = callback(await oauth_service.start(connection, user_id))
        await oauth_service.complete(connection, data, user_id)
        row = await db.get(ConnectionOAuth, connection.id)
        grant = Grant.model_validate_json(get_encryption_service().decrypt(row.grant))
        grant.token_expires_at = time.time() - 1
        row.grant = get_encryption_service().encrypt(grant.model_dump_json())

    headers = []
    async def call(status=200):
        def upstream(request):
            headers.append(request.headers["authorization"])
            return httpx.Response(status)
        async with httpx.AsyncClient(auth=ConnectionOAuthAuth(connection.id, url), transport=httpx.MockTransport(upstream)) as client:
            return await client.get(url)
    await asyncio.gather(call(), call())
    assert headers == ["Bearer synthetic-access-2"] * 2
    assert provider["token_count"] == 2
    await call(401)
    assert len(headers) == 3  # The rejected request is never replayed.
    async with get_db_session():
        assert (await oauth_service.status(connection)).reconnect_required
    with pytest.raises(ValueError, match="Authorize"):
        await call()


@pytest.mark.asyncio
async def test_http_oauth_requires_web_edit_privileges_and_managed_agent(committed_oauth_connection, monkeypatch):
    monkeypatch.setattr(oauth_service.settings, "APP_HOST", "https://orchestrator.example.com")
    from core.authorize import Assignment, Privilege, Role
    from core.user import encrypt_password
    from main import app
    from core.database import database as database_module, middleware as database_middleware
    monkeypatch.setattr(database_middleware, "AsyncSessionLocal", database_module.AsyncSessionLocal)

    connection, user_id, tool, requests, provider = committed_oauth_connection
    async with get_db_session() as db:
        user = await db.get(UserModel, user_id)
        user.hashed_password = encrypt_password("Synthetic-OAuth-password-123")
        email = user.email
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(["CONNECTION_ACCESS", "CONNECTION_EDIT"]))))
        role = Role(code=f"oauth-{uuid4().hex}", display_name="Synthetic OAuth manager", privileges=privileges)
        stranger = UserModel(email=f"foreign-{uuid4().hex}@example.test", hashed_password="unused")
        db.add_all([role, stranger])
        await db.flush()
        db.add(Assignment(user_id=user_id, role_id=role.id, is_default=True))
        own_agent = await db.get(Agent, connection.agent_id)
        other_agent = Agent(user_id=stranger.id, title_id=own_agent.title_id, code=f"foreign-{uuid4().hex}", first_name="Foreign", last_name="Synthetic")
        db.add(other_agent)
        await db.flush()
        other = Connection(agent_id=other_agent.id, tool_id=tool.id, active=True)
        db.add(other)
        await db.flush()
        other_id = other.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get(f"/api/connections/{connection.id}/oauth")).status_code == 401
        document = await client.get("/api/connections/oauth/client-metadata")
        assert document.status_code == 200
        assert document.json()["client_name"] == "Galaris"
        assert not any("secret" in key for key in document.json())
        local_document = await client.get("/api/connections/oauth/client-metadata/loopback/http/localhost/8484")
        assert local_document.status_code == 200
        assert local_document.json()["client_id"].endswith("/oauth/client-metadata/loopback/http/localhost/8484")
        assert local_document.json()["redirect_uris"] == ["http://localhost:8484/connection/oauth-callback"]
        assert (await client.get("/api/connections/oauth/client-metadata/loopback/http/attacker.example/8484")).status_code == 422
        assert (await client.post(f"/api/connections/{connection.id}/oauth/device", json={"state": "synthetic-no-session-state-000001"})).status_code == 401
        login = await client.post("/api/auth/login-json", json={"email": email, "password": "Synthetic-OAuth-password-123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        status = await client.get(f"/api/connections/{connection.id}/oauth", headers=headers)
        assert status.status_code == 200, status.text
        for method, path, body in [
            ("GET", "oauth", None), ("POST", "oauth/start", None),
            ("POST", "oauth/callback", {"state": "synthetic-foreign-state-000000"}), ("DELETE", "oauth", None),
            ("POST", "oauth/device", {"state": "synthetic-foreign-state-000000"}),
        ]:
            response = await client.request(method, f"/api/connections/{other_id}/{path}", headers=headers, json=body)
            assert response.status_code == 404, response.text
        for provider_response, expected in [
            (httpx.Response(400, json={"error": "invalid_client_metadata", "error_description": "SYNTHETIC-PRIVATE-DATA"}), "invalid_client_metadata"),
            (httpx.Response(400, json={"error": "invalid_redirect_uri", "error_description": "SYNTHETIC-PRIVATE-DATA"}), "invalid_redirect_uri"),
            (httpx.Response(503, json={"error": "SYNTHETIC-PRIVATE-DATA"}), "HTTP 503"),
            (httpx.Response(201, json={"client_id": "SYNTHETIC-PRIVATE-DATA"}), "invalid OAuth registration response"),
        ]:
            provider["registration_response"] = provider_response
            failed = await client.post(f"/api/connections/{connection.id}/oauth/start", headers=headers)
            assert failed.status_code == 400, failed.text
            assert expected in failed.json()["detail"]
            assert "SYNTHETIC-PRIVATE-DATA" not in failed.text
            if expected == "invalid_redirect_uri":
                assert oauth_loopback.REDIRECT_URI in failed.json()["detail"]
        async with get_db_session() as db:
            assert await db.get(ConnectionOAuth, connection.id) is None
        del provider["registration_response"]
        started = await client.post(f"/api/connections/{connection.id}/oauth/start", headers=headers)
        assert started.status_code == 200, started.text
        assert (await client.delete(f"/api/connections/{connection.id}/oauth", headers=headers)).status_code == 204
        async with get_db_session() as db:
            role = await db.get(Role, role.id)
            # Keep read access but remove authorization-management permission.
            await db.refresh(role, ["privileges"])
            role.privileges = [item for item in role.privileges if item.code == "CONNECTION_ACCESS"]
        login = await client.post("/api/auth/login-json", json={"email": email, "password": "Synthetic-OAuth-password-123"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert (await client.get(f"/api/connections/{connection.id}/oauth", headers=headers)).status_code == 200
        assert (await client.post(f"/api/connections/{connection.id}/oauth/start", headers=headers)).status_code == 403
        assert (await client.post(f"/api/connections/{connection.id}/oauth/device", headers=headers, json={"state": "synthetic-no-edit-state-000001"})).status_code == 403


def test_legacy_tool_oauth_configuration_is_readable_without_manual_settings():
    # OAuth now belongs to the connection; obsolete Tool settings are ignored.
    config = McpConfig.model_validate({"type": "http", "url": "https://mcp.example.test/mcp",
        "auth": {"type": "oauth", "oauth_client_id": "legacy-client", "oauth_scopes": "legacy-scope"}})
    assert config.auth.type == "none"
    assert "oauth_client_id" not in config.model_dump_json()
    assert "oauth_scopes" not in config.model_dump_json()
