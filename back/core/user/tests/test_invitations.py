"""The real user API owns invitations from administrative creation through login."""

from datetime import datetime, timedelta, timezone
from asyncio import gather
from hashlib import sha256
import re
from secrets import token_urlsafe
from smtplib import SMTPServerDisconnected
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from core import settings
from core.database import get_db_session
from core.params import params_service, runtime_settings
from core.params.models import Param
from core.user.models import User
from core.user import invitation_service, platform_mail
from core.util import decrypt_value


@pytest.mark.asyncio
async def test_invitation_lifecycle_and_smtp_configuration(client, monkeypatch):
    credentials = {"email": "invite-admin@example.com", "password": "Granite-sparrow-47"}
    assert (await client.post("/api/auth/register", json={**credentials, "language": "en"})).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    users = "/api/auth/users"
    data = {"email": "invited-person@example.com", "invite": True}
    monkeypatch.setattr(runtime_settings, "PLATFORM_SMTP_HOST", "")
    monkeypatch.setattr(settings, "APP_HOST", "https://accounts.example.test")
    assert (await client.post(users, headers=headers, json=data)).status_code == 503
    smtp_test_url = "/api/auth/platform-smtp/test"
    smtp_test_data = {"recipient": "test-recipient@example.com"}
    assert (await client.post(smtp_test_url, json=smtp_test_data)).status_code == 401
    assert (await client.post(smtp_test_url, headers=headers, json=smtp_test_data)).status_code == 409

    smtp_config = {
        "PLATFORM_SMTP_HOST": "smtp.example.test",
        "PLATFORM_SMTP_FROM": "platform@example.com",
        "PLATFORM_SMTP_USERNAME": "platform",
        "PLATFORM_SMTP_PASSWORD": "synthetic-mail-credential",
    }
    monkeypatch.setattr(params_service, "_cache_loaded", False)
    monkeypatch.setattr(params_service, "_params_cache", {})
    for name, value in smtp_config.items():
        monkeypatch.setattr(runtime_settings, name, getattr(runtime_settings, name))
        configured = await client.put(f"/api/params/{name}", headers=headers, json={"value": value})
        assert configured.status_code == 200, configured.text
    secret = smtp_config["PLATFORM_SMTP_PASSWORD"]
    assert configured.json()["value"] is None
    assert secret not in (await client.get("/api/params", headers=headers)).text
    async with get_db_session() as db:
        stored = await db.scalar(select(Param.value).where(Param.name == "PLATFORM_SMTP_PASSWORD"))
        assert stored != secret and decrypt_value(stored) == secret

    smtp = Mock()
    connect = Mock(return_value=smtp)
    monkeypatch.setattr(platform_mail, "SMTP", connect)
    invalid = await client.post(smtp_test_url, headers=headers, json={"recipient": "first@example.com, second@example.com"})
    assert invalid.status_code == 422
    connect.assert_not_called()
    result = await client.post(smtp_test_url, headers=headers, json=smtp_test_data)
    assert result.status_code == 204, result.text
    smtp.send_message.assert_called_once()
    test_message = smtp.send_message.call_args.args[0]
    assert test_message["To"] == smtp_test_data["recipient"]
    assert test_message["Subject"] == "Galaris SMTP test"
    assert "/user/invitation" not in test_message.get_content()
    assert test_message["From"] == smtp_config["PLATFORM_SMTP_FROM"]

    smtp.send_message.side_effect = SMTPServerDisconnected("synthetic transport failure")
    failure = await client.post(smtp_test_url, headers=headers, json=smtp_test_data)
    assert failure.status_code == 502
    assert "synthetic transport failure" not in failure.text
    created = await client.post(users, headers=headers, json=data)
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["invitation_pending"] and not account["is_active"] and not account["invitation_sent"]
    user_url = f"{users}/{account['id']}"
    resend_url = f"{user_url}/invitation"
    assert (await client.post("/api/auth/login-json", json={
        "email": data["email"], "password": "Silver maples above the river",
    })).status_code == 401
    assert (await client.put(user_url, headers=headers, json={"is_active": True})).status_code == 409
    assert (await client.put(user_url, headers=headers, json={"password": "Granite-sparrow-48"})).status_code == 409
    assert (await client.post(resend_url, headers=headers)).status_code == 502
    smtp.send_message.side_effect = None
    smtp.reset_mock()

    async def resend() -> str:
        response = await client.post(resend_url, headers=headers)
        assert response.status_code == 204, response.text
        message = smtp.send_message.call_args.args[0]
        assert message["To"] == current_email
        assert message["From"] == smtp_config["PLATFORM_SMTP_FROM"]
        link = re.search(r"https://accounts\.example\.test/user/invitation#([A-Za-z0-9_-]{43})", message.get_content())
        assert link
        return link[1]

    current_email = data["email"]
    expired = await resend()
    assert [call[0] for call in smtp.method_calls] == ["starttls", "login", "send_message", "close"]
    smtp.login.assert_called_once_with("platform", secret)
    assert connect.call_args.args == ("smtp.example.test", 587)
    async with get_db_session() as db:
        pending = await db.get(User, account["id"])
        assert pending.invitation_digest != expired
        pending.invitation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    async def accept(token: str, password: str = "Silver maples above the river", confirmation: str | None = None):
        return await client.post("/api/auth/invitations/accept", json={
            "token": token, "password": password,
            "password_confirmation": confirmation if confirmation is not None else password,
        })

    assert (await accept(expired)).status_code == 400
    replaced = await resend()
    token = await resend()
    assert token != replaced and (await accept(replaced)).status_code == 400
    current_email = "updated-invite@example.com"
    assert (await client.put(user_url, headers=headers, json={"email": current_email})).status_code == 200
    assert (await accept(token)).status_code == 400
    token = await resend()
    assert (await accept(token, "password-123")).status_code == 422
    assert (await accept(token, confirmation="mismatch")).status_code == 422
    assert (await accept(token)).status_code == 204
    assert (await accept(token)).status_code == 400
    assert (await client.post(resend_url, headers=headers)).status_code == 409

    client.cookies.clear()
    member = await client.post("/api/auth/login-json", json={
        "email": current_email, "password": "Silver maples above the river",
    })
    assert member.status_code == 200, member.text
    member_headers = {"Authorization": f"Bearer {member.json()['access_token']}"}
    sends = smtp.send_message.call_count
    assert (await client.post(smtp_test_url, headers=member_headers, json=smtp_test_data)).status_code == 403
    assert smtp.send_message.call_count == sends
    assert (await client.post(resend_url, headers=member_headers)).status_code == 403
    assert (await client.post(users, headers=member_headers, json={**data, "email": "outsider@example.com"})).status_code == 403
    assert (await client.put("/api/params/PLATFORM_SMTP_PASSWORD", headers=member_headers, json={
        "value": "other-synthetic-secret",
    })).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["123456789012", "abcdabcdabcd", "            ", "é" * 37])
async def test_password_policy_rejects_weak_or_oversized_passwords_without_echo(client, password):
    response = await client.post("/api/auth/register", json={"email": "weak-password@example.com", "password": password})
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    if password.strip():
        assert password not in response.text


@pytest.mark.asyncio
async def test_concurrent_invitation_acceptance_can_set_only_one_password(committed_database):
    token = token_urlsafe(32)
    async with get_db_session() as db:
        user = User(
            email="concurrent-invite@example.com", hashed_password="unused", is_active=False,
            invitation_pending=True, invitation_digest=sha256(token.encode("ascii")).hexdigest(),
            invitation_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    async def accept(password: str) -> bool:
        async with get_db_session():
            return await invitation_service.accept_invitation(token, password)

    passwords = ("Cedar branches by the coast", "Copper roofs above the valley")
    accepted = await gather(*(accept(password) for password in passwords))
    assert accepted.count(True) == 1
    async with get_db_session() as db:
        user = await db.get(User, user_id)
        assert user.is_active and not user.invitation_pending and user.invitation_digest is None
        from core.user import verify_password

        assert verify_password(passwords[accepted.index(True)], user.hashed_password)
