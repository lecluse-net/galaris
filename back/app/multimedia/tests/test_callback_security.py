"""The callback acknowledges a per-run capability without trusting vendor state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.multimedia import router


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "wrong-token", "wrong-engine", "missing"])
async def test_callback_requires_the_matching_multimedia_run_token(client, monkeypatch, case):
    run_id = uuid4()
    run = SimpleNamespace(engine_code="multimedia", callback_token="per-run-secret", status="running")
    if case == "wrong-engine":
        run.engine_code = "n8n"
    lookup = AsyncMock(return_value=None if case == "missing" else run)
    monkeypatch.setattr(router.process_service, "get_run", lookup)
    token = "incorrect" if case == "wrong-token" else "per-run-secret"
    response = await client.post(
        f"/api/multimedia/callback/{run_id}/{token}",
        json={"status": "completed", "url": "https://untrusted.example/output"},
    )
    assert response.status_code == (200 if case == "valid" else 404)
    if case == "valid":
        assert response.json() == {"received": True}
    assert run.status == "running"
    lookup.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
async def test_delivery_repair_requires_authentication_and_administration(client):
    run, receipt = uuid4(), uuid4()
    path = f"/api/multimedia/runs/{run}/deliveries/{receipt}/resolve"
    body = {"attempt_number": 1, "decision": "retry_absent", "evidence": "Checked the remote destination"}
    assert (await client.post(path, json=body)).status_code == 401
    from core.database import get_db_session
    from core.user.models import User
    from core.user.user_service import encrypt_password
    email = f"repair-{uuid4()}@example.com"
    async with get_db_session() as db:
        db.add(User(email=email, hashed_password=encrypt_password("repair-password"), is_active=True))
    login = await client.post("/api/auth/login-json", json={"email": email, "password": "repair-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.post(path, headers=headers, json=body)).status_code == 403
    assert (await client.get(f"/api/multimedia/runs/{run}/deliveries", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_delivery_repair_cannot_cross_managed_agent_scope(monkeypatch):
    from fastapi import HTTPException
    from app.agent import AgentManagementScope
    from app.multimedia.delivery import DeliveryRepair
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, frozenset({7}))))
    monkeypatch.setattr(router.process_service, "get_run", AsyncMock(return_value=SimpleNamespace(engine_code="multimedia", launcher_agent_id=8)))
    repair = AsyncMock()
    monkeypatch.setattr(router, "repair_delivery", repair)
    with pytest.raises(HTTPException) as error:
        await router.resolve_delivery(uuid4(), uuid4(), DeliveryRepair(attempt_number=1, decision="retry_absent", evidence="Checked by another agent"))
    assert error.value.status_code == 404
    repair.assert_not_awaited()
