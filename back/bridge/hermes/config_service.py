"""Bridge-owned Hermes configuration."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import secrets
from typing import Any

from sqlalchemy import select

from core.database import get_db
from core.i18n import render_prompt, tr
from core.util import (
    SECRET_MASK,
    encrypt_mapping_values,
    get_encryption_service,
    mask_mapping_values,
)

from .models import HermesAgentConfig
from .schemas import HermesAgentConfiguration, HermesConfigUpdate


_FIELDS = ("url", "api_key", "model", "api_port", "dashboard_enabled", "dashboard_port",
           "dashboard_username", "dashboard_password_hash", "config", "compose", "mcp_token", "data_env")


@dataclass(frozen=True)
class HermesDataEnvEncryptionResult:
    """Number of bridge-owned environment maps encrypted in place."""
    configs_updated: int


def _stored_payload(config: HermesAgentConfig) -> dict[str, Any]:
    return {
        field: getattr(config, field)
        for field in _FIELDS
    }


async def get_config(agent_id: int) -> HermesAgentConfig | None:
    """Return the driver-owned row, if the expansion has reached this agent."""

    result = await get_db().execute(
        select(HermesAgentConfig).where(HermesAgentConfig.agent_id == agent_id)
    )
    return result.scalar_one_or_none()


def _encrypt_if_needed(value: str | None) -> str | None:
    if not value:
        return value
    encryption = get_encryption_service()
    return value if encryption.is_encrypted(value) else encryption.encrypt(value)


def _hash_dashboard_password(password: str) -> str:
    """Produce the format expected by Hermes' dashboard authentication plugin."""

    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${digest_b64}"


async def ensure_config(agent: Any) -> HermesAgentConfig:
    """Return or initialize the bridge-owned configuration."""

    config = await get_config(int(agent.id))
    if config is not None:
        return config
    from sqlalchemy.dialects.postgresql import insert
    await get_db().execute(insert(HermesAgentConfig).values(agent_id=int(agent.id))
                          .on_conflict_do_nothing(index_elements=[HermesAgentConfig.agent_id]))
    config = await get_config(int(agent.id))
    assert config is not None
    return config


def _public_configuration(
    agent: Any,
    payload: dict[str, Any],
) -> HermesAgentConfiguration:
    return HermesAgentConfiguration(
        id=int(agent.id),
        code=str(agent.code),
        first_name=str(agent.first_name),
        last_name=str(agent.last_name),
        hermes_dashboard_enabled=bool(payload["dashboard_enabled"]),
        hermes_dashboard_port=payload["dashboard_port"],
        hermes_dashboard_username=payload["dashboard_username"],
        hermes_dashboard_password_configured=bool(payload["dashboard_password_hash"]),
        hermes_config=payload["config"],
        hermes_compose=payload["compose"],
        hermes_data_env=mask_mapping_values(dict(payload["data_env"] or {})),
    )


async def public_configuration(agent: Any) -> HermesAgentConfiguration:
    """Return the bridge configuration without exposing encrypted secrets."""

    config = await ensure_config(agent)
    return _public_configuration(agent, _stored_payload(config))


async def update_configuration(
    agent: Any,
    update: HermesConfigUpdate,
) -> HermesAgentConfiguration:
    """Persist an operator edit in the bridge-owned table only."""

    config = await ensure_config(agent)
    data = update.model_dump()
    password = data.pop("hermes_dashboard_password", None)
    raw_env = dict(data.pop("hermes_data_env", {}) or {})
    existing_env = dict(config.data_env or {})
    merged_env: dict[str, str] = {}
    for key, value in raw_env.items():
        if value == SECRET_MASK:
            previous = existing_env.get(key)
            if previous is None:
                raise ValueError(
                    render_prompt(
                        await tr("agent_api.errors.secret_placeholder_without_value"),
                        key=key,
                    )
                )
            merged_env[key] = previous
        else:
            merged_env[key] = value

    field_names = {
        "hermes_dashboard_enabled": "dashboard_enabled",
        "hermes_dashboard_port": "dashboard_port",
        "hermes_dashboard_username": "dashboard_username",
        "hermes_config": "config",
        "hermes_compose": "compose",
    }
    for source, target in field_names.items():
        setattr(config, target, data[source])
    # Historical rows may still carry ``false``. The column is retained only
    # for expansion compatibility; it no longer controls runtime behaviour.
    config.use_galaris_llm = True
    if isinstance(password, str) and password:
        if not config.dashboard_username:
            config.dashboard_username = "admin"
        config.dashboard_password_hash = _encrypt_if_needed(
            _hash_dashboard_password(password)
        )
    config.data_env = encrypt_mapping_values(merged_env)
    db = get_db()
    await db.commit()
    await db.refresh(config)
    return _public_configuration(agent, _stored_payload(config))


async def update_runtime_target(
    agent: Any,
    *,
    api_key: str,
    url: str,
    model: str,
) -> HermesAgentConfig:
    """Persist endpoint credentials created by the Hermes provisioner."""

    config = await ensure_config(agent)
    config.api_key = _encrypt_if_needed(api_key)
    config.url = url
    config.model = model
    await get_db().commit()
    await get_db().refresh(config)
    return config


async def set_mcp_token(agent: Any, token: str) -> None:
    """Store Hermes' system MCP token in bridge-owned persistence."""

    config = await ensure_config(agent)
    config.mcp_token = _encrypt_if_needed(token)
    await get_db().commit()


async def execution_snapshot(agent: Any) -> dict[str, Any]:
    """Return the immutable, minimal configuration needed by a Hermes run."""

    config = await ensure_config(agent)
    payload = _stored_payload(config)
    return {
        "url": payload["url"],
        "api_key": payload["api_key"],
        "model": payload["model"],
        "model_gateway": "galaris",
        "kanban": {
            "transport": "legacy",
            "board": "default",
            "assignee": "default",
            "workspace_path": "/opt/data/galaris",
        },
    }


async def encrypt_persisted_data_env() -> HermesDataEnvEncryptionResult:
    """Encrypt old plaintext maps in the authoritative bridge table only."""
    configs = (await get_db().scalars(select(HermesAgentConfig))).all()
    updated = 0
    for config in configs:
        protected = encrypt_mapping_values(config.data_env or {})
        if protected != (config.data_env or {}):
            config.data_env = protected
            updated += 1
    await get_db().flush()
    return HermesDataEnvEncryptionResult(configs_updated=updated)
