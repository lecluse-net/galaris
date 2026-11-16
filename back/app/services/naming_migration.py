"""Rename the former Galaris Tool domain in place, preserving row identities."""

import json
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

_TABLES = {"tools": "services", "tool_function_state": "service_function_state",
    "tool_action_authorizations": "service_action_authorizations"}
_COLUMNS = {"tool_id": "service_id", "tool_code": "service_code"}
_PARAMS = {"tools.management_scope": "services.management_scope",
    "tools.fileindexing": "services.fileindexing",
    "tools.file_indexing_mode": "services.file_indexing_mode"}


def needs_service_names(transitions: SchemaTransitionSet) -> bool:
    return bool(set(_TABLES) & transitions.removed_tables) or any(
        key.rsplit(".", 1)[-1] in _COLUMNS for key in transitions.removed_columns)


async def _tables(session: AsyncSession) -> set[str]:
    return set(await session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))


async def _columns(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(text("SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name IN ('tool_id','tool_code')"))
    return [(str(row[0]), str(row[1])) for row in rows]


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _schema_name(name: str) -> str:
    renamed = name
    for old, new in _TABLES.items():
        renamed = renamed.replace(old + "_", new + "_")
    renamed = renamed.replace("_tool_id", "_service_id").replace("_tool_code", "_service_code")
    return {"uq_connection_agent_tool": "uq_connection_agent_service",
        "uq_tool_function": "uq_service_function", "ck_tool_function_state": "ck_service_function_state",
        "ck_tool_capability_kind": "ck_service_capability_kind"}.get(renamed, renamed)


async def _rename_constraints_and_indexes(session: AsyncSession) -> None:
    # Rename metadata in place: rebuilding foreign keys or large indexes just
    # for their names would scan/lock unrelated conversation and Process data.
    constraints = (await session.execute(text("SELECT t.relname,c.conname FROM pg_constraint c "
        "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname='public' ORDER BY t.relname,c.conname"))).all()
    for table, name in constraints:
        target = _schema_name(str(name))
        if target != name:
            # Catalog identifiers and the derived target are double-quoted with embedded quotes escaped.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"ALTER TABLE public.{_quote(str(table))} RENAME CONSTRAINT {_quote(str(name))} TO {_quote(target)}"))
    # Constraint-backed indexes were already renamed with their constraint.
    for name in await session.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname='public' ORDER BY indexname")):
        target = _schema_name(str(name))
        if target != name:
            # Catalog identifiers and the derived target pass through the same identifier escaping.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"ALTER INDEX public.{_quote(str(name))} RENAME TO {_quote(target)}"))


def _configuration(value: Any) -> Any:
    """Only software-owned keys/codes; never rewrite arbitrary prose or secrets."""
    if isinstance(value, dict):
        return {_PARAMS.get(key, key): _configuration(item) for key, item in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [_configuration(item) for item in cast(list[Any], value)]
    return value


async def rename_services(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    tables = await _tables(session)
    for old, new in _TABLES.items():
        if old not in tables:
            continue
        if new in tables:
            raise ValueError(f"Service rename refused: both {old} and {new} exist")
        # Both identifiers come from the fixed _TABLES mapping and are quoted.
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        await session.execute(text(f"ALTER TABLE public.{_quote(old)} RENAME TO {_quote(new)}"))
        # SERIAL defaults and sequence ownership must retain their current values.
        sequence = await session.scalar(text("SELECT to_regclass(:name)::text"), {"name": f"public.{old}_id_seq"})
        if sequence is not None:
            # Sequence names derive only from the fixed _TABLES mapping and are quoted.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"ALTER SEQUENCE public.{_quote(old + '_id_seq')} RENAME TO {_quote(new + '_id_seq')}"))
        tables.remove(old)
        tables.add(new)
    for table, old in await _columns(session):
        new = _COLUMNS[old]
        exists = await session.scalar(text("SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=:table AND column_name=:column"), {"table": table, "column": new})
        if exists:
            raise ValueError("Service rename refused: both legacy and destination columns exist")
        # Catalog table names and allowlisted column names are escaped as SQL identifiers.
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        await session.execute(text(f"ALTER TABLE public.{_quote(table)} RENAME COLUMN {_quote(old)} TO {_quote(new)}"))
    await _rename_constraints_and_indexes(session)
    if "services" in tables:
        collision = await session.scalar(text("SELECT count(*) FROM public.services WHERE code IN ('tool_admin','service_admin')"))
        if int(collision or 0) > 1:
            raise ValueError("Service administration identity collision")
        await session.execute(text("UPDATE public.services SET code='service_admin', label='ServiceAdmin' WHERE code='tool_admin'"))
        rows = await session.execute(text("SELECT id, connection_schema, global_params FROM public.services"))
        for row in rows:
            schema, params = _configuration(row[1]), _configuration(row[2])
            if schema != row[1] or params != row[2]:
                await session.execute(text("UPDATE public.services SET connection_schema=CAST(:schema AS jsonb), "
                    "global_params=CAST(:params AS jsonb) WHERE id=:id"),
                    {"schema": json.dumps(schema), "params": json.dumps(params), "id": row[0]})
    if "connection_params" in tables:
        for old, new in _PARAMS.items():
            conflict = await session.scalar(text("SELECT 1 FROM public.connection_params a JOIN public.connection_params b "
                "ON a.connection_id=b.connection_id WHERE a.param_name=:old AND b.param_name=:new LIMIT 1"), {"old": old, "new": new})
            if conflict:
                raise ValueError("Service parameter naming collision")
            await session.execute(text("UPDATE public.connection_params SET param_name=:new WHERE param_name=:old"), {"old": old, "new": new})
    for table in ("service_function_state", "connection_function_state"):
        if table in tables:
            # Only the two fixed table names above are interpolated, with identifier escaping.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"UPDATE public.{_quote(table)} SET function_name='service_admin' || substr(function_name,11) "
                "WHERE function_name LIKE 'tool\\_admin\\_%' ESCAPE '\\'"))
            # The table is allowlisted and quoted; all values are fixed SQL literals.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"UPDATE public.{_quote(table)} SET function_name='services_list' WHERE function_name='tools_list'"))
            # The table is allowlisted and quoted; all values are fixed SQL literals.
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            await session.execute(text(f"UPDATE public.{_quote(table)} SET function_name='agent_service_list' WHERE function_name='agent_tool_list'"))
    if "privileges" in tables:
        for old, new in (("TOOL_ACCESS", "SERVICE_ACCESS"), ("TOOL_EDIT", "SERVICE_EDIT")):
            collision = await session.scalar(text("SELECT 1 FROM public.privileges WHERE code=:new"), {"new": new})
            if collision and await session.scalar(text("SELECT 1 FROM public.privileges WHERE code=:old"), {"old": old}):
                raise ValueError("Service privilege naming collision")
            await session.execute(text("UPDATE public.privileges SET code=:new WHERE code=:old"), {"old": old, "new": new})
    if "privilege_list_defaults" in tables:
        collision = await session.scalar(text("SELECT count(*) FROM public.privilege_list_defaults WHERE code IN ('toolsSkills','servicesSkills')"))
        if int(collision or 0) > 1:
            raise ValueError("Service privilege category naming collision")
        await session.execute(text("UPDATE public.privilege_list_defaults SET code='servicesSkills' WHERE code='toolsSkills'"))
    if "privilege_lists" in tables:
        await session.execute(text("UPDATE public.privilege_lists SET translation_key='authorize.privilegeLists.defaults.servicesSkills' "
            "WHERE translation_key='authorize.privilegeLists.defaults.toolsSkills'"))
        await session.execute(text("UPDATE public.privilege_lists SET display_name='authorize.privilegeLists.defaults.servicesSkills' "
            "WHERE display_name='authorize.privilegeLists.defaults.toolsSkills'"))
    # An approval is bound to exact function/configuration fingerprints. Preserve
    # its audit evidence, but never reinterpret a pending approval after a rename.
    if "service_action_authorizations" in tables:
        await session.execute(text("UPDATE public.service_action_authorizations SET status='invalidated' "
            "WHERE status IN ('pending','approved')"))


async def service_names_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    tables = await _tables(session)
    return not (set(_TABLES) & tables) and not await _columns(session)


def register_naming_migration(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.services.rename_domain", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="service-identities-parameters-policies-v1", predicate=needs_service_names,
        handler=rename_services, postcondition=service_names_complete))
