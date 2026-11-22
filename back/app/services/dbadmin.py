"""Programmatic datasets for built-in services and their default connections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection
from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminReconciler, DbAdminRegistry

from .mandatory_services import (
    AUTO_CONNECTED_INTEGRATED_SERVICE_CODES,
    DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES,
    mandatory_service_rows,
    SYSTEM_SERVICE_CODES,
)
from .models import Service
from .descriptions import bridge_description
from .contracts import FILE_INDEXING_PARAM


def _legacy_indexing_defaults(record: Service, schema: dict[str, object]) -> dict[str, object]:
    from .service import default_global_params

    defaults: dict[str, object] = dict(default_global_params(schema))
    if FILE_INDEXING_PARAM in defaults and FILE_INDEXING_PARAM not in (record.global_params or {}):
        defaults[FILE_INDEXING_PARAM] = {"value": record.file_indexing_mode or "excluded", "forced": False}
    return defaults


async def _reconcile_standard_params(session: AsyncSession) -> None:
    for record in await session.scalars(select(Service)):
        from .service import connection_schema_for_service
        schema = connection_schema_for_service(record)
        if schema != record.connection_schema:
            record.connection_schema = schema
        defaults = _legacy_indexing_defaults(record, schema)
        merged = _merge_global_defaults(record.global_params, defaults)
        if merged != record.global_params:
            record.global_params = cast(dict[str, object], merged)
    await session.flush()


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


async def _service_name_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    """Rename the installed administrative Service without changing its identity.

    The primary key is deliberately used for this dataset: the code itself is
    being renamed, while connections, function policies and credentials refer
    to the existing Service identity.
    """
    legacy = await session.scalar(select(Service).where(Service.code == "galaris_admin"))
    if legacy is None:
        return ()
    target = await session.scalar(select(Service.id).where(Service.code == "platform_admin"))
    if target is not None:
        raise ValueError("Cannot rename the legacy administration Service: platform_admin already exists")
    return ({"id": legacy.id, "code": "platform_admin", "label": "Administration"},)


async def _service_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    # The preceding naming dataset updates the table directly. Refresh any Service
    # already present in this session before deriving administrator-owned defaults.
    existing = {
        record.code: record
        for record in await session.scalars(select(Service).execution_options(populate_existing=True))
    }
    for raw in mandatory_service_rows():
        row = dict(raw)
        messenger_config = row.get("messenger_config")
        if messenger_config is None:
            # Absence means "not owned by this source". An administrator or a
            # previously installed integration may legitimately own this value.
            row.pop("messenger_config", None)
        code = str(row["code"])
        if code in existing:
            row["global_params"] = _legacy_indexing_defaults(existing[code], cast(dict[str, object], row["connection_schema"]))
        rows.append(row)
    return tuple(rows)


async def _connection_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    tool_rows = (
        await session.execute(
            select(Service.id, Service.code).where(Service.code.in_(AUTO_CONNECTED_INTEGRATED_SERVICE_CODES))
        )
    ).all()
    agent_query = Agent.histo_filter(select(Agent.id))
    agent_ids = tuple(int(value) for value in (await session.scalars(agent_query)).all())
    existing = set((await session.execute(select(Connection.service_id, Connection.agent_id))).all())
    return tuple(
        {
            "service_id": int(service_id),
            "agent_id": agent_id,
            **(
                {
                    "active": str(service_code) in SYSTEM_SERVICE_CODES
                    or str(service_code) in DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES
                }
                if str(service_code) in SYSTEM_SERVICE_CODES or (int(service_id), agent_id) not in existing
                else {}
            ),
        }
        for service_id, service_code in tool_rows
        for agent_id in agent_ids
    )


async def _bridge_description_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for tool in (await session.scalars(select(Service))).all():
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
    """Compile the Service datasets; ``agent_id`` scopes runtime connection repair."""

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
            key="app.services.builtin_names",
            table=cast(Table, Service.__table__),
            natural_key=("id",),
            rows=_service_name_rows,
            update_columns=("code", "label"),
        ),
        DbAdminDataset(
            key="app.services.mandatory.services",
            table=cast(Table, Service.__table__),
            natural_key=("code",),
            rows=_service_rows,
            update_columns=(
                "label",
                "description",
                "capabilities",
                "can_disable",
                "mcp_config",
                "file_share_config",
                "messenger_config",
                "listener_config",
                "connection_schema",
                "global_params",
                "task_config",
            ),
            column_mergers={"global_params": _merge_global_defaults},
            depends_on=("core.params.declarations", "app.services.builtin_names"),
        ),
        DbAdminDataset(
            key="app.services.mandatory.connections",
            table=cast(Table, Connection.__table__),
            natural_key=("service_id", "agent_id"),
            rows=connection_rows,
            # Optional activation remains administrator-owned; system services converge active.
            update_columns=("active",),
            depends_on=("app.services.mandatory.services",),
        ),
        DbAdminDataset(
            key="app.services.bridge_descriptions",
            table=cast(Table, Service.__table__),
            natural_key=("code",),
            rows=_bridge_description_rows,
            update_columns=("description",),
            depends_on=("app.services.mandatory.services",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.services", factory=datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    from .naming_migration import register_naming_migration
    register_naming_migration(registry)
    from .capability_migration import register_capability_migration
    register_capability_migration(registry)
    from .protocol_migration import register_protocol_migration
    register_protocol_migration(registry)
    registry.register_data_source(DATA_SOURCE)
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.standard_params", handler=_reconcile_standard_params,
        depends_on=("app.services.mandatory.services",),
    ))
