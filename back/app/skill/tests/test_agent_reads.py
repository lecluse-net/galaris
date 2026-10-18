"""Identity lists and authorization matrices do not need Agent profile payloads."""

import json
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select

from app.agent.models import Agent, Title
from app.skill import skill_service
from app.skill.models import AgentSkill, Skill
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_skill_agent_consumers_use_only_identity_fields_and_keep_scopes(db):
    title = Title(label="Synthetic skill readers", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"skill-reader-{index}", first_name=f"Reader {index:02d}",
                    last_name="Synthetic", agent_driver="internal" if index % 2 else "hermes",
                    avatar=b"a" * 100_000,
                    personality="<p>" + "Synthetic personality. " * 1000 + "</p>",
                    job_description="<p>" + "Synthetic job. " * 1000 + "</p>") for index in range(41)]
    removed = Agent(title_id=title.id, code="skill-reader-removed", first_name="Removed", last_name="Synthetic")
    db.add_all([*agents, removed])
    await db.flush()
    removed.soft_delete()
    skill = await db.scalar(select(Skill).where(Skill.code == "galaris"))
    db.add_all([AgentSkill(skill_id=skill.id, agent_id=agent.id, active=index % 2 == 0)
                for index, agent in enumerate(agents)])
    await db.commit()
    expected = [(agent.id, agent.code, agent.first_name, agent.last_name, agent.agent_driver) for agent in agents]
    skill_id = skill.id
    db.expunge_all()
    loaded = []

    def materialized(_session, instance):
        if isinstance(instance, Agent):
            loaded.append(sum(len(value if isinstance(value, bytes) else value.encode())
                              for name in ("avatar", "personality", "job_description")
                              if name not in inspect(instance).unloaded
                              and (value := getattr(instance, name)) is not None))

    event.listen(db.sync_session, "loaded_as_persistent", materialized)
    try:
        rows = await skill_service.list_skill_agents()
        assert [(row.id, row.code, row.first_name, row.last_name, row.agent_driver) for row in rows] == expected
        authorizations = await skill_service.list_authorizations(skill_id=skill_id)
        assert [item.agent_id for item in authorizations] == [item[0] for item in expected]
        assert [item.agent_state for item in authorizations] == ["enabled" if index % 2 == 0 else "disabled"
                                                              for index in range(41)]
    finally:
        event.remove(db.sync_session, "loaded_as_persistent", materialized)
    allowed = [expected[0][0], expected[-1][0]]
    assert [row.id for row in await skill_service.list_skill_agents(agent_ids=allowed)] == allowed
    assert await skill_service.list_skill_agents(agent_ids=[]) == []
    assert [item.agent_id for item in await skill_service.list_authorizations(
        skill_id=skill_id, agent_ids=allowed,
    )] == allowed
    # A subsequent full profile read must still retrieve the original payload.
    full = await db.scalar(select(Agent).where(Agent.id == allowed[0]))
    assert full.avatar == b"a" * 100_000 and "Synthetic personality." in full.personality
    report = {"agents": len(rows), "loaded_profile_bytes": sum(loaded)}
    destination = Path(__file__).resolve().parents[4] / "artifacts/skill-agent-reads.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert report["loaded_profile_bytes"] == 0, report


@pytest.mark.asyncio
async def test_skill_agent_http_preserves_manager_scope_and_assignment_privileges(client):
    password = "synthetic-skill-reader-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "SKILL_ACCESS"))
        role = Role(code="synthetic-skill-reader", privileges=[privilege])
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"skill-reader-{index}@example.com", hashed_password=password_hash,
                           is_active=True) for index in range(2)]
        title = Title(label="Synthetic HTTP skill reader", gender="N")
        db.add_all([role, title, *users])
        await db.flush()
        db.add(Assignment(user_id=users[0].id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-http-skill-{index}",
                        first_name="Synthetic", last_name=str(index), agent_driver="internal")
                  for index, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        owner_id = agents[0].id
    path = "/api/skills/agents"
    assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(2):
        login = await client.post("/api/auth/login-json", json={
            "email": f"skill-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert (await client.get(path, headers=headers[1])).status_code == 403
    response = await client.get(path, headers=headers[0])
    assert response.status_code == 200, response.text
    assert response.json() == [{"id": owner_id, "code": "synthetic-http-skill-0", "label": "Synthetic 0", "driver": "internal"}]
    assert (await client.get(path, headers=headers[0])).json() == response.json()
    assert (await client.get("/api/skills/authorizations", headers=headers[0])).status_code == 403
