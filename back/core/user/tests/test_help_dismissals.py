"""Help is acknowledged permanently per account through the authenticated API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_help_dismissals_persist_independently_across_logins(client: AsyncClient) -> None:
    endpoint = "/api/auth/me/help-dismissals"
    assert (await client.get(endpoint)).status_code == 401
    assert (await client.put(f"{endpoint}/agents")).status_code == 401

    credentials = {"email": "help-admin@example.com", "password": "help-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201

    async def login(data: dict[str, str]) -> dict[str, str]:
        response = await client.post("/api/auth/login-json", json=data)
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    headers = await login(credentials)
    assert (await client.get(endpoint, headers=headers)).json() == []
    for key in ["agents", "documents", "agents"]:
        assert (await client.put(f"{endpoint}/{key}", headers=headers)).status_code == 204
    assert (await client.put(f"{endpoint}/invalid key", headers=headers)).status_code == 422
    assert (await client.put(f"{endpoint}/{'a' * 101}", headers=headers)).status_code == 422

    other = {"email": "help-member@example.com", "password": "help-password-456"}
    assert (await client.post("/api/auth/users", json=other, headers=headers)).status_code == 201
    other_headers = await login(other)
    assert (await client.get(endpoint, headers=other_headers)).json() == []
    # An ordinary member can only acknowledge their own help, even with an extra query argument.
    assert (await client.put(f"{endpoint}/tasks?user_id=1", headers=other_headers)).status_code == 204
    assert (await client.get(endpoint, headers=other_headers)).json() == ["tasks"]

    fresh_headers = await login(credentials)
    restored = await client.get(endpoint, headers=fresh_headers)
    assert restored.status_code == 200
    assert restored.headers["cache-control"] == "no-store"
    assert restored.json() == ["agents", "documents"]
