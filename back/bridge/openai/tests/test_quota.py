"""Synthetic subscription quota responses and HTTP access guarantees."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.llm.provider_facade import ProviderAuthenticationError
from bridge.openai import codex_oauth, codex_quota


@pytest.fixture
def upstream(monkeypatch):
    responses = []
    requests = []
    token = AsyncMock(return_value="synthetic-access-token")
    monkeypatch.setattr(codex_oauth, "get_access_token", token)
    client_type = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(codex_quota.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    return responses, requests, token


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", [False, True])
async def test_account_quota_preserves_windows_and_refreshes_only_after_401(upstream, refresh):
    responses, requests, token = upstream
    if refresh:
        responses.append(httpx.Response(401))
    responses.append(httpx.Response(200, json={"rate_limit": {
        "primary_window": {"used_percent": 37, "limit_window_seconds": 18000, "reset_at": 2000000000},
        "secondary_window": {"used_percent": 0, "limit_window_seconds": 604800, "reset_at": 2000604800},
    }, "email": "private@example.test"}))
    quota = await codex_quota.get_quota(17)
    assert [(w.name, w.used_percent, w.window_seconds) for w in quota.windows] == [
        ("primary", 37, 18000), ("secondary", 0, 604800),
    ]
    assert quota.windows[0].resets_at.timestamp() == 2000000000
    assert "private@example.test" not in repr(quota)
    assert len(requests) == (2 if refresh else 1)
    assert all(str(r.url) == "https://chatgpt.com/backend-api/wham/usage" for r in requests)
    assert all(r.headers["Authorization"] == "Bearer synthetic-access-token" for r in requests)
    assert token.call_args.kwargs.get("force_refresh", False) is refresh


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [None, {}, {"used_percent": True}, {"used_percent": -1}, {"used_percent": 101}])
async def test_missing_or_invalid_limits_are_not_presented_as_zero(upstream, window):
    upstream[0].append(httpx.Response(200, json={"rate_limit": {"primary_window": window}}))
    assert (await codex_quota.get_quota(17)).windows == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_upstream_errors_are_safe_and_do_not_retry_limits(upstream, status):
    responses, requests, token = upstream
    responses.extend([httpx.Response(status, text="secret upstream details")] * 2)
    with pytest.raises(ProviderAuthenticationError) as error:
        await codex_quota.get_quota(17)
    assert error.value.status_code == (status if status != 500 else 502)
    assert error.value.relogin_required is (status == 401)
    assert "secret" not in str(error.value)
    assert len(requests) == (2 if status == 401 else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="not JSON"), httpx.ConnectError("secret")])
async def test_invalid_json_and_network_failure_are_safe(upstream, response):
    upstream[0].append(response)
    with pytest.raises(ProviderAuthenticationError, match="temporarily unavailable"):
        await codex_quota.get_quota(17)


@pytest.mark.asyncio
async def test_quota_endpoint_requires_provider_privileges_and_keeps_credentials_private(client, monkeypatch):
    from main import app

    path = "/api/llm-providers/1/quota"
    assert (await client.get(path)).status_code == 401
    admin = {"email": f"quota-admin-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=admin)).status_code == 201
    login = await client.post("/api/auth/login-json", json=admin)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    owner = await client.get("/api/auth/me", headers=headers)
    assert owner.status_code == 200
    credentials = {"email": f"quota-reader-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/users", json=credentials, headers=headers)).status_code == 201
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=client.base_url) as browser:
        login = await browser.post("/api/auth/login-json", json=credentials)
        assert login.status_code == 200
        denied = await browser.get(path, headers={"Authorization": f"Bearer {login.json()['access_token']}"})
        assert denied.status_code == 403

    provider = await client.put("/api/llm-providers/catalog/openai-codex", headers=headers, json={
        "is_active": False, "subscription_acknowledged": True, "user_id": owner.json()["id"],
    })
    assert provider.status_code == 200
    provider_id = provider.json()["id"]
    path = f"/api/llm-providers/{provider_id}/quota"
    # Read the real provider service and bridge; replace only the external HTTP/token boundary.
    monkeypatch.setattr(codex_oauth, "get_access_token", AsyncMock(return_value="synthetic-token"))
    client_type = httpx.AsyncClient
    monkeypatch.setattr(codex_quota.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"rate_limit": {
            "primary_window": {"used_percent": 42, "limit_window_seconds": 18000},
        }})), **kwargs,
    ))
    response = await client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["windows"][0]["used_percent"] == 42
    assert "synthetic-token" not in response.text
    assert (await client.get("/api/llm-providers/999999/quota", headers=headers)).status_code == 404
