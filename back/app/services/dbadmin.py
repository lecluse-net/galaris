"""Programmatic datasets for built-in services and their default connections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Select, Table, case, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection, ConnectionFunctionState, ConnectionParam, ServiceFunctionState
from app.connection.facade import services_with_mcp_oauth_grants
from core.dbadmin import DbAdminAction, DbAdminDataSource, DbAdminDataset, DbAdminPhase, DbAdminReconciler, DbAdminRegistry, SchemaTransitionSet

from .mandatory_services import (
    AGENT_DISCOVERY_TOOLS,
    AUTO_CONNECTED_INTEGRATED_SERVICE_CODES,
    CONTACT_TOOLS, TASK_TOOLS, DOCUMENT_ANALYSIS_TOOLS, CONVERSATION_TASK_TOOLS, CONVERSATION_PROCESS_TOOLS,
    DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES,
    GOAL_SELF_SERVICE_TOOLS,
    PROCESS_SELF_SERVICE_TOOLS,
    SERVICE_DISCOVERY_TOOLS,
    mandatory_service_rows,
    SYSTEM_SERVICE_CODES,
)
from .models import Service
from .descriptions import bridge_description
from .contracts import FILE_INDEXING_PARAM, MANAGEMENT_SCOPE_PARAM
from .secrets import MCP_AUTH_MODE_EXPLICIT


def _legacy_services_with_mcp_oauth() -> Select[tuple[Service]]:
    return select(Service).where(
        Service.id.in_(services_with_mcp_oauth_grants()),
        Service.mcp_config["type"].astext.in_(("http", "sse")),
        Service.mcp_config[MCP_AUTH_MODE_EXPLICIT].as_boolean().is_not(True),
        Service.mcp_config["auth"]["type"].astext.is_distinct_from("oauth"),
    )


async def _mcp_auth_modes_migrated(session: AsyncSession, _: SchemaTransitionSet) -> bool:
    return await session.scalar(_legacy_services_with_mcp_oauth().with_only_columns(Service.id).limit(1)) is None


async def _migrate_mcp_auth_modes(session: AsyncSession, _: SchemaTransitionSet) -> None:
    for record in await session.scalars(_legacy_services_with_mcp_oauth().with_for_update()):
        config = record.mcp_config or {}
        auth = cast(dict[str, object], config.get("auth") or {})
        record.mcp_config = {**config, "auth": {**auth, "type": "oauth"}, MCP_AUTH_MODE_EXPLICIT: True}
    await session.flush()


def _legacy_indexing_defaults(record: Service, schema: dict[str, object]) -> dict[str, object]:
    from .service import default_global_params

    defaults: dict[str, object] = dict(default_global_params(schema))
    mail_only = record.mail_config is not None and (not record.file_share_config or record.file_share_config.get("service") == "mail")
    # Mail previously had no indexing preference. Its old column default did not express a user choice.
    if not mail_only and FILE_INDEXING_PARAM in defaults and FILE_INDEXING_PARAM not in (record.global_params or {}):
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
    """Rename installed Services without changing their identities.

    The primary key is deliberately used for this dataset: the code itself is
    being renamed, while connections, function policies and credentials refer
    to the existing Service identity.
    """
    rows: list[dict[str, object]] = []
    for old_code, code, label in (
        ("agenda", "calendar", "Agenda"),
        ("galaris_admin", "platform_admin", "Administration"),
        ("process_admin", "process", "Processes"),
        ("goal_management", "goal", "Goals"),
        ("agent_admin", "agent", "Agent"),
        ("service_admin", "service", "Services"),
    ):
        legacy = await session.scalar(select(Service.id).where(Service.code == old_code))
        if legacy is None:
            continue
        if await session.scalar(select(Service.id).where(Service.code == code)) is not None:
            raise ValueError(f"Cannot rename the {old_code} Service: {code} already exists")
        rows.append({"id": legacy, "code": code, "label": label})
    return tuple(rows)


async def _legacy_calendar_provider_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    """Free the Calendar code without replacing a historical external provider."""
    provider = await session.scalar(select(Service).where(Service.code == "calendar", Service.can_disable.is_(True)))
    if provider is None:
        return ()
    used = set(await session.scalars(select(Service.code).where(Service.code.like("calendar-provider%"))))
    code = "calendar-provider"
    suffix = 2
    while code in used:
        code = f"calendar-provider-{suffix}"
        suffix += 1
    return ({"id": provider.id, "code": code},)


async def _legacy_default_connection_rows(session: AsyncSession) -> tuple[dict[str, object], ...]:
    """Activate previously default-inactive connections before the Service is renamed."""
    has_scope_override = (
        select(ConnectionParam.id).where(
            ConnectionParam.connection_id == Connection.id,
            ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM,
            ConnectionParam.param_value.is_not(None),
        ).exists()
    )
    ids = await session.scalars(select(Connection.id).join(Service).join(Agent).where(
        Service.code.in_(("process_admin", "goal_management", "agent_admin", "service_admin")),
        Connection.active.is_(False),
        Agent.deleted_at.is_(None), ~has_scope_override,
    ))
    return tuple({"id": identity, "active": True} for identity in ids)


async def move_galaris_function_policies(session: AsyncSession) -> None:
    """Move policies with the relocated tools and preserve destination overrides."""
    from .legacy_names import BUILTIN_TOOL_RENAMES
    transfers = {
        "agent": AGENT_DISCOVERY_TOOLS, "service": SERVICE_DISCOVERY_TOOLS,
        "goal": GOAL_SELF_SERVICE_TOOLS, "process": PROCESS_SELF_SERVICE_TOOLS,
        "contact": CONTACT_TOOLS, "task": (*TASK_TOOLS, "task_stop", "task_work_update"), "document": DOCUMENT_ANALYSIS_TOOLS,
    }
    moves = {"galaris": transfers, "conversation": {
        "document": ("document_show",),
        "task": (*CONVERSATION_TASK_TOOLS, "task_retry", "task_submit", "task_status", "task_stop_conversation", *BUILTIN_TOOL_RENAMES["task"]),
        "process": (*CONVERSATION_PROCESS_TOOLS, *BUILTIN_TOOL_RENAMES["process"]),
    }}
    from .builtin_merge import rebind_action_history
    ids = dict((await session.execute(select(Service.code, Service.id).where(
        Service.code.in_(("galaris", "conversation", *transfers)),
    ).order_by(Service.id).with_for_update())).tuples().all())
    for source, targets in moves.items():
        if source not in ids:
            continue
        for code, names in targets.items():
            if code not in ids:
                continue
            await move_function_policies(session, ids[source], ids[code], f"{source} and {code}", names)
        destinations = {(row.service_id, row.agent_id): row for row in await session.scalars(select(Connection).where(
            Connection.service_id.in_({ids[code] for code in targets if code in ids}), Connection.singleton_key == 0,
        ))}
        await rebind_action_history(session, ids[source],
            {name: ids[code] for code, names in targets.items() if code in ids for name in names}, destinations)


async def move_function_policies(
    session: AsyncSession, origin: int, destination: int, description: str, names: tuple[str, ...],
) -> None:
    # Archived agents may have stored function rules without a destination connection.
    agent_alias = Connection.__table__.alias("destination_agent")
    configured = select(Connection.agent_id).join(ConnectionFunctionState).where(
        Connection.service_id == origin, ConnectionFunctionState.capability_kind == "tool",
        ConnectionFunctionState.function_name.in_(names),
        ~select(agent_alias.c.id).where(agent_alias.c.agent_id == Connection.agent_id,
            agent_alias.c.service_id == destination, agent_alias.c.singleton_key == 0).exists(),
    ).distinct()
    session.add_all(Connection(service_id=destination, agent_id=agent_id, active=False)
                    for agent_id in await session.scalars(configured))
    await session.flush()
    connections = cast(Table, Connection.__table__)
    recipients = connections.alias("recipient_connections")
    for model, reference in ((ServiceFunctionState, "service_id"), (ConnectionFunctionState, "connection_id")):
        states = cast(Table, model.__table__)
        matches = states.c.function_name.in_(names) & (states.c.capability_kind == "tool")
        source = states
        if model is ServiceFunctionState:
            target = literal(destination)
            matches = matches & (states.c.service_id == origin)
        else:
            source = states.join(connections, connections.c.id == states.c.connection_id).join(
                recipients, (recipients.c.agent_id == connections.c.agent_id)
                & (recipients.c.service_id == destination) & (recipients.c.singleton_key == 0),
            )
            target = recipients.c.id
            matches = matches & (connections.c.service_id == origin)
        columns = (reference, "function_name", "capability_kind", "enabled", "state")
        targets = select(states.c.id, target.label(reference)).select_from(source).where(matches).cte()
        moved = delete(states).where(states.c.id == targets.c.id).returning(
            targets.c[reference], states.c.function_name, states.c.capability_kind, states.c.enabled, states.c.state,
        ).cte()
        transplant = insert(states).from_select(columns, select(moved))
        current_state = func.coalesce(states.c.state, case((states.c.enabled, "enabled"), else_="disabled"))
        incoming_state = func.coalesce(transplant.excluded.state,
            case((transplant.excluded.enabled, "enabled"), else_="disabled"))
        # PostgreSQL returns no row for a conflicting policy. Roll the entire
        # move back in that case, including the delete from the original Service.
        retained = transplant.on_conflict_do_update(
            index_elements=(reference, "function_name", "capability_kind"),
            set_={"state": states.c.state}, where=current_state == incoming_state,
        ).returning(states.c.id).cte()
        conflict = await session.scalar(select(
            select(func.count()).select_from(moved).scalar_subquery()
            != select(func.count()).select_from(retained).scalar_subquery(),
        ))
        if conflict:
            raise ValueError(f"Conflicting {reference} function policies between {description}")


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
            if code in {"contact", "task"} and existing[code].can_disable:
                raise ValueError(f"Cannot install the mandatory {code} Service over an existing custom Service")
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
    legacy_conversation = await session.scalar(select(Service.id).where(Service.code == "conversation"))
    # The merge reads the old per-agent Chat activation before making Chat mandatory.
    mandatory_codes = SYSTEM_SERVICE_CODES - {"chat"} if legacy_conversation is not None else SYSTEM_SERVICE_CODES
    return tuple(
        {
            "service_id": int(service_id),
            "agent_id": agent_id,
            **(
                {
                    "active": str(service_code) in SYSTEM_SERVICE_CODES
                    or str(service_code) in DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES
                }
                if str(service_code) in mandatory_codes or (int(service_id), agent_id) not in existing
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
            key="app.services.legacy_default_connections",
            table=cast(Table, Connection.__table__),
            natural_key=("id",),
            rows=_legacy_default_connection_rows,
            update_columns=("active",),
        ),
        DbAdminDataset(
            key="app.services.legacy_calendar_provider",
            table=cast(Table, Service.__table__),
            natural_key=("id",),
            rows=_legacy_calendar_provider_rows,
            update_columns=("code",),
        ),
        DbAdminDataset(
            key="app.services.builtin_names",
            table=cast(Table, Service.__table__),
            natural_key=("id",),
            rows=_service_name_rows,
            update_columns=("code", "label"),
            depends_on=("app.services.legacy_default_connections", "app.services.legacy_calendar_provider"),
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
    from .builtin_merge import (
        merge_builtin_services, merge_conversation_into_chat, merge_media_and_search_services,
        rename_chat_tools, rename_domain_tools,
    )
    from .naming_migration import register_naming_migration
    register_naming_migration(registry)
    from .capability_migration import register_capability_migration
    register_capability_migration(registry)
    from .protocol_migration import register_protocol_migration
    register_protocol_migration(registry)
    registry.register_data_source(DATA_SOURCE)
    registry.register_action(DbAdminAction(
        key="app.services.explicit_mcp_oauth", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="preserve-existing-mcp-grants",
        predicate=lambda _: True, handler=_migrate_mcp_auth_modes, postcondition=_mcp_auth_modes_migrated,
        requires_schema=frozenset({"services.mcp_config", "connections.service_id", "connection_oauth.grant"}),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.galaris_function_policies", handler=move_galaris_function_policies,
        depends_on=("app.services.mandatory.connections",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.merge_builtin_services", handler=merge_builtin_services,
        depends_on=("app.services.mandatory.connections",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.merge_conversation_into_chat", handler=merge_conversation_into_chat,
        depends_on=("app.services.galaris_function_policies", "app.services.merge_builtin_services"),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.rename_chat_tools", handler=rename_chat_tools,
        depends_on=("app.services.merge_conversation_into_chat",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.rename_domain_tools", handler=rename_domain_tools,
        depends_on=("app.services.rename_chat_tools",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.merge_media_and_search", handler=merge_media_and_search_services,
        depends_on=("app.services.mandatory.connections",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.services.standard_params", handler=_reconcile_standard_params,
        depends_on=("app.services.mandatory.services",),
    ))
