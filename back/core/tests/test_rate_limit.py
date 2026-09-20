"""Exercise the enabled limiter through the application's real nested routers."""

import time

import pytest
from httpx import ASGITransport, AsyncClient

from core.rate_limit import limiter
from core.params import runtime_settings
from main import app


@pytest.fixture
def enabled_limiter(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_default_limit_covers_modular_routes_and_recovers(client, enabled_limiter, monkeypatch):
    monkeypatch.setattr(runtime_settings, "HTTP_RATE_LIMIT_PER_MINUTE", 3)
    # An unauthenticated protected route must still consume its default quota.
    for _ in range(3):
        assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 429
    # An untrusted header cannot change the ASGI peer identity.
    assert (await client.get("/api/auth/me", headers={"X-Forwarded-For": "198.51.100.9"})).status_code == 429
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.10", 1234)),
        base_url=client.base_url,
    ) as other:
        assert (await other.get("/api/auth/me")).status_code == 401
    after_window = time.time() + 61
    monkeypatch.setattr(time, "time", lambda: after_window)
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path,form", [("/api/auth/login-json", False), ("/api/auth/login", True)])
async def test_login_has_its_stricter_limit_before_password_verification(client, enabled_limiter, path, form):
    payload = {"email": "unknown@example.com", "password": "invalid-password"}
    kwargs = {"data": {"username": payload["email"], "password": payload["password"]}} if form else {"json": payload}
    for _ in range(10):
        assert (await client.post(path, **kwargs)).status_code == 401
    assert (await client.post(path, **kwargs)).status_code == 429


@pytest.mark.asyncio
async def test_invalid_login_fields_cannot_bypass_the_login_quota(client, enabled_limiter):
    for _ in range(10):
        assert (await client.post("/api/auth/login-json", json={"email": "invalid"})).status_code == 422
    assert (await client.post("/api/auth/login-json", json={"email": "invalid"})).status_code == 429
