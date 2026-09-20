"""Progressive lockout and TOTP MFA integration tests."""

import pytest
from httpx import AsyncClient

from core import settings


async def _bootstrap(client: AsyncClient, email: str) -> str:
    password = "a-strong-password"
    registered = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert logged_in.status_code == 200
    return logged_in.json()["access_token"]


@pytest.mark.asyncio
async def test_progressive_login_lockout_is_persistent(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "a-strong-password"
    await _bootstrap(client, "locked-account@example.com")
    monkeypatch.setattr(type(settings), "AUTH_LOGIN_LOCKOUT_THRESHOLD", 2)
    monkeypatch.setattr(type(settings), "AUTH_LOGIN_LOCKOUT_BASE_SECONDS", 60)

    for _ in range(2):
        rejected = await client.post(
            "/api/auth/login-json",
            json={
                "email": "locked-account@example.com",
                "password": "incorrect-password",
            },
        )
        assert rejected.status_code == 401

    locked = await client.post(
        "/api/auth/login-json",
        json={
            "email": "locked-account@example.com",
            "password": password,
        },
    )
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"
    assert int(locked.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_totp_setup_requires_second_factor_and_consumes_recovery_code(
    client: AsyncClient,
) -> None:
    password = "a-strong-password"
    access_token = await _bootstrap(client, "mfa-user@example.com")
    headers = {"Authorization": f"Bearer {access_token}"}

    setup = await client.post("/api/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert secret not in setup.json()["provisioning_uri"].split("secret=", 1)[0]

    from core.user.mfa_service import _totp
    import time

    code = _totp(secret, int(time.time()) // 30)
    confirmed = await client.post(
        "/api/auth/mfa/confirm",
        headers=headers,
        json={"code": code},
    )
    assert confirmed.status_code == 200
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == 10

    replacement_setup = await client.post("/api/auth/mfa/setup", headers=headers)
    assert replacement_setup.status_code == 409

    missing = await client.post(
        "/api/auth/login-json",
        json={"email": "mfa-user@example.com", "password": password},
    )
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "mfa_required"

    recovered = await client.post(
        "/api/auth/login-json",
        json={
            "email": "mfa-user@example.com",
            "password": password,
            "otp_code": recovery_codes[0],
        },
    )
    assert recovered.status_code == 200

    replayed = await client.post(
        "/api/auth/login-json",
        json={
            "email": "mfa-user@example.com",
            "password": password,
            "otp_code": recovery_codes[0],
        },
    )
    assert replayed.status_code == 401
    assert replayed.json()["detail"]["code"] == "invalid_mfa_code"
