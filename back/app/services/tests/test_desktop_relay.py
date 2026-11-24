"""Exercise an outbound desktop link through independently authenticated HTTP requests."""

import asyncio
from secrets import token_urlsafe
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from httpx import ASGITransport, AsyncClient

from app.services import service
from app.services.desktop_relay import API_PATH, DESKTOP_HEADER, SERVICE_HEADER
from core.authorize import Privileges
from core.authorize.tests.test_guard_policy_parameters import actor
from core.database import get_db_session
from core.database import middleware
from main import app


@pytest.mark.asyncio
async def test_desktop_relay_registration_is_scoped_and_calls_are_not_replayed(
    committed_database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    admin, _ = await actor([Privileges.SERVICE_EDIT])
    reader, _ = await actor([Privileges.SERVICE_ACCESS, Privileges.CONNECTION_ACCESS])
    desktop = {DESKTOP_HEADER: token_urlsafe(32)}
    other = {DESKTOP_HEADER: token_urlsafe(32)}
    relay = uuid4()
    registration = {"relay": str(relay), "label": "Synthetic desktop inventory"}
    path = f"{API_PATH}/{relay}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.post(API_PATH, headers=reader | desktop, json=registration)).status_code == 403
        created = await client.post(API_PATH, headers=admin | desktop, json=registration)
        assert created.status_code == 200, created.text
        assert (await client.post(API_PATH, headers=admin | desktop, json=registration)).json() == created.json()
        assert (await client.post(API_PATH, headers=admin | other, json=registration)).status_code == 403
        service_id = created.json()["service_id"]
        async with get_db_session():
            registered = await service.get_service_by_id(service_id)
        assert registered is not None and registered.mcp is not None
        assert registered.mcp.url is not None and registered.mcp.url.endswith(path + "/mcp")
        assert registered.mcp.type == "http"
        service_headers = {SERVICE_HEADER: registered.mcp.headers[SERVICE_HEADER]}
        public = await client.get(f"/api/services/{service_id}", headers=reader)
        assert public.is_success and public.json()["desktop_mcp_relay"] is True
        options = await client.get("/api/connections/service-options", headers=reader)
        assert options.is_success
        relay_option = next(option for option in options.json() if option["id"] == service_id)
        assert relay_option["desktop_mcp_relay"] is True
        assert relay_option["connection_schema"]["params"] == {}
        assert service_headers[SERVICE_HEADER] not in public.text + options.text
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        assert (await client.post(path + "/mcp", json=init, headers=service_headers)).status_code == 503
        assert (await client.post(path + "/poll", headers=other)).status_code == 403
        assert (await client.post(path + "/mcp", json=init, headers=desktop)).status_code == 403

        async def receive(request: dict, result: dict, headers: dict[str, str]):
            async with asyncio.TaskGroup() as group:
                pending = group.create_task(client.post(path + "/poll", headers=desktop))
                # Presence is updated by the outbound poll before a client can connect.
                for _ in range(100):
                    upstream = group.create_task(client.post(path + "/mcp", json=request, headers=headers))
                    response = await asyncio.wait({pending, upstream}, return_when=asyncio.FIRST_COMPLETED)
                    if pending in response[0] or upstream.result().status_code != 503:
                        break
                    await asyncio.sleep(0.02)
                delivery = (await pending).json()
                assert delivery["message"] == request
                reply = {"request": delivery["request"], "response": {"result": result}}
                assert (await client.post(path + "/complete", json=reply, headers=other)).status_code == 403
                assert (await client.post(path + "/complete", json=reply, headers=desktop)).status_code == 204
                assert (await client.post(path + "/complete", json={
                    **reply, "response": {"result": {"unexpected": True}},
                }, headers=desktop)).status_code == 204
                return await upstream

        opened = await receive(init, {"capabilities": {"tools": {}}, "protocolVersion": "2025-11-25"}, service_headers)
        assert opened.status_code == 200
        session = service_headers | {"Mcp-Session-Id": opened.headers["Mcp-Session-Id"]}
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "inventory", "arguments": {}}}
        result = await receive(call, {"content": [{"type": "text", "text": "synthetic"}]}, session)
        assert result.json() == {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "synthetic"}]}}

        async def serve_desktop() -> None:
            results = {
                "initialize": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {}},
                               "serverInfo": {"name": "Synthetic desktop", "version": "1"}},
                "tools/list": {"tools": [{"name": "inventory", "inputSchema": {"type": "object"}}]},
                "tools/call": {"content": [{"type": "text", "text": "synthetic"}]},
                "resources/read": {"contents": [{"uri": "ui://inventory/table", "text": "<p>Synthetic stock</p>",
                                                  "mimeType": "text/html;profile=mcp-app"}]},
            }
            while True:
                outgoing = await client.post(path + "/poll", headers=desktop)
                assert outgoing.status_code == 200
                if delivery := outgoing.json():
                    message = delivery["message"]
                    reply = {"request": delivery["request"], "response": {
                        "result": results[message["method"]] if message is not None else {},
                    }}
                    assert (await client.post(path + "/complete", json=reply, headers=desktop)).status_code == 204
                    if message is None:
                        return

        def client_factory(**kwargs):
            return AsyncClient(transport=ASGITransport(app=app), **kwargs)

        transport = StreamableHttpTransport(registered.mcp.url, headers=service_headers, httpx_client_factory=client_factory)
        async with asyncio.timeout(10), asyncio.TaskGroup() as group:
            polling = group.create_task(serve_desktop())
            async with Client(transport) as mcp_client:
                assert [tool.name for tool in await mcp_client.list_tools()] == ["inventory"]
                assert (await mcp_client.call_tool("inventory", {})).content[0].text == "synthetic"
                assert (await mcp_client.read_resource("ui://inventory/table"))[0].text == "<p>Synthetic stock</p>"
            polling.cancel()

        assert (await client.post(path + "/poll?offline=true", headers=desktop)).status_code == 200
        assert (await client.post(path + "/mcp", json=call, headers=session)).status_code == 503
        service_url = f"/api/services/{service_id}"
        impact = await client.get(service_url + "/deletion-impact", headers=admin)
        assert impact.status_code == 200
        removed = await client.delete(service_url, headers=admin, params={
            "cascade": "true", "expected_version": impact.json()["version"],
        })
        assert removed.status_code == 204, removed.text
        assert (await client.post(path + "/poll", headers=desktop)).status_code == 403
