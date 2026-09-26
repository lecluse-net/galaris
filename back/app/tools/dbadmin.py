"""Programmatic datasets for built-in tools and their default connections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection
from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminRegistry

from .mandatory_tools import (
    AUTO_CONNECTED_INTEGRATED_TOOL_CODES,
    DEFAULT_ACTIVE_INTEGRATED_TOOL_CODES,
    DEFAULT_CONVERSATION_TOOL_CODES,
    mandatory_tool_rows,
    SYSTEM_TOOL_CODES,
)
from .models import Tool
from .descriptions import bridge_description


def _merge_global_defaults(existing: object | None, desired: object) -> object:
    """Add software defaults without overwriting administrator-owned values."""

    merged: dict[str, object] = {}
    if isinstance(existing, Mapping):
        existing_mapping = cast(Mapping[object, object], existing)
        merged.update({str(name): value for name, value in existing_mapping.items()})
    if isinstance(desired, Mapping):
        desired_mapping = cast(Mapping[object, object], desired)
        for name, value in desired_mapping.items():
            merged.setdefault(str(name), value)
    return merged


async def _tool_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    existing_codes = set((await session.scalars(select(Tool.code))).all())
    for raw in mandatory_tool_rows():
        row = dict(raw)
        messenger_config = row.get("messenger_config")
        if messenger_config is None:
            # Absence means "not owned by this source". An administrator or a
            # previously installed integration may legitimately own this value.
            row.pop("messenger_config", None)
        code = str(row["code"])
        if code in SYSTEM_TOOL_CODES or code not in existing_codes:
            row["conversation_enabled"] = (
                code in SYSTEM_TOOL_CODES
                or code in DEFAULT_CONVERSATION_TOOL_CODES
                # Mail remains opt-in even though it provides a messaging transport.
                or (messenger_config is not None and code != "mail")
            )
        else:
            # Omit administrator-owned values entirely, including during concurrent edits.
            row.pop("conversation_enabled", None)
        rows.append(row)
    return tuple(rows)


async def _connection_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    tool_rows = (
        await session.execute(
            select(Tool.id, Tool.code).where(Tool.code.in_(AUTO_CONNECTED_INTEGRATED_TOOL_CODES))
        )
    ).all()
    agent_query = Agent.histo_filter(select(Agent.id))
    agent_ids = tuple(int(value) for value in (await session.scalars(agent_query)).all())
    existing = set((await session.execute(select(Connection.tool_id, Connection.agent_id))).all())
    return tuple(
        {
            "tool_id": int(tool_id),
            "agent_id": agent_id,
            **(
                {
                    "active": str(tool_code) in SYSTEM_TOOL_CODES
                    or str(tool_code) in DEFAULT_ACTIVE_INTEGRATED_TOOL_CODES
                }
                if str(tool_code) in SYSTEM_TOOL_CODES or (int(tool_id), agent_id) not in existing
                else {}
            ),
        }
        for tool_id, tool_code in tool_rows
        for agent_id in agent_ids
    )


async def _bridge_description_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for tool in (await session.scalars(select(Tool))).all():
        previous_default = bridge_description(
            tool.messenger_config,
            tool.file_share_config,
            overview_only=True,
        )
        if tool.description and tool.description.strip() and tool.description != previous_default:
            continue
        description = bridge_description(tool.messenger_config, tool.file_share_config)
        if description:
            rows.append({"code": tool.code, "description": description})
    return tuple(rows)


def datasets(*, agent_id: int | None = None) -> tuple[DbAdminDataset, ...]:
    """Compile the Tool datasets; ``agent_id`` scopes runtime connection repair."""

    connection_rows = _connection_rows
    if agent_id is not None:

        async def scoped_connection_rows(
            session: AsyncSession,
        ) -> tuple[dict[str, object], ...]:
            rows = await _connection_rows(session)
            return tuple(row for row in rows if row["agent_id"] == agent_id)

        connection_rows = scoped_connection_rows

    return (
        DbAdminDataset(
            key="app.tools.mandatory.tools",
            table=cast(Table, Tool.__table__),
            natural_key=("code",),
            rows=_tool_rows,
            update_columns=(
                "label",
                "description",
                "can_disable",
                "conversation_enabled",
                "mcp_config",
                "file_share_config",
                "messenger_config",
                "listener_config",
                "connection_schema",
                "global_params",
                "task_config",
            ),
            column_mergers={"global_params": _merge_global_defaults},
            depends_on=("core.params.declarations",),
        ),
        DbAdminDataset(
            key="app.tools.mandatory.connections",
            table=cast(Table, Connection.__table__),
            natural_key=("tool_id", "agent_id"),
            rows=connection_rows,
            # Optional activation remains administrator-owned; system services converge active.
            update_columns=("active",),
            depends_on=("app.tools.mandatory.tools",),
        ),
        DbAdminDataset(
            key="app.tools.bridge_descriptions",
            table=cast(Table, Tool.__table__),
            natural_key=("code",),
            rows=_bridge_description_rows,
            update_columns=("description",),
            depends_on=("app.tools.mandatory.tools",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.tools", factory=datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
