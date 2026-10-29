"""Transfer legacy Agent columns before DbAdmin contracts their schema."""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import encrypt_mapping_values, get_encryption_service

from .models import HermesAgentConfig


_FIELDS = (
    "url", "api_key", "model", "api_port", "dashboard_enabled", "dashboard_port",
    "dashboard_username", "dashboard_password_hash", "config", "compose", "mcp_token", "data_env",
)


async def _legacy_rows(session: AsyncSession) -> list[dict[str, Any]]:
    columns = set(await session.scalars(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'agents' AND column_name LIKE 'hermes_%'
    """)))
    fields = [name for name in _FIELDS if f"hermes_{name}" in columns]
    if not fields:
        return []
    # Every identifier comes from the fixed tuple, never from persisted values.
    selection = ", ".join(f"hermes_{name} AS {name}" for name in fields)
    rows = (await session.execute(text(f"SELECT id AS agent_id, agent_driver, {selection} FROM agents"))).mappings()
    return [dict(row) for row in rows if row["agent_driver"] == "hermes" or any(
        row.get(name) not in (None, False, "", {}, "hermes-agent") for name in fields
    )]


async def _complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    rows = await _legacy_rows(session)
    if not rows:
        return True
    assigned = set(await session.scalars(select(HermesAgentConfig.agent_id)))
    return all(row["agent_id"] in assigned for row in rows)


async def _transfer(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    for row in await _legacy_rows(session):
        row.pop("agent_driver")
        row["model"] = row.get("model") or "hermes-agent"
        row["dashboard_enabled"] = bool(row.get("dashboard_enabled"))
        row["data_env"] = encrypt_mapping_values(dict(row.get("data_env") or {}))
        for field in ("api_key", "dashboard_password_hash", "mcp_token"):
            value = row.get(field)
            encryption = get_encryption_service()
            row[field] = encryption.encrypt(value) if value and not encryption.is_encrypted(value) else value
        await session.execute(insert(HermesAgentConfig).values(**row)
                              .on_conflict_do_nothing(index_elements=[HermesAgentConfig.agent_id]))


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="bridge.hermes.retire_agent_columns", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="preserve-bridge-config-before-agent-column-removal",
        predicate=lambda delta: any(key.startswith("agents.hermes_") for key in delta.removed_columns),
        handler=_transfer, postcondition=_complete,
    ))
