"""Persistent browser-session integration tests."""

import pytest
from httpx import AsyncClient

from core import settings
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from core.user import refresh_session_service as sessions
from core.user.models import User, UserRefreshSession


async def _register_and_login(client: AsyncClient, email: str) -> tuple[str, str]:
    registration = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "persistent-password"},
    )
    assert registration.status_code == 201

    login = await client.post(
        "/api/auth/login-json",
        json={"email": email, "password": "persistent-password"},
    )
    assert login.status_code == 200
    refresh_token = client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert refresh_token
    return login.json()["access_token"], refresh_token


@pytest.mark.asyncio
async def test_login_refresh_and_logout_browser_session(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    access_token, initial_refresh_token = await _register_and_login(
        client,
        "persistent-session@example.com",
    )

    set_cookie = client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert set_cookie == initial_refresh_token

    refreshed = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    rotated_refresh_token = client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert rotated_refresh_token
    assert rotated_refresh_token != initial_refresh_token

    current_user = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert current_user.status_code == 200

    logged_out = await client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME) is None

    old_access = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"},
    )
    assert old_access.status_code == 401
    rotated_access = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert rotated_access.status_code == 401

    refresh_after_logout = await client.post("/api/auth/refresh")
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_reuses_same_rotation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    access_token, initial_refresh_token = await _register_and_login(
        client,
        "concurrent-refresh@example.com",
    )

    first = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert first.status_code == 200
    rotated_refresh_token = client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    assert rotated_refresh_token

    concurrent = await client.post(
        "/api/auth/refresh",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Cookie": (
                f"{settings.AUTH_REFRESH_COOKIE_NAME}={initial_refresh_token}"
            ),
        },
    )
    assert concurrent.status_code == 200
    assert client.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME) == rotated_refresh_token


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "expired_revoked", "inactive", "replayed_inactive", "unknown"])
async def test_invalid_refresh_cannot_resurrect_a_browser_session(db, state):
    user = User(email=f"{state}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.commit()
    token = await sessions.create_refresh_session(user.id, user_agent="browser" * 100)
    row = await db.scalar(select(UserRefreshSession).where(UserRefreshSession.user_id == user.id))
    family = row.family_id
    assert len(row.user_agent) == 512
    if state.startswith("expired"):
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if state == "expired_revoked":
            row.revoked_at = datetime.now(timezone.utc)
    elif state == "replayed_inactive":
        await sessions.rotate_refresh_token(token)
        user.is_active = False
    elif state == "inactive":
        user.is_active = False
    await db.commit()
    with pytest.raises(sessions.InvalidRefreshTokenError):
        await sessions.rotate_refresh_token("unknown" if state == "unknown" else token)
    if state != "unknown":
        assert not await sessions.is_family_active(user.id, family)
    else:
        assert await sessions.is_family_active(user.id, family)
    with pytest.raises(sessions.InvalidRefreshTokenError):
        await sessions.family_for_token("unknown")
    assert not await sessions.revoke_refresh_token("unknown")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [True, False])
async def test_inactive_or_missing_account_cannot_create_refresh_credentials(db, missing):
    user = User(email="inactive-create@example.test", hashed_password="unused", is_active=False)
    db.add(user)
    await db.commit()
    with pytest.raises(sessions.InvalidRefreshTokenError):
        await sessions.create_refresh_session(2147483647 if missing else user.id)
    assert list(await db.scalars(select(UserRefreshSession))) == []
