"""Assembled catalogue API preserves RBAC and per-manager assignment counts."""

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.agent.models import Title
from app.harnesses.models import AgentHarness, Harness
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_catalogue_http_scopes_counts_and_rechecks_after_reassignment(client):
    password = "synthetic-catalogue-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "HARNESS_CONFIG_ACCESS"))
        title_id = await db.scalar(select(Title.id).limit(1))
        reader = Role(code="synthetic-catalogue-reader", privileges=[privilege])
        users = [UserModel(email=f"catalogue-{name}@example.com", is_active=True,
                           hashed_password=encrypt_password(password))
                 for name in ("owner", "empty", "denied")]
        harness = Harness(name="Synthetic HTTP catalogue", provider_code="openai_messages",
                          driver_code="openai_messages", enabled=True)
        db.add_all([reader, harness, *users])
        await db.flush()
        for user in users[:2]:
            db.add(Assignment(user_id=user.id, role_id=reader.id, is_default=True))
        agents = [Agent(title_id=title_id, code=f"catalogue-http-{index}",
                        first_name="Synthetic", last_name=str(index), user_id=user.id)
                  for index, user in enumerate((users[0], users[2]))]
        db.add_all(agents)
        await db.flush()
        db.add_all([AgentHarness(agent_id=agent.id, harness_id=harness.id,
                                provider_code="openai_messages") for agent in agents])
        harness_id, moving_agent_id, empty_user_id = harness.id, agents[0].id, users[1].id

    urls = ("/api/harnesses/catalog", f"/api/harnesses/catalog/{harness_id}")
    for url in urls:
        assert (await client.get(url)).status_code == 401
    headers = {}
    for name, count in (("owner", 1), ("empty", 0), ("denied", None)):
        login = await client.post("/api/auth/login-json", json={
            "email": f"catalogue-{name}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers[name] = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for url in urls:
            response = await client.get(url, headers=headers[name])
            assert response.status_code == (403 if count is None else 200)
            if count is not None:
                payload = response.json()
                item = next(row for row in payload if row["id"] == str(harness_id)) if isinstance(payload, list) else payload
                assert item["assigned_agents"] == count
                assert "api_token_encrypted" not in item

    async with get_db_session() as db:
        agent = await db.get(Agent, moving_agent_id)
        agent.user_id = empty_user_id
    for name, expected in (("owner", 0), ("empty", 1)):
        for url in urls:
            response = await client.get(url, headers=headers[name])
            assert response.status_code == 200
            payload = response.json()
            item = next(row for row in payload if row["id"] == str(harness_id)) if isinstance(payload, list) else payload
            assert item["assigned_agents"] == expected
