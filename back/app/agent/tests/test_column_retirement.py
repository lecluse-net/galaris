"""A populated legacy Agent schema survives real DbAdmin contraction and retry."""

from dataclasses import replace

import pytest
from sqlalchemy import select, text

from app.agent.dbadmin import register_dbadmin
from app.agent.defaults import default_agent_dataset
from app.agent.models import Agent, AgentGroup, AgentTeam, Title
from bridge.hermes.dbadmin import register_dbadmin as register_hermes
from bridge.hermes.models import HermesAgentConfig
from core import settings
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator, reconcile_dataset
from core.dbadmin._internal import atlas
from core.params import Param, Params
from core.user import UserModel
from core.util import decrypt_mapping_values, get_encryption_service


async def _legacy_agents(session):
    manager = UserModel(email="synthetic-agent-upgrade@example.test", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic upgrade", gender="X")
    team = AgentGroup(name="Synthetic retained team")
    session.add_all([manager, title, team])
    await session.flush()
    agents = [Agent(user_id=manager.id, title_id=title.id, code=f"synthetic-upgrade-{index}",
                    first_name="Synthetic", last_name=str(index), agent_driver="hermes") for index in range(2)]
    session.add_all(agents)
    await session.flush()
    current, archived = agents
    archived.soft_delete()
    session.add(HermesAgentConfig(agent_id=current.id, url="http://newer.example.test/v1", model="newer-model"))
    await session.flush()
    await session.execute(text("""
        ALTER TABLE agents
        ADD COLUMN group_id integer REFERENCES agent_groups(id),
        ADD COLUMN initialization_key varchar(50) UNIQUE,
        ADD COLUMN profile_media_type varchar(40) DEFAULT 'text/html',
        ADD COLUMN profile_legacy_source jsonb,
        ADD COLUMN hermes_url text, ADD COLUMN hermes_api_key text,
        ADD COLUMN hermes_model text DEFAULT 'hermes-agent',
        ADD COLUMN hermes_use_galaris_llm boolean DEFAULT true,
        ADD COLUMN hermes_api_port integer, ADD COLUMN hermes_dashboard_enabled boolean DEFAULT false,
        ADD COLUMN hermes_dashboard_port integer, ADD COLUMN hermes_dashboard_username text,
        ADD COLUMN hermes_dashboard_password_hash text, ADD COLUMN hermes_config text,
        ADD COLUMN hermes_compose text, ADD COLUMN hermes_mcp_token text,
        ADD COLUMN hermes_data_env jsonb DEFAULT '{}'::jsonb
    """))
    await session.execute(text("""
        UPDATE agents SET group_id = :team, hermes_url = 'http://old.example.test/v1',
            hermes_api_key = 'synthetic-old-api-key', hermes_mcp_token = 'synthetic-old-mcp-token',
            hermes_data_env = '{"SYNTHETIC_FLAG":"retained"}'::jsonb
        WHERE id IN (:current, :archived)
    """), {"team": team.id, "current": current.id, "archived": archived.id})
    await session.execute(text("""
        UPDATE agents SET initialization_key = 'galaris', personality = '# Retained personality',
            job_description = '**Retained duties**', profile_media_type = 'text/markdown',
            profile_legacy_source = '{"personality":"obsolete backup"}'::jsonb WHERE id = :id
    """), {"id": archived.id})
    await session.commit()
    return current.id, archived.id, team.id


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_key", [None, "app.agent.editorial_html", "app.agent.galaris_identity", "bridge.hermes.retire_agent_columns"])
async def test_real_upgrade_preserves_teams_hermes_and_deleted_assistant_identity(committed_database, monkeypatch, failure_key):
    engine = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(settings, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    async with committed_database() as session:
        current, archived, team = await _legacy_agents(session)
    declared = DbAdminRegistry()
    register_dbadmin(declared)
    register_hermes(declared)
    registry = DbAdminRegistry()
    for action in declared.actions:
        if action.key in {"app.agent.team_memberships", "app.agent.editorial_html", "app.agent.galaris_identity", "bridge.hermes.retire_agent_columns"}:
            registry.register_action(action)
    if failure_key:
        interrupted = DbAdminRegistry()
        for action in registry.actions:
            if action.key == failure_key:
                original = action.handler

                async def fail_after_transfer(session, delta):
                    await original(session, delta)
                    raise RuntimeError("Synthetic interruption before transfer commit")

                action = replace(action, handler=fail_after_transfer)
            interrupted.register_action(action)
        result = await orchestrator.synchronize_database(target_registry=interrupted)
        assert result.verdict is not DbAdminVerdict.CONVERGED
        async with committed_database() as session:
            assert await session.scalar(text("""
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'agents'
                    AND column_name IN ('group_id', 'initialization_key', 'profile_media_type', 'hermes_url')
            """)) == 4
    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED
    async with committed_database() as session:
        memberships = set((await session.execute(select(AgentTeam.agent_id, AgentTeam.team_id))).tuples())
        assert {(current, team), (archived, team)} <= memberships
        assert await session.scalar(select(Param.value).where(Param.name == Params.GALARIS_AGENT_ID)) == str(archived)
        profile = await session.get(Agent, archived, execution_options={"include_historized": True})
        assert profile.deleted_at is not None
        assert "<h1>Retained personality</h1>" in profile.personality
        assert "<strong>Retained duties</strong>" in profile.job_description
        assert (await session.get(HermesAgentConfig, current)).url == "http://newer.example.test/v1"
        copied = await session.get(HermesAgentConfig, archived)
        assert copied.url == "http://old.example.test/v1"
        assert get_encryption_service().decrypt(copied.api_key) == "synthetic-old-api-key"
        assert get_encryption_service().decrypt(copied.mcp_token) == "synthetic-old-mcp-token"
        assert decrypt_mapping_values(copied.data_env) == {"SYNTHETIC_FLAG": "retained"}
        assert await session.scalar(text("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'agents'
                AND (column_name LIKE 'hermes_%' OR column_name IN
                    ('group_id', 'initialization_key', 'profile_media_type', 'profile_legacy_source'))
        """)) == 0
        # Even the archived, renamed initial assistant suppresses future proposals.
        assert (await reconcile_dataset(session, default_agent_dataset())).inserted == 0
