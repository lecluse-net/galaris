"""The public user lifecycle must succeed on the actual HTTP routes."""
from uuid import uuid4
import pytest


@pytest.mark.asyncio
async def test_user_lifecycle_flow(client):
    email = f"lifecycle-{uuid4()}@example.com"
    registered = await client.post("/api/auth/register", json={"email": email, "password": "strongpassword123"})
    assert registered.status_code == 201, registered.text
    denied = await client.post("/api/auth/login-json", json={"email": email, "password": "incorrect"})
    assert denied.status_code == 401
    login = await client.post("/api/auth/login-json", json={"email": email, "password": "strongpassword123"})
    assert login.status_code == 200, login.text
    current = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert current.status_code == 200 and current.json()["email"] == email
    assert (await client.get("/api/auth/me")).status_code == 401
