"""Synthetic provider usage snapshots, through the shared catalog and HTTP contract."""

from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from app.llm import provider_quota
from app.llm.provider_facade import ProviderAuthenticationError, ProviderConnection, provider_quota_reader_for


CASES = [
    ("elevenlabs", "https://api.elevenlabs.io/v1", "/v1/user/subscription",
     {"character_count": 12000, "character_limit": 10000, "next_character_count_reset_unix": 2000000000},
     "account", (120, 12000, 10000, -2000, "credits")),
    ("mammouth", "https://api.mammouth.ai/v1", "/key/info",
     {"info": {"spend": 2.5, "max_budget": 10, "budget_reset_at": "2033-05-18T03:33:20+00:00",
               "key_name": "private label", "user_id": "private identity"}, "key": "private-key"},
     "api_key", (25, 2.5, 10, 7.5, "USD")),
    ("openrouter", "https://openrouter.ai/api/v1", "/api/v1/key",
     {"data": {"limit": 10, "limit_remaining": 8, "limit_reset": "monthly", "usage": 90,
               "label": "private label"}},
     "api_key", (None, None, None, 8, "USD")),
    ("deepseek", "https://api.deepseek.com/v1", "/user/balance",
     {"balance_infos": [{"currency": "CNY", "total_balance": "0.00"}]},
     "account", (None, None, None, 0, "CNY")),
    ("sunoapi", "https://api.sunoapi.org/api/v1", "/api/v1/generate/credit",
     {"code": 200, "data": 0}, "account", (None, None, None, 0, "credits")),
]


@pytest.fixture
def upstream(monkeypatch):
    requests = []
    responses = []
    client_type = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(provider_quota.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    return responses, requests


def connection(code, base_url):
    return ProviderConnection(
        id=17, name="Synthetic provider", catalog_code=code, provider_type=code,
        base_url=base_url, api_key="synthetic-private-key",
        configuration={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("code,base_url,path,payload,scope,amounts", CASES)
async def test_credit_snapshots_preserve_units_scope_zero_and_overages(upstream, code, base_url, path, payload, scope, amounts):
    upstream[0].append(httpx.Response(200, json=payload))
    reader = provider_quota_reader_for(connection(code, base_url))
    assert reader is not None
    quota = await reader.get_quota(connection(code, base_url))
    assert quota.scope == scope
    window, = quota.windows
    assert (window.used_percent, window.used, window.limit, window.remaining, window.unit) == amounts
    assert "private" not in repr(quota)
    request, = upstream[1]
    assert request.url.path == path
    assert request.headers["xi-api-key" if code == "elevenlabs" else "Authorization"] == (
        "synthetic-private-key" if code == "elevenlabs" else "Bearer synthetic-private-key"
    )
    if code in {"elevenlabs", "mammouth"}:
        assert window.resets_at.timestamp() == 2000000000


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected", [
    ({"info": {"spend": 0, "max_budget": None}}, (0, None, None)),
    ({"info": {"spend": 1, "max_budget": 0}}, (1, 0, -1)),
    ({"info": {"spend": True, "max_budget": 10}}, None),
    ({"info": {"spend": "NaN", "max_budget": 10}}, None),
    ({"info": {"spend": -1, "max_budget": 10}}, None),
    ({"info": {}}, None),
])
async def test_missing_or_invalid_amounts_do_not_create_a_fictional_gauge(upstream, payload, expected):
    upstream[0].append(httpx.Response(200, json=payload))
    configured = connection("mammouth", CASES[1][1])
    reader = provider_quota_reader_for(configured)
    quota = await reader.get_quota(configured)
    if expected is None:
        assert quota.windows == []
    else:
        window, = quota.windows
        assert (window.used, window.limit, window.remaining) == expected
        assert window.used_percent is None


@pytest.mark.asyncio
@pytest.mark.parametrize("credits,expected", [
    ({"total_credits": 50, "total_usage": 12.5}, 37.5),
    ({"total_credits": 50, "total_usage": 50}, 0),
    ({"total_credits": 50, "total_usage": 60}, -10),
    ({"total_credits": 50}, None),
    ({"total_usage": 12.5}, None),
])
async def test_openrouter_management_key_reads_account_credits(upstream, credits, expected):
    upstream[0].extend([
        httpx.Response(200, json={"data": {"is_management_key": True}}),
        httpx.Response(200, json={"data": credits}),
    ])
    configured = connection("openrouter", CASES[2][1])
    quota = await provider_quota_reader_for(configured).get_quota(configured)
    assert quota.scope == "account"
    if expected is None:
        assert quota.windows == []
    else:
        window, = quota.windows
        assert window.name == "balance"
        assert (window.remaining, window.unit) == (expected, "USD")
        assert (window.used_percent, window.limit, window.used) == (None, None, None)
    assert [request.url.path for request in upstream[1]] == ["/api/v1/key", "/api/v1/credits"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response,status", [
    (httpx.Response(401, text="private-key"), 401),
    (httpx.Response(403, text="private-key"), 403),
    (httpx.Response(429, text="private-key"), 429),
    (httpx.Response(500, text="private-key"), 502),
    (httpx.Response(200, text="private-key"), 502),
    (httpx.ConnectError("private-key"), 502),
])
async def test_unavailable_upstreams_preserve_safe_errors_without_retries(upstream, response, status):
    upstream[0].append(response)
    configured = connection("elevenlabs", CASES[0][1])
    with pytest.raises(ProviderAuthenticationError) as error:
        await provider_quota_reader_for(configured).get_quota(configured)
    assert error.value.status_code == status
    assert "private-key" not in str(error.value)
    assert len(upstream[1]) == 1


@pytest.mark.asyncio
async def test_unconfigured_key_does_not_send_a_request(upstream):
    configured = replace(connection("elevenlabs", CASES[0][1]), api_key=None)
    with pytest.raises(ProviderAuthenticationError):
        await provider_quota_reader_for(configured).get_quota(configured)
    assert upstream[1] == []


@pytest.mark.asyncio
async def test_fireworks_does_not_substitute_spend_quota_for_a_credit_balance(client, upstream):
    configured = connection("fireworks", "https://api.fireworks.ai/inference/v1")
    assert provider_quota_reader_for(configured) is None
    credentials = {"email": f"balance-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    saved = await client.put("/api/llm-providers/catalog/fireworks", headers=headers, json={
        "api_key": "synthetic-private-key", "is_active": False,
    })
    assert saved.status_code == 200
    catalog = await client.get("/api/llm-providers/catalog", headers=headers)
    item = next(item for item in catalog.json()["items"] if item["code"] == "fireworks")
    assert item["supports_quota"] is False
    response = await client.get(f"/api/llm-providers/{saved.json()['id']}/quota", headers=headers)
    assert response.status_code == 400
    assert upstream[1] == []  # No account discovery or spend-quota fallback.


@pytest.mark.asyncio
@pytest.mark.parametrize("code,base_url,path,payload,scope,amounts", CASES)
async def test_catalog_and_endpoint_read_the_encrypted_connection(client, monkeypatch, code, base_url, path, payload, scope, amounts):
    credentials = {"email": f"credits-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    saved = await client.put(f"/api/llm-providers/catalog/{code}", headers=headers, json={
        "api_key": "synthetic-private-key", "is_active": False,
        "configuration": connection(code, base_url).configuration,
    })
    assert saved.status_code == 200, saved.text
    catalog = await client.get("/api/llm-providers/catalog", headers=headers)
    supported = {item["code"] for item in catalog.json()["items"] if item["supports_quota"]}
    assert supported == {"openai-codex", "elevenlabs", "mammouth", "openrouter", "deepseek", "sunoapi"}
    client_type = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(provider_quota.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    response = await client.get(f"/api/llm-providers/{saved.json()['id']}/quota", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == scope
    assert response.json()["windows"][0]["remaining"] == amounts[3]
    assert "private" not in response.text
    assert requests[0].headers["xi-api-key" if code == "elevenlabs" else "Authorization"].endswith("synthetic-private-key")


@pytest.mark.asyncio
@pytest.mark.parametrize("write_route", ["catalog", "provider"])
async def test_separate_management_key_is_encrypted_private_and_confined_to_credit_reads(client, monkeypatch, write_route):
    from app.llm import llm_provider_service
    from app.llm.resource_discovery import provider_connection
    from app.llm.provider_schemas import LLMProviderCreate, LLMProviderUpdate, ProviderCatalogConfigure
    from core.database import get_db_session
    from core.util import get_encryption_service

    credentials = {"email": f"management-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    management_key = "synthetic-management-secret"
    for schema in (
        LLMProviderCreate(name="Synthetic provider", base_url=CASES[2][1], management_api_key=management_key),
        LLMProviderUpdate(management_api_key=management_key),
        ProviderCatalogConfigure(management_api_key=management_key),
    ):
        assert management_key not in repr(schema)
    saved = await client.put("/api/llm-providers/catalog/openrouter", headers=headers, json={
        "api_key": "synthetic-inference-secret", "management_api_key": management_key, "is_active": False,
    })
    assert saved.status_code == 200, saved.text
    provider_id = saved.json()["id"]
    route = f"/api/llm-providers/{provider_id}" if write_route == "provider" else "/api/llm-providers/catalog/openrouter"

    async def check_storage(expected):
        async with get_db_session():
            data = await llm_provider_service.get_provider_with_decrypted_key(provider_id)
            assert data is not None
            provider, primary_key = data
            assert primary_key == "synthetic-inference-secret"
            assert provider.management_api_key != expected or expected is None
            if expected:
                assert get_encryption_service().decrypt(provider.management_api_key) == expected
            else:
                assert provider.management_api_key is None
            detached = provider_connection(provider, primary_key)
            assert detached.management_api_key is None
            assert detached.api_key == "synthetic-inference-secret"

    await check_storage(management_key)
    for path in (f"/api/llm-providers/{provider_id}", "/api/llm-providers", "/api/llm-providers/catalog"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200
        assert management_key not in response.text
        assert '"management_api_key"' not in response.text
    assert saved.json()["management_api_key_configured"] is True

    client_type = httpx.AsyncClient
    requests = []
    credits_status = 200

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/credits"):
            assert request.headers["Authorization"] == f"Bearer {management_key}"
            return httpx.Response(credits_status, json={"data": {"total_credits": 50, "total_usage": 12.5}})
        assert request.url.path.endswith("/key")
        assert request.headers["Authorization"] == "Bearer synthetic-inference-secret"
        return httpx.Response(200, json={"data": {"limit": 10, "limit_remaining": 4}})

    monkeypatch.setattr(provider_quota.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    quota_path = f"/api/llm-providers/{provider_id}/quota"
    quota = await client.get(quota_path, headers=headers)
    assert quota.status_code == 200, quota.text
    assert quota.json()["scope"] == "account"
    assert quota.json()["windows"][0]["remaining"] == 37.5
    assert len(requests) == 1
    assert management_key not in quota.text
    assert "management" not in repr(replace(connection("openrouter", CASES[2][1]), management_api_key=management_key))

    unchanged = await client.put(route, headers=headers, json={"is_active": False})
    assert unchanged.status_code == 200
    await check_storage(management_key)
    management_key = "synthetic-replacement-secret"
    changed = await client.put(route, headers=headers, json={"management_api_key": management_key, "is_active": False})
    assert changed.status_code == 200
    await check_storage(management_key)
    credits_status = 403
    unavailable = await client.get(quota_path, headers=headers)
    assert unavailable.status_code == 403
    assert management_key not in unavailable.text
    assert requests[-1].url.path.endswith("/credits")
    await check_storage(management_key)

    removed = await client.put(route, headers=headers, json={"management_api_key": None, "is_active": False})
    assert removed.status_code == 200
    assert removed.json()["management_api_key_configured"] is False
    await check_storage(None)
    fallback = await client.get(quota_path, headers=headers)
    assert fallback.status_code == 200
    assert fallback.json()["scope"] == "api_key"
    assert fallback.json()["windows"][0]["remaining"] == 4


@pytest.mark.asyncio
async def test_management_credentials_require_authorization_and_a_supported_profile(client):
    path = "/api/llm-providers/catalog/openrouter"
    payload = {"management_api_key": "synthetic-management-secret", "is_active": False}
    assert (await client.put(path, json=payload)).status_code == 401
    admin = {"email": f"key-admin-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/register", json=admin)).status_code == 201
    login = await client.post("/api/auth/login-json", json=admin)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    reader = {"email": f"key-reader-{uuid4()}@example.com", "password": "synthetic-password-123"}
    assert (await client.post("/api/auth/users", json=reader, headers=headers)).status_code == 201
    # Model a separate browser login so the reader does not revoke the admin session.
    client.cookies.clear()
    login = await client.post("/api/auth/login-json", json=reader)
    denied_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.put(path, json=payload, headers=denied_headers)).status_code == 403
    unsupported = await client.put("/api/llm-providers/catalog/elevenlabs", headers=headers, json=payload)
    assert unsupported.status_code == 422, unsupported.text
    assert "synthetic-management-secret" not in unsupported.text
