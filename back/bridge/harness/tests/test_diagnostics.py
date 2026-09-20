import importlib
import socket
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from bridge.harness.diagnostics import diagnose, _safe_url
from bridge.harness.manager import HarnessManager, HarnessManagerError
from bridge.harness.router import router, manager_diagnostics
from core.authorize import GuardProvider, Privileges
from core.settings import settings
from core.params import runtime_settings
from bridge.harness.distribution import source_version


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(runtime_settings, "HARNESS_MANAGER_URL", "http://host.docker.internal:8485")
    monkeypatch.setattr(runtime_settings, "HARNESS_MANAGER_SECRET", Fernet.generate_key().decode())
    monkeypatch.setattr(runtime_settings, "HARNESS_MANAGER_GALARIS_API_URL", "")
    monkeypatch.setattr(settings, "APP_HOST", "https://galaris.example.test")
    instance = HarnessManager()
    instance._request = AsyncMock(return_value=httpx.Response(200, json={
        "service": "bridge.harness", "capabilities": ["compose-lifecycle", "file-share"],
    }))
    return instance


@pytest.mark.asyncio
async def test_healthy_manager_does_not_claim_runtime_mcp_verified(client):
    report = await diagnose(client)
    assert report.state == "ok"
    assert report.secret_configured is True
    assert report.runtime_api_check == "not_checked"
    assert report.galaris_api_url == "https://galaris.example.test/api"
    client._request.assert_awaited_once_with("GET", "/", timeout=8.0)


@pytest.mark.asyncio
@pytest.mark.parametrize('installed,status', [
    ('1.0.0', 'update_available'), (source_version(), 'current'), ('999.0.0', 'newer'),
    (None, 'unknown'), ('secret-or-invalid-version', 'unknown'),
])
async def test_version_comparison_preserves_connection_health(client, installed, status):
    client._request.return_value = httpx.Response(200, json={
        'service': 'bridge.harness', 'capabilities': ['compose-lifecycle', 'file-share'], 'version': installed,
    })
    report = await diagnose(client)
    assert report.state == 'ok'
    assert report.expected_version == source_version()
    assert report.version_status == status
    assert report.manager_version == (installed if status != 'unknown' else None)


@pytest.mark.asyncio
async def test_missing_secret_performs_no_request(client, monkeypatch):
    monkeypatch.setattr(runtime_settings, "HARNESS_MANAGER_SECRET", "")
    assert (await diagnose(client)).state == "missing_secret"
    client._request.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_secret_is_not_reported_as_network_failure(monkeypatch):
    monkeypatch.setitem(runtime_settings.__dict__, "HARNESS_MANAGER_SECRET", "not-a-fernet-key")
    report = await diagnose(HarnessManager())
    assert report.state == "invalid_secret"
    assert "not-a-fernet-key" not in report.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(401, "unauthorized"), (403, "forbidden"), (404, "not_found"), (502, "http_error")])
async def test_http_failures_have_distinct_guidance(client, status, expected):
    request = httpx.Request("GET", runtime_settings.HARNESS_MANAGER_URL)
    cause = httpx.HTTPStatusError("remote body must not leak", request=request, response=httpx.Response(status, request=request))
    error = HarnessManagerError("redacted")
    error.__cause__ = cause
    client._request.side_effect = error
    report = await diagnose(client)
    assert report.state == expected
    assert report.http_status == status
    assert "remote body" not in report.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause,expected", [
    (socket.gaierror(-2, "Name not known"), "dns_error"),
    (ssl.SSLError("certificate verify failed"), "tls_error"),
    (httpx.ConnectTimeout("timeout"), "timeout"),
    (ConnectionRefusedError(), "connection_error"),
])
async def test_transport_failures_preserve_the_cause(client, cause, expected):
    transport = httpx.ConnectError("connection error")
    transport.__cause__ = cause
    error = HarnessManagerError("redacted")
    error.__cause__ = transport
    client._request.side_effect = error
    assert (await diagnose(client)).state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, text="<html>login</html>"), "invalid_response"),
    (httpx.Response(200, json={"service": "other"}), "incompatible_manager"),
])
async def test_wrong_service_is_not_healthy(client, response, expected):
    client._request.return_value = response
    assert (await diagnose(client)).state == expected


@pytest.mark.asyncio
async def test_report_contains_no_secret_token_or_url_credentials(client, monkeypatch):
    secret = runtime_settings.HARNESS_MANAGER_SECRET
    monkeypatch.setitem(runtime_settings.__dict__, "HARNESS_MANAGER_URL", f"https://user:{secret}@manager.example.test/?token=private-token#private-fragment")
    monkeypatch.setitem(runtime_settings.__dict__, "HARNESS_MANAGER_GALARIS_API_URL", "https://user:private-password@galaris.example.test/api?token=private-token")
    client._request.return_value = httpx.Response(200, json={
        "service": "bridge.harness", "capabilities": ["compose-lifecycle", "file-share"],
        "secret": secret, "token": "remote-private-token",
    })
    report = await diagnose(client)
    serialized = report.model_dump_json()
    for sensitive in [secret, "private-token", "private-password", "private-fragment", "X-Harness-Token"]:
        assert sensitive not in serialized
    assert report.secret_configured is True
    assert report.manager_url == "https://manager.example.test/".rstrip("/")


@pytest.mark.parametrize("raw", ["", "file:///etc/passwd", "http://", "http://host:bad"])
def test_invalid_urls_are_not_exposed(raw):
    assert _safe_url(raw) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_diagnostics_route_requires_configuration_privileges(monkeypatch, allowed):
    guards_module = importlib.import_module("core.authorize.guard_provider")
    app = FastAPI()
    app.include_router(router)
    guards = GuardProvider()
    guards.scan_app(app)
    monkeypatch.setattr(guards_module, "guard_provider", guards)
    monkeypatch.setattr(guards_module, "get_db", lambda: object())
    check = AsyncMock(return_value=allowed)
    monkeypatch.setattr(guards_module, "check_privilege", check)
    monkeypatch.setattr(guards_module, "tr", AsyncMock(return_value="Forbidden"))
    request = Request({"type": "http", "method": "GET", "path": "/harness-manager/diagnostics", "headers": [],
        "route": SimpleNamespace(name="manager_diagnostics", endpoint=manager_diagnostics)})
    user = SimpleNamespace(id=1, is_active=True)
    if allowed:
        await guards_module.global_authorization_guard(request, current_user=user)
    else:
        with pytest.raises(HTTPException) as exc:
            await guards_module.global_authorization_guard(request, current_user=user)
        assert exc.value.status_code == 403
    assert check.await_args.args[1] == [Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT]
