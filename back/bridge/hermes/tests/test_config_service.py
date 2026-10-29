from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from bridge.hermes import config_service
from bridge.hermes.models import HermesAgentConfig
from bridge.hermes.schemas import HermesConfigUpdate
from core.util import SECRET_MASK, decrypt_mapping_values, get_encryption_service


async def _agent(db: AsyncSession, *, code: str, suffix: int) -> Agent:
    title = Title(label=f"Title {suffix}", gender="F")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code=code,
        first_name="Alice",
        last_name="Martin",
        agent_driver="hermes",
    )
    db.add(agent)
    await db.flush()
    from core.util import encrypt_mapping_values
    db.add(HermesAgentConfig(
        agent_id=agent.id, url=f"http://{code}:8642/v1", api_key=f"encrypted-key-{suffix}",
        model="hermes-agent", api_port=8600 + suffix, dashboard_enabled=True,
        data_env=encrypt_mapping_values({"CUSTOM_FLAG": str(suffix)}),
    ))
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_sync_hydrate_and_execution_snapshot_use_driver_owned_row(
    db: AsyncSession,
) -> None:
    agent = await _agent(db, code="hermes-config-sync", suffix=1)

    config = await config_service.ensure_config(agent)

    assert config.agent_id == agent.id
    assert config.url == "http://hermes-config-sync:8642/v1"
    assert config.api_key == "encrypted-key-1"
    assert await config_service.ensure_config(agent) is config
    assert config.use_galaris_llm is True
    assert config.data_env != {"CUSTOM_FLAG": "1"}
    assert decrypt_mapping_values(config.data_env) == {"CUSTOM_FLAG": "1"}
    config.url = "http://authoritative:8642/v1"
    config.api_key = "authoritative-encrypted-key"
    config.data_env = {"SOURCE": "new-table"}
    await db.flush()

    snapshot = await config_service.execution_snapshot(agent)

    assert config.url == "http://authoritative:8642/v1"
    assert config.data_env == {"SOURCE": "new-table"}
    assert snapshot == {
        "url": "http://authoritative:8642/v1",
        "api_key": "authoritative-encrypted-key",
        "model": "hermes-agent",
        "model_gateway": "galaris",
        "kanban": {
            "transport": "legacy",
            "board": "default",
            "assignee": "default",
            "workspace_path": "/opt/data/galaris",
        },
    }


@pytest.mark.asyncio
async def test_operator_llm_flag_cannot_disable_galaris_routing(
    db: AsyncSession,
) -> None:
    agent = await _agent(db, code="hermes-direct-llm", suffix=4)
    config = await config_service.ensure_config(agent)

    assert config.use_galaris_llm is True
    config.use_galaris_llm = False
    await db.flush()
    snapshot = await config_service.execution_snapshot(agent)

    assert snapshot["model_gateway"] == "galaris"


@pytest.mark.asyncio
async def test_bridge_update_owns_secrets_and_returns_only_masks(
    db: AsyncSession,
) -> None:
    agent = await _agent(db, code="hermes-bridge-update", suffix=5)
    config = await config_service.ensure_config(agent)
    config.data_env = {
        "EXISTING": get_encryption_service().encrypt("old-secret"),
    }
    await db.commit()

    public = await config_service.update_configuration(
        agent,
        HermesConfigUpdate(
            hermes_dashboard_enabled=True,
            hermes_dashboard_username="operator",
            hermes_dashboard_password="new-password",
            hermes_data_env={
                "EXISTING": SECRET_MASK,
                "NEW": "new-secret",
            },
        ),
    )

    stored = await config_service.get_config(agent.id)
    assert stored is not None
    assert decrypt_mapping_values(stored.data_env) == {
        "EXISTING": "old-secret",
        "NEW": "new-secret",
    }
    assert stored.url == "http://hermes-bridge-update:8642/v1"
    assert stored.model == "hermes-agent"
    assert stored.api_port == 8605
    public_payload = public.model_dump()
    assert "hermes_url" not in public_payload
    assert "hermes_model" not in public_payload
    assert "hermes_api_port" not in public_payload
    assert "hermes_use_galaris_llm" not in public_payload
    assert public.hermes_dashboard_password_configured is True
    assert public.hermes_data_env == {
        "EXISTING": SECRET_MASK,
        "NEW": SECRET_MASK,
    }
