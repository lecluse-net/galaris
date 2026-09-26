"""The bundled assistant is a proposal that administrators keep control of."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.defaults import default_agent_dataset
from app.agent.models import Agent, Title
from app.connection import Connection
from app.skill import AgentSkill, skill_service
from app.tools import ToolModel, has_documentation_access, has_galaris_admin_access, initialize_admin_agent_connections
from app.tools.dbadmin import datasets as tool_datasets
from core.authorize import Assignment, Role
from core.database import get_db_session
from core.dbadmin import DbAdminDatasetResult, reconcile_dataset
from core.user import UserModel, notify_user_access_changed


async def _admin(db):
    user = UserModel(email="seed-admin@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    role = await db.scalar(select(Role).where(Role.code == "admin"))
    db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    await db.flush()
    return user


async def _proposal(db):
    return (await db.scalars(select(Agent).where(Agent.initialization_key == "galaris"))).one()


@pytest.mark.asyncio
@pytest.mark.parametrize("skill_code", ["galaris-lab", "galaris-knowledge"])
async def test_seed_waits_for_manager_then_preserves_edits_revocations_and_deletion(db, skill_code):
    dataset = default_agent_dataset()
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    user = await _admin(db)
    user.is_active = False
    await db.flush()
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    user.is_active = True
    await db.flush()
    assert (await reconcile_dataset(db, dataset)).inserted == 1
    agent = await _proposal(db)
    assert agent.first_name == "Galaris"
    assert agent.user_id == user.id
    assert agent.agent_driver == "internal"
    assert agent.task_harness_id is None and agent.profile_id is None
    assert agent.profile_media_type == "text/html"
    assert await has_galaris_admin_access(agent.id)
    assert await has_documentation_access(agent.id)
    skill = await skill_service.get_by_code(skill_code)
    assert skill is not None and not skill.global_enabled
    assert skill_code in await skill_service.get_assigned_codes(agent.id)

    agent.first_name = "Custom assistant"
    agent.code = "custom-assistant"
    agent.job_description = "<p>Custom duties</p>"
    from app.llm.profile_models import LlmProfile

    custom_profile = LlmProfile(label="Custom profile", code="custom-profile")
    db.add(custom_profile)
    await db.flush()
    agent.profile_id = custom_profile.id
    agent.agent_driver = "hermes"
    admin_tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris_admin"))
    connection = (await db.scalars(select(Connection).where(
        Connection.agent_id == agent.id, Connection.tool_id == admin_tool_id,
    ))).one()
    connection.active = False
    await db.commit()
    await skill_service.set_agent_authorization(skill.id, agent.id, "disabled")

    # Replay the complete set of ordinary connection defaults as on an update.
    for definition in tool_datasets():
        await reconcile_dataset(db, definition)
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    await db.refresh(agent)
    assert (agent.first_name, agent.code, agent.job_description) == (
        "Custom assistant", "custom-assistant", "<p>Custom duties</p>",
    )
    assert not await has_galaris_admin_access(agent.id)
    assert not await has_documentation_access(agent.id)
    assert skill_code not in await skill_service.get_assigned_codes(agent.id)
    assignment = await db.scalar(select(AgentSkill).where(
        AgentSkill.agent_id == agent.id, AgentSkill.skill_id == skill.id,
    ))
    assert assignment.active is False
    assert agent.profile_id == custom_profile.id and agent.agent_driver == "hermes"

    agent.soft_delete()
    await db.commit()
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    assert await db.scalar(select(Agent.id)) is None
    await db.refresh(agent)
    assert agent.deleted_at is not None


@pytest.mark.asyncio
async def test_seed_preserves_existing_galaris_agent(db):
    user = await _admin(db)
    title_id = await db.scalar(select(Title.id).limit(1))
    existing = Agent(code="galaris", first_name="Existing", last_name="Agent",
                     user_id=user.id, title_id=title_id)
    db.add(existing)
    await db.flush()
    assert (await reconcile_dataset(db, default_agent_dataset())).inserted == 1
    proposal = await _proposal(db)
    assert proposal.id != existing.id and proposal.code != existing.code
    await db.refresh(existing)
    assert existing.first_name == "Existing" and existing.initialization_key is None
    assert not await has_galaris_admin_access(existing.id)
    # Documentation access alone must not grant the bundled assistant's skills.
    await initialize_admin_agent_connections(existing.id)
    assert await has_documentation_access(existing.id)
    existing_skills = await skill_service.get_assigned_codes(existing.id)
    proposal_skills = await skill_service.get_assigned_codes(proposal.id)
    for code in ("galaris-lab", "galaris-knowledge"):
        assert code not in existing_skills
        assert code in proposal_skills


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["dataset", "user_observer"])
@pytest.mark.parametrize("grant", ["connections", "skills"])
async def test_seed_failure_rolls_back_agent_and_grants_and_can_retry(db, monkeypatch, entrypoint, grant):
    import app.tools
    import app.skill

    user = await _admin(db)
    await db.commit()
    module = app.tools if grant == "connections" else app.skill
    method = "initialize_admin_agent_connections" if grant == "connections" else "initialize_galaris_agent_skills"
    initialize = getattr(module, method)

    async def fail_after_grant(agent_id):
        await initialize(agent_id)
        raise RuntimeError("Synthetic initialization failure")

    monkeypatch.setattr(module, method, fail_after_grant)
    if entrypoint == "dataset":
        with pytest.raises(RuntimeError, match="Synthetic"):
            async with db.begin_nested():
                await reconcile_dataset(db, default_agent_dataset())
    else:
        await notify_user_access_changed(user.id)
    assert await db.scalar(select(Agent.id)) is None
    assert await db.scalar(select(AgentSkill.id)) is None
    monkeypatch.setattr(module, method, initialize)
    assert (await reconcile_dataset(db, default_agent_dataset())).inserted == 1
    assert await has_documentation_access((await _proposal(db)).id)
    assert {"galaris-lab", "galaris-knowledge"} <= set(
        await skill_service.get_assigned_codes((await _proposal(db)).id)
    )


@pytest.mark.asyncio
async def test_concurrent_initialization_proposes_only_one_agent(committed_database):
    async with get_db_session() as session:
        await _admin(session)

    async def seed():
        async with get_db_session() as session:
            return await reconcile_dataset(session, default_agent_dataset())

    results = await asyncio.gather(seed(), seed())
    assert sum(result.inserted for result in results) == 1
    async with get_db_session() as session:
        assert len((await session.scalars(select(Agent))).all()) == 1
        assert await has_documentation_access((await _proposal(session)).id)


@pytest.mark.asyncio
async def test_first_signup_immediately_proposes_manageable_galaris(client, monkeypatch):
    from app.console import provisioning
    from app.console.contracts import ConsoleStatus

    monkeypatch.setattr(provisioning.embedded_executor_manager, "request",
                        AsyncMock(return_value={"ssh_host_key": "ssh-ed25519 synthetic-host-key"}))
    transport = AsyncMock()
    transport.status.return_value = ConsoleStatus(
        reachable=True, authenticated=True, host_key_verified=True,
        home_writable=True, sftp_available=True,
    )
    monkeypatch.setattr(provisioning, "SshExecutionTransport", lambda config: transport)
    credentials = {"email": "onboarding@example.com", "password": "synthetic-password-123"}
    response = await client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    agents = await client.get("/api/agents", headers=headers)
    assert agents.status_code == 200
    records = agents.json()
    assert len(records) == 1
    agent = records[0]
    assert agent["first_name"] == "Galaris"
    assert agent["agent_driver"] == "internal" and agent["profile_id"] is None
    assert "initialization_key" not in agent
    authorizations = await client.get(
        "/api/skills/authorizations", headers=headers, params={"agent_id": agent["id"]},
    )
    assert authorizations.status_code == 200, authorizations.text
    for code in ("galaris-lab", "galaris-knowledge"):
        skill = next(row for row in authorizations.json()["authorizations"] if row["code"] == code)
        assert skill["agent_state"] == "enabled" and skill["effective"] is True
        assert skill["global_state"] == "disabled"
    changed = await client.put(f"/api/agents/{agent['id']}", headers=headers,
                               json={"first_name": "My assistant"})
    assert changed.status_code == 200, changed.text
    deleted = await client.delete(f"/api/agents/{agent['id']}", headers=headers)
    assert deleted.status_code == 204
    # User changes notify the same observer that handles first registration.
    updated = await client.put("/api/auth/me", headers=headers, json={"display_name": "New name"})
    assert updated.status_code == 200
    assert (await client.get("/api/agents", headers=headers)).json() == []
