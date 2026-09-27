"""Only web authentication can manage API credentials or renew frontend JWTs."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt


@pytest_asyncio.fixture
async def token_owner(client: AsyncClient):
    credentials = {"email": "token-owner@example.com", "password": "token-owner-password"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200
    access = login.json()["access_token"]
    claims = jwt.get_unverified_claims(access)
    # The first account is an administrator: even its API token must be denied.
    assert claims["role_code"] == "admin"
    web_headers = {"Authorization": f"Bearer {access}"}
    created = await client.post("/api/auth/me/tokens", headers=web_headers, json={"label": "Integration"})
    assert created.status_code == 201
    return web_headers, created.json(), claims["role_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "create", "update", "delete", "keep_alive", "switch_role"])
async def test_api_token_cannot_manage_credentials_or_become_web_session(client, token_owner, operation):
    web_headers, token, role_id = token_owner
    api_headers = {"Authorization": f"Bearer {token['token']}"}
    # A real API credential remains usable for ordinary authenticated access.
    assert (await client.get("/api/auth/me", headers=api_headers)).status_code == 200
    operations = {
        "list": ("GET", "/api/auth/me/tokens", None),
        "create": ("POST", "/api/auth/me/tokens", {"label": "Escalated"}),
        "update": ("PUT", f"/api/auth/me/tokens/{token['id']}", {"label": "Changed", "enabled": False}),
        "delete": ("DELETE", f"/api/auth/me/tokens/{token['id']}", None),
        "keep_alive": ("POST", "/api/auth/keep-alive", None),
        "switch_role": ("POST", "/api/authorize/switch-role", {"role_id": role_id}),
    }
    method, path, payload = operations[operation]
    # Login cookies are intentionally still present; an API Bearer must not be
    # upgraded by a cookie or by caller-supplied authentication metadata.
    response = await client.request(
        method, path, headers={**api_headers, "Origin": "http://localhost"},
        params={"web_session_user_id": 1}, json=payload,
    )
    assert response.status_code == 403
    assert "access_token" not in response.json()
    unchanged = await client.get("/api/auth/me/tokens", headers=web_headers)
    assert unchanged.status_code == 200
    assert [(row["id"], row["label"], row["enabled"]) for row in unchanged.json()] == [
        (token["id"], "Integration", True)
    ]
    # Request authentication must not leak from an API call into a web call.
    assert (await client.get("/api/auth/me", headers=api_headers)).status_code == 200


@pytest.mark.asyncio
async def test_web_token_management_survives_renewal_and_rejects_other_owners(client, token_owner):
    web_headers, token, role_id = token_owner
    for path, payload in [
        ("/api/auth/keep-alive", None),
        ("/api/authorize/switch-role", {"role_id": role_id}),
    ]:
        renewed = await client.post(path, headers=web_headers, json=payload)
        assert renewed.status_code == 200
        web_headers = {"Authorization": f"Bearer {renewed.json()['access_token']}"}
        assert (await client.get("/api/auth/me/tokens", headers=web_headers)).status_code == 200

    updated = await client.put(
        f"/api/auth/me/tokens/{token['id']}", headers=web_headers,
        json={"label": "Renamed", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Renamed"
    assert updated.json()["enabled"] is False
    assert (await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token['token']}"},
    )).status_code == 401

    other_credentials = {"email": "other-token-owner@example.com", "password": "other-owner-password"}
    assert (await client.post("/api/auth/users", headers=web_headers, json=other_credentials)).status_code == 201
    from main import app

    # Each owner has a separate browser cookie jar. Logging another user into
    # the same browser intentionally revokes that browser's previous session.
    async with AsyncClient(transport=ASGITransport(app=app), base_url=client.base_url) as other_browser:
        other_login = await other_browser.post("/api/auth/login-json", json=other_credentials)
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert (await client.get("/api/auth/me/tokens", headers=other_headers)).json() == []
    for method, payload in [("PUT", {"enabled": True}), ("DELETE", None)]:
        denied = await client.request(
            method, f"/api/auth/me/tokens/{token['id']}", headers=other_headers, json=payload,
        )
        assert denied.status_code == 404
    assert (await client.delete(f"/api/auth/me/tokens/{token['id']}", headers=web_headers)).status_code == 204
    assert (await client.get("/api/auth/me/tokens", headers=web_headers)).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Bearer invalid-credential"])
async def test_token_management_requires_authentication(client, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    for method, path, payload in [
        ("GET", "/api/auth/me/tokens", None),
        ("POST", "/api/auth/me/tokens", {}),
        ("PUT", "/api/auth/me/tokens/1", {"enabled": False}),
        ("DELETE", "/api/auth/me/tokens/1", None),
        ("POST", "/api/auth/keep-alive", None),
        ("POST", "/api/authorize/switch-role", {"role_id": 1}),
    ]:
        assert (await client.request(method, path, headers=headers, json=payload)).status_code == 401


@pytest.mark.asyncio
async def test_agent_mcp_credentials_also_require_web_authentication(client, token_owner):
    from app.agent.models import Agent, Title
    from core.database import get_db_session

    web_headers, api_token, _ = token_owner
    async with get_db_session() as db:
        title = Title(label="Credential test", gender="M")
        db.add(title)
        await db.flush()
        agent = Agent(
            code="credential-guard", first_name="Credential", last_name="Guard",
            user_id=api_token["user_id"], title_id=title.id,
        )
        db.add(agent)
        await db.commit()
        agent_id = agent.id
    path = f"/api/agents/{agent_id}/mcp-tokens"
    created = await client.post(path, headers=web_headers, json={"label": "MCP integration"})
    assert created.status_code == 201
    mcp_token = created.json()
    item_path = f"{path}/{mcp_token['id']}"
    for credential, expected in [(api_token["token"], 403), (mcp_token["token"], 401)]:
        headers = {"Authorization": f"Bearer {credential}"}
        for method, url, payload in [
            ("GET", path, None),
            ("POST", path, {"label": "Escalated MCP"}),
            ("PUT", item_path, {"enabled": False}),
            ("DELETE", item_path, None),
        ]:
            assert (await client.request(method, url, headers=headers, json=payload)).status_code == expected
    listed = await client.get(path, headers=web_headers)
    assert listed.status_code == 200
    assert [(row["id"], row["enabled"]) for row in listed.json()] == [(mcp_token["id"], True)]
    updated = await client.put(item_path, headers=web_headers, json={"label": "Renamed MCP", "enabled": False})
    assert updated.status_code == 200
    assert updated.json()["label"] == "Renamed MCP"
    assert updated.json()["enabled"] is False
    assert (await client.delete(item_path, headers=web_headers)).status_code == 204
    assert (await client.get(path, headers=web_headers)).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,payload", [
    ("PUT", "/api/auth/me", {"password": "unauthorized-password"}),
    ("PUT", "/api/auth/me", {"display_name": "Changed", "language": "zh", "document_open_mode": "dialog"}),
    ("PUT", "/api/auth/users/{user_id}", {"password": "unauthorized-password", "language": "zh"}),
    ("POST", "/api/auth/users", {"email": "unauthorized-account@example.com", "password": "unauthorized-password"}),
    ("DELETE", "/api/auth/users/{user_id}", None),
    ("DELETE", "/api/auth/me", None),
    ("POST", "/api/auth/me/avatar", None),
    ("DELETE", "/api/auth/me/avatar", None),
    ("GET", "/api/auth/me/help-dismissals", None),
    ("PUT", "/api/auth/me/help-dismissals/agents", None),
    ("GET", "/api/auth/mfa/status", None),
    ("POST", "/api/auth/mfa/setup", None),
    ("POST", "/api/auth/mfa/confirm", {"code": "123456"}),
    ("POST", "/api/auth/mfa/disable", {"password": "token-owner-password", "code": "123456"}),
    ("POST", "/api/auth/mfa/recovery-codes", {"code": "123456"}),
    ("PUT", "/api/authorize/assignments/{assignment_id}/default", None),
    ("GET", "/api/llm/me/preferences", None),
    ("PUT", "/api/llm/me/preferences", {"voice_mode": "tts", "voice_code": None}),
    ("GET", "/api/llm/me/options", None),
    ("GET", "/api/llm/users/{user_id}/preferences", None),
    ("PUT", "/api/llm/users/{user_id}/preferences", {"voice_mode": "tts", "voice_code": None}),
])
async def test_api_token_cannot_manage_accounts_or_preferences(client, token_owner, method, path, payload):
    web_headers, token, _ = token_owner
    claims = jwt.get_unverified_claims(web_headers["Authorization"].removeprefix("Bearer "))
    path = path.format(user_id=token["user_id"], assignment_id=claims["assignment_id"])
    api_headers = {"Authorization": f"Bearer {token['token']}"}
    before = await client.get("/api/auth/me", headers=web_headers)
    response = await client.request(
        method, path, headers=api_headers, json=payload,
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\nsynthetic-avatar", "image/png")}
        if path.endswith("/avatar") and method == "POST" else None,
    )
    assert response.status_code == 403
    # A denied request leaves both the web session and the API identity usable.
    after = await client.get("/api/auth/me", headers=api_headers)
    assert after.status_code == 200
    assert after.json() == before.json()
    assert (await client.get("/api/auth/me/tokens", headers=web_headers)).status_code == 200
    assert (await client.get("/api/auth/me/help-dismissals", headers=web_headers)).json() == []
    assert (await client.get("/api/auth/mfa/status", headers=web_headers)).json() == {
        "enabled": False, "setup_pending": False, "recovery_codes_remaining": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["self", "admin"])
async def test_web_password_change_still_works_and_revokes_old_web_session(client, token_owner, route):
    web_headers, token, _ = token_owner
    claims = jwt.get_unverified_claims(web_headers["Authorization"].removeprefix("Bearer "))
    default_role = await client.put(
        f"/api/authorize/assignments/{claims['assignment_id']}/default", headers=web_headers,
    )
    assert default_role.status_code == 200
    assert default_role.json()["is_default"] is True
    changed = await client.put(
        "/api/auth/me" if route == "self" else f"/api/auth/users/{token['user_id']}",
        headers=web_headers, json={"password": "new-web-password"},
    )
    assert changed.status_code == 200
    assert (await client.get("/api/auth/me", headers=web_headers)).status_code == 401
    for password, expected in [("token-owner-password", 401), ("new-web-password", 200)]:
        result = await client.post(
            "/api/auth/login-json", json={"email": "token-owner@example.com", "password": password},
        )
        assert result.status_code == expected
