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
    generic_skill = generic.json()[0]
    enabled_path = f'/api/skills/{generic_skill["id"]}/enabled'
    activation = {"enabled": False, "expected_revision": generic_skill["revision"]}
    assert (await client.put(enabled_path, json=activation)).status_code == 401
    assert (await client.put(enabled_path, headers=headers[0], json=activation)).status_code == 403
    scope_path = f"/api/connections/{connection_id}/params/bulk"
    mutation_path = f"{personal_path}/{package_ids[0]}"
    assert (await client.put(mutation_path, headers=headers[0], json={"expected_revision": 1, "label": "Forbidden"})).status_code == 403
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
    assert (await client.put(f"{personal_path}/{package_ids[1]}", headers=headers[0], json={"expected_revision": 1, "label": "Forbidden"})).status_code == 404
    assert (await client.put(enabled_path, headers=headers[0], json=activation)).status_code == 403
    assert (await client.put(mutation_path, headers=headers[0], json={"expected_revision": 1, "label": "Human edited guide"})).status_code == 200
    source = "---\nname: private-guide\ndescription: Synthetic edited guide.\n---\nHuman source\n"
    rejected = await client.put(f"{mutation_path}/content", headers=headers[0], json={"expected_revision": 2, "path": "SKILL.md", "content": "invalid frontmatter", "label": "Must not be saved"})
    assert rejected.status_code == 422
    assert (await client.get(mutation_path, headers=headers[0])).json()["skill"]["label"] == "Human edited guide"
    saved = await client.put(f"{mutation_path}/content", headers=headers[0], json={"expected_revision": 2, "path": "SKILL.md", "content": source, "label": "Combined human edit"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 3
    stale = await client.put(f"{mutation_path}/content", headers=headers[0], json={"expected_revision": 2, "path": "SKILL.md", "content": "stale", "label": "Stale label"})
    assert stale.status_code == 409
    content = (await client.get(f"{mutation_path}/content", headers=headers[0])).json()
    assert content["content"] == source and content["revision"] == 3
    assert (await client.get(mutation_path, headers=headers[0])).json()["skill"]["label"] == "Combined human edit"
    assert (await client.put(f"{mutation_path}/enabled", headers=headers[0], json={"expected_revision": 3, "enabled": False})).status_code == 200
    assert (await client.request("DELETE", mutation_path, headers=headers[0], json={"expected_revision": 3})).status_code == 409
    assert (await client.post(f"/api/skills/{package_ids[0]}/release-ownership", headers=headers[0], json={"expected_revision": 4, "operation_id": "00000000-0000-0000-0000-000000000001"})).status_code == 403
    from uuid import uuid4
    transfer_path = f"{mutation_path}/owner"
    transfer = {"expected_revision": 4, "owner_agent_id": same_manager_id, "operation_id": str(uuid4())}
    assert (await client.post(transfer_path, headers=headers[1], json=transfer)).status_code == 403
    denied = await client.post(transfer_path, headers=headers[0], json={**transfer, "owner_agent_id": other_id})
    assert denied.status_code == 404, denied.text
    assert (await client.post(f"{personal_path}/{package_ids[1]}/owner", headers=headers[0], json=transfer)).status_code == 404
    assert (await client.post(transfer_path, headers=headers[0], json={**transfer, "expected_revision": 3})).status_code == 409
    original_prepare = storage.prepare_ownership_release
    def failed_transfer(*args, **kwargs):
        original_prepare(*args, **kwargs)
        raise RuntimeError("Synthetic transfer failure")
    with monkeypatch.context() as patch:
        patch.setattr(storage, "prepare_ownership_release", failed_transfer)
        failed = await client.post(transfer_path, headers=headers[0], json=transfer)
        assert failed.status_code == 409, failed.text
    preserved = (await client.get(mutation_path, headers=headers[0])).json()["skill"]
    assert preserved["owner_agent_id"] == owner_id and preserved["revision"] == 4 and not preserved["enabled"]
    assert (await client.get(f"{mutation_path}/content", headers=headers[0])).json()["content"] == source
    async with get_db_session() as db:
        collision = Skill(code="private-guide", label="Synthetic recipient homonym", owner_agent_id=same_manager_id, assignments=[])
        db.add(collision)
        await storage.install_markdown(collision.code, collision.label,
            "---\nname: private-guide\ndescription: Synthetic homonym.\n---\nPreserved recipient instructions\n", owner_agent_id=same_manager_id)
    assert (await client.post(transfer_path, headers=headers[0], json=transfer)).status_code == 409
    transfer["new_code"] = "transferred-guide"
    transferred = await client.post(transfer_path, headers=headers[0], json=transfer)
    assert transferred.status_code == 200, transferred.text
    assert (await client.post(transfer_path, headers=headers[0], json=transfer)).json() == transferred.json()
    moved = (await client.get(mutation_path, headers=headers[0])).json()["skill"]
    assert moved["owner_agent_id"] == same_manager_id and moved["revision"] == 5 and moved["enabled"]
    async with get_db_session() as db:
        assert [(item.agent_id, item.active) for item in (await db.scalars(select(AgentSkill).where(AgentSkill.skill_id == package_ids[0]))).all()] == [(same_manager_id, True)]
    back = await client.post(transfer_path, headers=headers[0], json={
        "expected_revision": 5, "owner_agent_id": owner_id, "operation_id": str(uuid4()), "new_code": "private-guide",
    })
    assert back.status_code == 200, back.text
    assert "Preserved recipient instructions" in storage.read_text("private-guide", "SKILL.md", owner_agent_id=same_manager_id)
    assert (await client.post(f"/api/skills/{package_ids[0]}/assign-ownership", headers=headers[0], json={
        "expected_revision": 4, "operation_id": "00000000-0000-0000-0000-000000000002", "owner_agent_id": owner_id,
    })).status_code == 403
    async with get_db_session() as db:
        removable = Skill(code="synthetic-delete", label="Disposable private guide", owner_agent_id=owner_id, assignments=[])
        db.add(removable)
        await db.flush()
        removable_id = removable.id
        await storage.install_markdown(removable.code, removable.label, "---\nname: synthetic-delete\ndescription: Synthetic.\n---\nRemove me\n", owner_agent_id=owner_id)
    assert (await client.request("DELETE", f"{personal_path}/{removable_id}", headers=headers[0], json={"expected_revision": 1})).status_code == 200
    assert (await client.get(f"{personal_path}/{removable_id}", headers=headers[0])).status_code == 404
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
    disabled = await client.put(enabled_path, headers=headers[0], json=activation)
    assert disabled.status_code == 200, disabled.text
    assert not disabled.json()["enabled"]
    assert disabled.json()["revision"] == activation["expected_revision"] + 1
    assert (await client.get(enabled_path.removesuffix('/enabled'), headers=headers[0])).json()["enabled"] is False
    assert (await client.put(enabled_path, headers=headers[0], json=activation)).status_code == 409
    assert (await client.put(f'/api/skills/personal/{generic_skill["id"]}/enabled', headers=headers[0],
                             json={"enabled": True, "expected_revision": disabled.json()["revision"]})).status_code == 404
    assert (await client.put(f'/api/skills/{package_ids[0]}/enabled', headers=headers[0],
                             json={"enabled": False, "expected_revision": 6})).status_code == 404
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
        "expected_revision": 6, "operation_id": str(uuid4()), "new_code": "http-released-guide",
    })
    assert release.status_code == 200, release.text
    assert release.json()["uri"] == "galaris://skill/http-released-guide/"
    assert (await client.get(f"{personal_path}/{package_ids[0]}", headers=headers[0])).status_code == 404
    assign_path = f"/api/skills/{package_ids[0]}/assign-ownership"
    assignment = {"expected_revision": 7, "operation_id": str(uuid4()), "owner_agent_id": other_id}
    assert (await client.post(assign_path, headers=headers[1], json=assignment)).status_code == 403
    stale = await client.post(assign_path, headers=headers[0], json={**assignment, "expected_revision": 4})
    assert stale.status_code == 409, stale.text
    response = await client.post(assign_path, headers=headers[0], json=assignment)
    assert response.status_code == 200, response.text
    assert (await client.post(assign_path, headers=headers[0], json=assignment)).json() == response.json()
    assert (await client.get(f"/api/skills/{package_ids[0]}", headers=headers[0])).status_code == 404
    assigned = (await client.get(f"{personal_path}/{package_ids[0]}", headers=headers[0])).json()["skill"]
    assert assigned["owner_agent_id"] == other_id and assigned["revision"] == 8 and assigned["enabled"]
    async with get_db_session() as db:
        record = await db.get(Skill, package_ids[0])
        assert not record.global_enabled and record.category_id is None
        assert [(row.agent_id, row.active) for row in (await db.scalars(select(AgentSkill).where(AgentSkill.skill_id == record.id))).all()] == [(other_id, True)]
