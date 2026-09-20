"""Persistence and one-way legacy import for Hermes agent configuration."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import secrets
from typing import Any

from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.i18n import render_prompt, tr
from core.util import (
    SECRET_MASK,
    decrypt_mapping_values,
    encrypt_mapping_values,
    get_encryption_service,
    mask_mapping_values,
)

from .models import HermesAgentConfig
from .schemas import HermesAgentConfiguration, HermesConfigUpdate


# Database attribute -> legacy ``Agent`` attribute. Keeping this map in the
# driver module prevents the generic agent facade from knowing Hermes fields.
_FIELD_MAP: dict[str, str] = {
    "url": "hermes_url",
    "api_key": "hermes_api_key",
    "model": "hermes_model",
    "api_port": "hermes_api_port",
    "dashboard_enabled": "hermes_dashboard_enabled",
    "dashboard_port": "hermes_dashboard_port",
    "dashboard_username": "hermes_dashboard_username",
    "dashboard_password_hash": "hermes_dashboard_password_hash",
    "config": "hermes_config",
    "compose": "hermes_compose",
    "mcp_token": "hermes_mcp_token",
    "data_env": "hermes_data_env",
}


@dataclass(frozen=True)
class HermesConfigBackfillResult:
    """Observable outcome of one idempotent legacy backfill."""

    eligible: int
    created: int
    matched: int
    mismatched: int


@dataclass(frozen=True)
class HermesDataEnvEncryptionResult:
    """Number of legacy and driver-owned environment maps encrypted in place."""

    agents_updated: int
    configs_updated: int


def _legacy_payload(agent: Any) -> dict[str, Any]:
    payload = {
        field: getattr(agent, legacy_field, None)
        for field, legacy_field in _FIELD_MAP.items()
    }
    payload["model"] = str(payload.get("model") or "hermes-agent")
    payload["dashboard_enabled"] = bool(payload.get("dashboard_enabled"))
    payload["data_env"] = encrypt_mapping_values(
        dict(payload.get("data_env") or {})
    )
    return payload


def _stored_payload(config: HermesAgentConfig) -> dict[str, Any]:
    return {
        field: getattr(config, field)
        for field in _FIELD_MAP
    }


def _payloads_match(
    stored: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    """Compare encrypted maps semantically without logging their plaintext."""
    stored_copy = dict(stored)
    candidate_copy = dict(candidate)
    stored_env = dict(stored_copy.pop("data_env", {}) or {})
    candidate_env = dict(candidate_copy.pop("data_env", {}) or {})
    return (
        stored_copy == candidate_copy
        and decrypt_mapping_values(stored_env)
        == decrypt_mapping_values(candidate_env)
    )


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
    """Return the bridge row, importing legacy values only when it is absent."""

    config = await get_config(int(agent.id))
    if config is not None:
        return config
    return await sync_from_agent(agent)


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


async def sync_from_agent(agent: Any) -> HermesAgentConfig:
    """Import the generic model's legacy flat fields to this table.

    Runtime callers use this only when no driver-owned row exists. The caller owns
    the transaction and the bridge table becomes authoritative immediately.
    """

    db = get_db()
    config = await get_config(int(agent.id))
    payload = _legacy_payload(agent)
    if config is None:
        config = HermesAgentConfig(agent_id=int(agent.id), **payload)
        db.add(config)
    else:
        for field, value in payload.items():
            setattr(config, field, value)
    await db.flush()
    return config


async def hydrate_agent(agent: Any) -> None:
    """Overlay bridge values on an in-memory record for the legacy manager adapter."""

    config = await get_config(int(agent.id))
    if config is None:
        return
    for field, legacy_field in _FIELD_MAP.items():
        value = getattr(config, field)
        if field == "data_env":
            value = dict(value or {})
        setattr(agent, legacy_field, value)


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


async def backfill_legacy_configs() -> HermesConfigBackfillResult:
    """Create missing Hermes rows without overwriting newer table data.

    Re-running this function is safe. Existing rows are compared with the
    legacy source so operators can detect divergence during the dual-write
    transition without logging secrets or configuration values.
    """

    from app.agent import list_agent_records

    db = get_db()
    agents = await list_agent_records(
        driver_code="hermes",
        limit=1_000_000,
    )
    created = 0
    matched = 0
    mismatched = 0
    for agent in agents:
        payload = _legacy_payload(agent)
        config = await get_config(agent.id)
        if config is None:
            db.add(HermesAgentConfig(agent_id=agent.id, **payload))
            created += 1
            continue
        if _payloads_match(_stored_payload(config), payload):
            matched += 1
        else:
            mismatched += 1
    await db.flush()
    outcome = HermesConfigBackfillResult(
        eligible=len(agents),
        created=created,
        matched=matched,
        mismatched=mismatched,
    )
    logger.info(
        "Hermes configuration backfill: eligible={}, created={}, matched={}, mismatched={}",
        outcome.eligible,
        outcome.created,
        outcome.matched,
        outcome.mismatched,
    )
    if outcome.mismatched:
        logger.debug(
            "Hermes legacy source differs from {} authoritative bridge row(s); "
            "no value was overwritten.",
            outcome.mismatched,
        )
    return outcome


async def encrypt_persisted_data_env() -> HermesDataEnvEncryptionResult:
    """Encrypt plaintext values in both transitional Hermes configuration stores.

    The migration is idempotent because already encrypted Fernet values are
    retained byte-for-byte. Keys remain visible so operators can manage the
    mapping without reading its values.
    """
    from app.agent import list_agent_records

    db = get_db()
    agents = await list_agent_records(
        driver_code="hermes",
        limit=1_000_000,
    )
    configs = list((await db.execute(select(HermesAgentConfig))).scalars().all())
    agents_updated = 0
    configs_updated = 0

    for agent in agents:
        protected = encrypt_mapping_values(agent.hermes_data_env or {})
        if protected != (agent.hermes_data_env or {}):
            agent.hermes_data_env = protected
            agents_updated += 1

    for config in configs:
        protected = encrypt_mapping_values(config.data_env or {})
        if protected != (config.data_env or {}):
            config.data_env = protected
            configs_updated += 1

    await db.flush()
    outcome = HermesDataEnvEncryptionResult(
        agents_updated=agents_updated,
        configs_updated=configs_updated,
    )
    logger.info(
        "Hermes data environment encryption: agents_updated={}, configs_updated={}",
        outcome.agents_updated,
        outcome.configs_updated,
    )
    return outcome
