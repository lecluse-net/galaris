"""Identity lists and authorization matrices do not need Agent profile payloads."""

import json
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select

from app.agent.models import Agent, Title
from app.skill import skill_service, storage
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
async def test_skill_agent_http_preserves_manager_scope_and_assignment_privileges(client, tmp_path, monkeypatch):
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    password = "synthetic-skill-reader-password"
    async with get_db_session() as db:
        from app.connection import Connection
        from app.tools import ToolModel
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
        other_id = agents[1].id
        tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == 'skills'))
        connection = Connection(agent_id=owner_id, tool_id=tool_id, active=True)
        db.add(connection)
        await db.flush()
        connection_id = connection.id
        packages = [Skill(code="private-guide", label="Synthetic private guide", owner_agent_id=agent.id,
                          creator_agent_id=agent.id, assignments=[]) for agent in agents]
        db.add_all(packages)
        await db.flush()
        package_ids = [package.id for package in packages]
        for agent, package in zip(agents, packages, strict=True):
            package.assignments.append(AgentSkill(agent_id=agent.id, active=True))
            await storage.install_markdown(package.code, package.label,
                f"---\nname: private-guide\ndescription: Synthetic guide.\n---\nOwner {agent.id}\n",
                owner_agent_id=agent.id)
    path = "/api/skills/agents"
    assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(2):
        # Independent browser sessions: logging in with an existing refresh cookie
        # revokes that session and would invalidate the first user's bearer token.
        client.cookies.clear()
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
    personal_path = "/api/skills/personal"
    assert (await client.get(personal_path)).status_code == 401
    assert (await client.get(personal_path, headers=headers[1])).status_code == 403
    personal = await client.get(personal_path, headers=headers[0], params={"page_size": 500})
    assert personal.status_code == 200, personal.text
    assert personal.json()["total"] == 1
    item = personal.json()["items"][0]
    assert item["id"] == package_ids[0] and item["owner_agent_id"] == owner_id
    assert item["enabled"] and item["valid"] and item["file_count"] == 1
    assert (await client.get(personal_path, headers=headers[0], params={"search": "absent"})).json()["total"] == 0
    assert (await client.get(personal_path, headers=headers[0], params={"owner_agent_id": other_id})).status_code == 404
    detail = await client.get(f"{personal_path}/{package_ids[0]}", headers=headers[0])
    assert detail.status_code == 200 and detail.json()["files"][0]["path"] == "SKILL.md"
    content = await client.get(f"{personal_path}/{package_ids[0]}/content", headers=headers[0])
    assert content.status_code == 200 and f"Owner {owner_id}" in content.json()["content"]
    for suffix in ("", "/content"):
        assert (await client.get(f"{personal_path}/{package_ids[1]}{suffix}", headers=headers[0])).status_code == 404
        assert (await client.get(f"{personal_path}/{package_ids[0]}{suffix}", headers=headers[1])).status_code == 403
    assert (await client.get(f"{personal_path}/{package_ids[0]}/content", headers=headers[0], params={"path": "../secret"})).status_code == 422
    generic = await client.get("/api/skills", headers=headers[0])
    assert {row["id"] for row in generic.json()}.isdisjoint(package_ids)
    scope_path = f"/api/connections/{connection_id}/params/bulk"
    def scope_data(value):
        return {'connection_id': connection_id, 'params': {'tools.management_scope': value}}
    assert (await client.post(scope_path, headers=headers[0], json=scope_data('all'))).status_code == 403
    assert (await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'active': False, 'params': {'tools.management_scope': 'all'},
    })).status_code == 403
    from sqlalchemy.orm import selectinload
    async with get_db_session() as db:
        reader_role = await db.scalar(select(Role).where(Role.code == "synthetic-skill-reader").options(selectinload(Role.privileges)))
        reader_role.privileges.append(await db.scalar(select(Privilege).where(Privilege.code == "SKILL_EDIT")))
        reader_role.privileges.append(await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_EDIT")))
        from app.connection import ConnectionParam
        same_manager = Agent(user_id=users[0].id, title_id=title.id, code='synthetic-scope-same-manager',
            first_name='Synthetic', last_name='Same manager', agent_driver='internal')
        db.add(same_manager)
        db.add(ConnectionParam(connection_id=connection_id, param_name='tools.management_scope', param_value='all'))
        await db.flush()
        same_manager_id = same_manager.id
    assert (await client.post(scope_path, headers=headers[0], json=scope_data('all'))).status_code == 403
    assert (await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'agent_id': same_manager_id,
    })).status_code == 403
    assert (await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'active': False, 'params': {'tools.management_scope': 'personal'},
    })).status_code == 403
    unchanged = (await client.get(f'/api/connections/{connection_id}', headers=headers[0])).json()
    assert unchanged['active'] and unchanged['agent_id'] == owner_id
    async with get_db_session() as db:
        reader_role = await db.scalar(select(Role).where(Role.code == "synthetic-skill-reader").options(selectinload(Role.privileges)))
        reader_role.privileges.append(await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL")))
    assert (await client.post(scope_path, headers=headers[0], json=scope_data('personal'))).status_code == 201
    assert (await client.get(f'/api/connections/{connection_id}/params', headers=headers[0])).json()['params']['tools.management_scope'] == 'personal'
    assert (await client.post(scope_path, headers=headers[0], json=scope_data('team'))).status_code == 201
    assert (await client.post(scope_path, headers=headers[0], json=scope_data('unknown'))).status_code == 422
    configured = await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'active': False, 'params': {'tools.management_scope': 'all'},
    })
    assert configured.status_code == 200 and not configured.json()['active']
    failed = await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'active': True, 'params': {'tools.management_scope': 'unknown'},
    })
    assert failed.status_code == 422
    assert not (await client.get(f'/api/connections/{connection_id}', headers=headers[0])).json()['active']
    assert (await client.get(f'/api/connections/{connection_id}/params', headers=headers[0])).json()['params']['tools.management_scope'] == 'all'
    assert (await client.patch(f'/api/connections/{connection_id}', headers=headers[0], json={
        'active': True, 'params': {'tools.management_scope': 'team'},
    })).status_code == 200
    failed_creation = await client.post('/api/connections', headers=headers[0], json={
        'agent_id': other_id, 'tool_id': tool_id, 'active': True,
        'params': {'tools.management_scope': 'unknown'},
    })
    assert failed_creation.status_code == 422
    assert (await client.get('/api/connections', headers=headers[0], params={'agent_id': other_id})).json() == []
    from uuid import uuid4
    release = await client.post(f"/api/skills/{package_ids[0]}/release-ownership", headers=headers[0], json={
        "expected_revision": 1, "operation_id": str(uuid4()), "new_code": "http-released-guide",
    })
    assert release.status_code == 200, release.text
    assert release.json()["uri"] == "galaris://skill/http-released-guide/"
    assert (await client.get(f"{personal_path}/{package_ids[0]}", headers=headers[0])).status_code == 404
