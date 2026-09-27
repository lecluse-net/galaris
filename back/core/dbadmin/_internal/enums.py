"""Idempotent PostgreSQL ENUM preparation performed before Atlas convergence."""

from __future__ import annotations

from uuid import uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..contracts import DbAdminFatalError, EnumTransition
from ..registry import DbAdminRegistry
from .enum_catalog import EnumReplacement, inspect_replacement


def _additive(transition: EnumTransition) -> bool:
    live = set(transition.live_values)
    return live <= set(transition.target_values) and tuple(
        value for value in transition.target_values if value in live
    ) == transition.live_values


def validate_enum_transitions(
    transitions: tuple[EnumTransition, ...],
    registry: DbAdminRegistry,
) -> None:
    """Validate every destructive mapping before the first enum DDL statement."""

    for transition in transitions:
        if not transition.target_values or len(set(transition.target_values)) != len(transition.target_values):
            raise DbAdminFatalError(f"Enum {transition.name!r} must have nonempty, distinct target labels")
        if any("\x00" in value or len(value.encode("utf-8")) > 63 for value in transition.target_values):
            raise DbAdminFatalError(f"Enum {transition.name!r} has an invalid target label (NUL or more than 63 bytes)")
        target_set = set(transition.target_values)
        if _additive(transition):
            continue
        mapping_config = registry.enum_mapping(transition.name)
        mapping = dict(mapping_config.values) if mapping_config is not None else {}
        missing = [
            value
            for value in transition.live_values
            if mapping.get(value, value) not in target_set
        ]
        if missing:
            raise DbAdminFatalError(
                f"Enum {transition.name!r} has no total mapping for: "
                + ", ".join(repr(value) for value in missing)
            )


async def validate_enum_ownership(
    connection: AsyncConnection,
    transitions: tuple[EnumTransition, ...],
) -> None:
    """Reject unavailable ALTER TYPE rights before any upgrade action can commit.

    Type USAGE grants do not confer ownership. PostgreSQL's role USAGE check
    includes inherited owner privileges and superusers, but not SET-only membership.
    """

    if not transitions:
        return
    rows = (await connection.execute(text(
        "SELECT current_user AS actor, t.typname, pg_get_userbyid(t.typowner) AS owner, "
        "pg_has_role(current_user, t.typowner, 'USAGE') AS can_alter "
        "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'public' AND t.typtype = 'e' "
        "AND t.typname = ANY(CAST(:names AS text[])) ORDER BY t.typname"
    ), {"names": [transition.name for transition in transitions]})).all()
    found = {str(row.typname) for row in rows}
    missing = sorted({transition.name for transition in transitions} - found)
    if missing:
        raise DbAdminFatalError(
            "Enum ownership preflight failed: public enum disappeared after inspection: "
            + ", ".join(missing)
        )
    denied = [
        f"role {row.actor!r} cannot alter enum public.{row.typname} owned by {row.owner!r}"
        for row in rows if not row.can_alter
    ]
    if denied:
        raise DbAdminFatalError(
            "Enum ownership preflight failed: " + "; ".join(denied)
            + ". ALTER TYPE requires ownership, including inherited owner privileges "
            "or a superuser. Ask a PostgreSQL administrator to correct the enum ownership "
            "or the migration role's inherited privileges before retrying. "
            "Granting USAGE on the type alone is insufficient."
        )


def _quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise DbAdminFatalError("Invalid PostgreSQL identifier in enum transition")
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _public(name: str) -> str:
    return f'"public".{_quote_identifier(name)}'


async def validate_enum_preflight(
    connection: AsyncConnection, transitions: tuple[EnumTransition, ...], registry: DbAdminRegistry,
) -> dict[str, EnumReplacement | None]:
    """Admit the whole batch before any action; None means an additive change."""

    validate_enum_transitions(transitions, registry)
    await validate_enum_ownership(connection, transitions)
    plans: dict[str, EnumReplacement | None] = {}
    for transition in transitions:
        labels = tuple((await connection.execute(text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
            "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' "
            "AND t.typname=:name ORDER BY e.enumsortorder"
        ), {"name": transition.name})).scalars())
        if labels == transition.target_values:
            continue  # Replaying a committed batch is harmless.
        if labels != transition.live_values:
            raise DbAdminFatalError(f"Enum public.{transition.name} changed since inspection; recompute the upgrade plan")
        if _additive(transition):
            plans[transition.name] = None
        else:
            config = registry.enum_mapping(transition.name)
            mapping = config.values if config is not None else {}
            destinations = [mapping.get(value, value) for value in transition.live_values]
            plans[transition.name] = await inspect_replacement(
                connection, transition, injective=len(set(destinations)) == len(destinations),
            )
    return plans


async def _add_labels(
    connection: AsyncConnection,
    transition: EnumTransition,
) -> None:
    current = list(transition.live_values)
    enum_sql = _public(transition.name)
    for index, value in enumerate(transition.target_values):
        if value in current:
            continue
        next_existing = next(
            (candidate for candidate in transition.target_values[index + 1 :] if candidate in current),
            None,
        )
        previous_existing = next(
            (candidate for candidate in reversed(transition.target_values[:index]) if candidate in current),
            None,
        )
        position = ""
        insert_at = len(current)
        if next_existing is not None:
            position = f" BEFORE {_quote_literal(next_existing)}"
            insert_at = current.index(next_existing)
        elif previous_existing is not None:
            position = f" AFTER {_quote_literal(previous_existing)}"
            insert_at = current.index(previous_existing) + 1
        statement = (
            f"ALTER TYPE {enum_sql} ADD VALUE IF NOT EXISTS "
            f"{_quote_literal(value)}{position}"
        )
        # All identifiers/literals are quoted above; DDL cannot bind enum labels.
        await connection.exec_driver_sql(statement)
        current.insert(insert_at, value)
        logger.info("DbAdmin added enum label {}.{}", transition.name, value)


async def _replace_enum(
    connection: AsyncConnection,
    transition: EnumTransition,
    registry: DbAdminRegistry,
    plan: EnumReplacement,
) -> None:
    mapping_config = registry.enum_mapping(transition.name)
    mapping = dict(mapping_config.values) if mapping_config is not None else {}
    target_set = set(transition.target_values)
    effective: dict[str, str] = {}
    for value in transition.live_values:
        destination = mapping.get(value, value)
        if destination not in target_set:
            raise DbAdminFatalError(
                f"Enum {transition.name!r} removes {value!r} without a total mapping"
            )
        effective[value] = destination

    # Never concatenate a potentially 63-byte user identifier: PostgreSQL would
    # truncate the random suffix and may collide with another type or its array.
    suffix = uuid4().hex
    temporary_name = f"dbadmin_enum_{suffix}"
    old_name = f"dbadmin_old_{suffix}"
    values_sql = ", ".join(_quote_literal(value) for value in transition.target_values)
    # exec_driver_sql keeps colon-bearing labels from becoming SQLAlchemy binds.
    # All interpolated identifiers and literals are quoted by the helpers above.
    await connection.exec_driver_sql(f"CREATE TYPE {_public(temporary_name)} AS ENUM ({values_sql})")
    for column in plan.columns:
        table_sql = _public(column.table_name)
        column_sql = _quote_identifier(column.column_name)
        await connection.exec_driver_sql(f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} DROP DEFAULT")
        cases = " ".join(
            f"WHEN {_quote_literal(source)} THEN {_quote_literal(destination)}"
            for source, destination in effective.items()
        )
        expression = (
            f"CASE WHEN {column_sql} IS NULL THEN NULL ELSE "
            f"(CASE {column_sql}::text {cases} ELSE {column_sql}::text END)::"
            f"{_public(temporary_name)} END"
        )
        await connection.exec_driver_sql(
            f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} TYPE "
            f"{_public(temporary_name)} USING ({expression})"
        )
    await connection.exec_driver_sql(
        f"ALTER TYPE {_public(transition.name)} "
        f"RENAME TO {_quote_identifier(old_name)}"
    )
    await connection.exec_driver_sql(
        f"ALTER TYPE {_public(temporary_name)} "
        f"RENAME TO {_quote_identifier(transition.name)}"
    )
    await connection.exec_driver_sql(f"DROP TYPE {_public(old_name)}")
    enum_sql = _public(transition.name)
    for column in plan.columns:
        if column.has_default:
            value = column.default_value
            default = "NULL" if value is None else _quote_literal(effective[value])
            await connection.exec_driver_sql(
                f"ALTER TABLE {_public(column.table_name)} ALTER COLUMN {_quote_identifier(column.column_name)} "
                f"SET DEFAULT {default}::{enum_sql}"
            )
    # CREATE TYPE uses the migration role's default ACL; remove it before
    # restoring the old type's grants, including explicit PUBLIC revocations.
    grantees = (await connection.execute(text(
        "SELECT DISTINCT CASE WHEN acl.grantee=0 THEN NULL ELSE pg_get_userbyid(acl.grantee) END "
        "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace, "
        "LATERAL aclexplode(COALESCE(t.typacl,acldefault('T',t.typowner))) acl "
        "WHERE n.nspname='public' AND t.typname=:name"
    ), {"name": transition.name})).scalars().all()
    for grantee in grantees:
        role = "PUBLIC" if grantee is None else _quote_identifier(str(grantee))
        await connection.exec_driver_sql(f"REVOKE ALL ON TYPE {enum_sql} FROM {role}")
    for grant in plan.grants:
        role = "PUBLIC" if grant.role is None else _quote_identifier(grant.role)
        option = " WITH GRANT OPTION" if grant.grant_option else ""
        await connection.exec_driver_sql(f"GRANT USAGE ON TYPE {enum_sql} TO {role}{option}")
    if plan.comment is not None:
        await connection.exec_driver_sql(f"COMMENT ON TYPE {enum_sql} IS {_quote_literal(plan.comment)}")
    await connection.exec_driver_sql(f"ALTER TYPE {enum_sql} OWNER TO {_quote_identifier(plan.owner)}")
    logger.info("DbAdmin prepared enum replacement {} (pending transaction commit)", transition.name)


async def prepare_enum_transitions(
    connection: AsyncConnection,
    transitions: tuple[EnumTransition, ...],
    registry: DbAdminRegistry,
) -> None:
    """Converge enum labels before Atlas sees their dependent columns/defaults."""

    if not transitions:
        return
    # A savepoint makes the whole batch atomic even if the caller catches an
    # error and commits its outer transaction. Connection loss rolls it back too.
    async with connection.begin_nested():
        plans = await validate_enum_preflight(connection, transitions, registry)
        tables = sorted({column.table_name for plan in plans.values() if plan is not None for column in plan.columns})
        for table in tables:
            await connection.exec_driver_sql(f"LOCK TABLE {_public(table)} IN ACCESS EXCLUSIVE MODE")
        if tables:
            plans = await validate_enum_preflight(connection, transitions, registry)
        for transition in transitions:
            if transition.name not in plans:
                continue
            plan = plans[transition.name]
            if plan is None:
                await _add_labels(connection, transition)
            else:
                await _replace_enum(connection, transition, registry, plan)
