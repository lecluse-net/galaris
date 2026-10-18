"""The home overview checks Tool existence without loading their configurations."""

import json
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.onboarding.services import check_tools_status
from app.tools.models import Tool
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_tools_status_does_not_materialize_the_catalogue(db):
    db.add_all([Tool(code=f"synthetic-welcome-tool-{index}", label=f"Synthetic Tool {index}",
                     description="Synthetic description. " * 5000) for index in range(41)])
    await db.commit()
    db.expunge_all()
    loaded = []

    def materialized(_session, instance):
        if isinstance(instance, Tool):
            loaded.append(instance)

    event.listen(Session, "loaded_as_persistent", materialized)
    try:
        assert await check_tools_status() is True
    finally:
        event.remove(Session, "loaded_as_persistent", materialized)
    report = {"synthetic_tools": 41, "materialized_tools": len(loaded),
              "description_bytes": sum(len(tool.description.encode()) for tool in loaded)}
    destination = Path(__file__).resolve().parents[4] / "artifacts/onboarding-tool-reads.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert not loaded, report


@pytest.mark.asyncio
async def test_overview_http_reports_tools_without_edit_rights(client):
    password = "synthetic-welcome-reader-password"
    async with get_db_session() as db:
        db.add(UserModel(email="welcome-reader@example.com", is_active=True,
                         hashed_password=encrypt_password(password)))
    path = "/api/onboarding/overview"
    assert (await client.get(path)).status_code == 401
    login = await client.post("/api/auth/login-json", json={
        "email": "welcome-reader@example.com", "password": password,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = await client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["tools"] == {"show": False, "has_privilege": False, "has_data": True}
    assert response.json()["agents"]["has_data"] is False
    assert (await client.get(path, headers=headers)).json() == response.json()
