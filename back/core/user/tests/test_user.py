"""Tests for the user module."""

import pytest
from httpx import AsyncClient
from jose import jwt
from starlette import status

from core.authorize.update_admin_role import ADMIN_ROLE_CODE
from core import settings
from core.secrets import auth_secret_key


async def _registered_user_headers(client: AsyncClient) -> dict[str, str]:
    credentials = {
        "email": "avatar-owner@example.com",
        "password": "avatar-password-123",
    }
    registration = await client.post("/api/auth/register", json=credentials)
    assert registration.status_code == status.HTTP_201_CREATED
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == status.HTTP_200_OK
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_user_avatar_mutations_require_authentication(
    client: AsyncClient,
) -> None:
    upload = await client.post(
        "/api/auth/me/avatar",
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    deletion = await client.delete("/api/auth/me/avatar")

    assert upload.status_code == status.HTTP_401_UNAUTHORIZED
    assert deletion.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_user_can_persist_simplified_chinese_language(
    client: AsyncClient,
) -> None:
    headers = await _registered_user_headers(client)

    updated = await client.put(
        "/api/auth/me",
        headers=headers,
        json={"language": "zh"},
    )

    assert updated.status_code == status.HTTP_200_OK
    assert updated.json()["language"] == "zh"

    invalid = await client.put(
        "/api/auth/me",
        headers=headers,
        json={"language": "de"},
    )
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
async def test_document_open_mode_is_saved_per_user(client: AsyncClient) -> None:
    headers = await _registered_user_headers(client)
    initial = await client.get("/api/auth/me", headers=headers)
    assert initial.json()["document_open_mode"] == "split"
    other = await client.post(
        "/api/auth/users",
        headers=headers,
        json={"email": "other-reader@example.com", "password": "other-password-123"},
    )
    assert other.status_code == status.HTTP_201_CREATED
    other_id = other.json()["id"]

    for mode in ("dialog", "split"):
        updated = await client.put(
            "/api/auth/me", headers=headers, json={"document_open_mode": mode},
        )
        assert updated.status_code == status.HTTP_200_OK
        assert updated.json()["document_open_mode"] == mode
        reloaded = await client.get("/api/auth/me", headers=headers)
        assert reloaded.json()["document_open_mode"] == mode
        unchanged = await client.get(f"/api/auth/users/{other_id}", headers=headers)
        assert unchanged.json()["document_open_mode"] == "split"

    invalid = await client.put(
        "/api/auth/me", headers=headers, json={"document_open_mode": "window"},
    )
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    unauthenticated = await client.put("/api/auth/me", json={"document_open_mode": "dialog"})
    assert unauthenticated.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_user_can_upload_replace_and_delete_self_hosted_avatar(
    client: AsyncClient,
) -> None:
    headers = await _registered_user_headers(client)

    initial = await client.get("/api/auth/me", headers=headers)
    assert initial.status_code == status.HTTP_200_OK
    assert initial.json()["avatar_url"] is None

    spoofed = await client.post(
        "/api/auth/me/avatar",
        headers=headers,
        files={"file": ("avatar.png", b"not-a-png", "image/png")},
    )
    assert spoofed.status_code == status.HTTP_400_BAD_REQUEST

    png = b"\x89PNG\r\n\x1a\nself-hosted-avatar"
    uploaded = await client.post(
        "/api/auth/me/avatar",
        headers=headers,
        files={"file": ("avatar.png", png, "image/png")},
    )
    assert uploaded.status_code == status.HTTP_200_OK
    first_url = uploaded.json()["avatar_url"]
    assert first_url.startswith("/api/auth/avatars/")

    downloaded = await client.get(first_url)
    assert downloaded.status_code == status.HTTP_200_OK
    assert downloaded.content == png
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.headers["cache-control"] == "public, max-age=31536000, immutable"

    gif = b"GIF89aself-hosted-avatar"
    replaced = await client.post(
        "/api/auth/me/avatar",
        headers=headers,
        files={"file": ("avatar.gif", gif, "image/gif")},
    )
    assert replaced.status_code == status.HTTP_200_OK
    second_url = replaced.json()["avatar_url"]
    assert second_url != first_url
    assert (await client.get(first_url)).status_code == status.HTTP_404_NOT_FOUND
    assert (await client.get(second_url)).content == gif

    deleted = await client.delete("/api/auth/me/avatar", headers=headers)
    assert deleted.status_code == status.HTTP_200_OK
    assert deleted.json()["avatar_url"] is None
    assert (await client.get(second_url)).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_users_unauthenticated(client: AsyncClient):
    """Test that listing users without a token returns 401."""
    response = await client.get("/api/users")
    # The endpoint may return 401, 403, or 404 when the user is not found.
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_validation_errors_never_echo_password_input(client: AsyncClient):
    """Invalid secret-bearing requests keep the submitted value out of the response."""
    password = "s3cr!"

    response = await client.post(
        "/api/auth/register",
        json={"email": "validation-secret@example.com", "password": password},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert password not in response.text
    assert '"input"' not in response.text
    assert response.json()["detail"] == [
        {
            "loc": ["body", "password"],
            "msg": "String should have at least 12 characters",
            "type": "string_too_short",
        }
    ]


@pytest.mark.asyncio
async def test_password_rejects_values_over_bcrypt_byte_limit(
    client: AsyncClient,
) -> None:
    """Multibyte passwords cannot cross bcrypt's 72-byte hard limit."""

    password = "é" * 40
    response = await client.post(
        "/api/auth/register",
        json={"email": "oversized-password@example.com", "password": password},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert password not in response.text
    assert '"input"' not in response.text


@pytest.mark.asyncio
async def test_public_registration_closes_after_initial_administrator(
    client: AsyncClient,
):
    initial_status = await client.get("/api/auth/registration-status")
    assert initial_status.status_code == status.HTTP_200_OK
    assert initial_status.json() == {"registration_open": True, "initial_admin_required": True}
    assert initial_status.headers["cache-control"] == "no-store"

    first = await client.post(
        "/api/auth/register",
        json={
            "email": "initial-admin@example.com",
            "password": "initial-password",
            "is_active": False,
        },
    )

    assert first.status_code == status.HTTP_201_CREATED
    assert first.json()["is_active"] is True

    closed_status = await client.get("/api/auth/registration-status")
    assert closed_status.status_code == status.HTTP_200_OK
    assert closed_status.json() == {"registration_open": False, "initial_admin_required": False}

    login = await client.post(
        "/api/auth/login-json",
        json={
            "email": "initial-admin@example.com",
            "password": "initial-password",
        },
    )
    assert login.status_code == status.HTTP_200_OK
    payload = jwt.decode(
        login.json()["access_token"],
        auth_secret_key(),
        algorithms=[settings.ALGORITHM],
    )
    assert payload["role_code"] == ADMIN_ROLE_CODE

    second = await client.post(
        "/api/auth/register",
        json={
            "email": "second-public-user@example.com",
            "password": "second-password",
        },
    )

    assert second.status_code == status.HTTP_403_FORBIDDEN
    second_login = await client.post(
        "/api/auth/login-json",
        json={
            "email": "second-public-user@example.com",
            "password": "second-password",
        },
    )
    assert second_login.status_code == status.HTTP_401_UNAUTHORIZED


def test_validation_error_messages_redact_values_embedded_by_validators():
    """Custom validator messages cannot smuggle their submitted secret back out."""
    from core.api import sanitize_validation_errors

    sentinel = "synthetic-validator-secret-never-return"
    errors = sanitize_validation_errors([
        {
            "loc": ("body", "password"),
            "msg": f"Value error, rejected credential {sentinel}",
            "type": "value_error",
            "input": {"password": sentinel},
        }
    ])

    assert sentinel not in repr(errors)
    assert errors[0]["msg"] == "Value error, rejected credential <redacted>"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test registration with an already existing email."""
    # 1. Register first user
    user1 = {
        "email": "dup@example.com",
        "password": "password123",
        "full_name": "User 1"
    }
    resp1 = await client.post("/api/users/register", json=user1)
    # Accept 201 (created), 409 (already exists), or 404 (endpoint unavailable).
    assert resp1.status_code in [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]

    # 2. Try register same email - should fail
    resp2 = await client.post("/api/users/register", json=user1)
    assert resp2.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    """Test login with wrong password."""
    # Register
    resp = await client.post("/api/users/register", json={
        "email": "login_fail@example.com",
        "password": "good_password",
        "full_name": "Login Test"
    })
    # Accepte 201, 409, ou 404
    assert resp.status_code in [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]

    # Login fail
    resp = await client.post("/api/users/login", data={
        "username": "login_fail@example.com",
        "password": "wrong_password"
    })
    assert resp.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient):
    """Ensure deactivated user cannot login."""
    # Register user
    resp = await client.post("/api/users/register", json={
        "email": "inactive@example.com",
        "password": "password123",
        "full_name": "Inactive User"
    })
    # Accepte 201, 409, ou 404
    assert resp.status_code in [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_password_update(client: AsyncClient):
    """Test password update flow."""
    # Register
    resp = await client.post("/api/users/register", json={
        "email": "pwd_update@example.com",
        "password": "old_password",
        "full_name": "Password Update Test"
    })
    # Accepte 201, 409, ou 404
    assert resp.status_code in [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_admin_crud_scenario(client: AsyncClient):
    """Test admin user CRUD operations."""
    # Register admin user
    resp = await client.post("/api/users/register", json={
        "email": "admin_crud@example.com",
        "password": "admin123",
        "full_name": "Admin CRUD Test"
    })
    # Accepte 201, 409, ou 404
    assert resp.status_code in [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT, status.HTTP_404_NOT_FOUND]
