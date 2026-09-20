"""Idempotent PostgreSQL ENUM preparation performed before Atlas convergence."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..contracts import DbAdminFatalError, EnumTransition
from ..registry import DbAdminRegistry


@dataclass(frozen=True, slots=True)
class EnumColumn:
    table_name: str
    column_name: str


def validate_enum_transitions(
    transitions: tuple[EnumTransition, ...],
    registry: DbAdminRegistry,
) -> None:
    """Validate every destructive mapping before the first enum DDL statement."""

    for transition in transitions:
        live_set = set(transition.live_values)
        target_set = set(transition.target_values)
        existing_in_target_order = tuple(
            value for value in transition.target_values if value in live_set
        )
        if live_set <= target_set and existing_in_target_order == transition.live_values:
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


def _quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise DbAdminFatalError("Invalid PostgreSQL identifier in enum transition")
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def _enum_columns(
    connection: AsyncConnection,
    enum_name: str,
) -> tuple[EnumColumn, ...]:
    rows = (
        await connection.execute(
            text(
                "SELECT c.relname, a.attname "
                "FROM pg_attribute AS a "
                "JOIN pg_class AS c ON c.oid = a.attrelid "
                "JOIN pg_namespace AS cn ON cn.oid = c.relnamespace "
                "JOIN pg_type AS t ON t.oid = a.atttypid "
                "JOIN pg_namespace AS tn ON tn.oid = t.typnamespace "
                "WHERE cn.nspname = 'public' AND tn.nspname = 'public' "
                "AND t.typname = :enum_name AND a.attnum > 0 AND NOT a.attisdropped"
            ),
            {"enum_name": enum_name},
        )
    ).all()
    return tuple(EnumColumn(str(table), str(column)) for table, column in rows)


async def _add_labels(
    connection: AsyncConnection,
    transition: EnumTransition,
) -> None:
    current = list(transition.live_values)
    enum_sql = _quote_identifier(transition.name)
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
        await connection.execute(text(statement))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        current.insert(insert_at, value)
        logger.info("DbAdmin added enum label {}.{}", transition.name, value)


async def _replace_enum(
    connection: AsyncConnection,
    transition: EnumTransition,
    registry: DbAdminRegistry,
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

    columns = await _enum_columns(connection, transition.name)
    if not columns:
        raise DbAdminFatalError(
            f"Enum {transition.name!r} has no supported public scalar column dependency"
        )

    suffix = uuid4().hex[:12]
    temporary_name = f"dbadmin_{transition.name}_{suffix}"
    old_name = f"dbadmin_old_{transition.name}_{suffix}"
    values_sql = ", ".join(_quote_literal(value) for value in transition.target_values)
    await connection.execute(
        # DDL assembled exclusively with _quote_identifier/_quote_literal.
        text(f"CREATE TYPE {_quote_identifier(temporary_name)} AS ENUM ({values_sql})")  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
    )
    for column in columns:
        table_sql = _quote_identifier(column.table_name)
        column_sql = _quote_identifier(column.column_name)
        await connection.execute(
            text(f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} DROP DEFAULT")  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        )
        cases = " ".join(
            f"WHEN {_quote_literal(source)} THEN {_quote_literal(destination)}"
            for source, destination in effective.items()
        )
        expression = (
            f"CASE WHEN {column_sql} IS NULL THEN NULL ELSE "
            f"(CASE {column_sql}::text {cases} END)::"
            f"{_quote_identifier(temporary_name)} END"
        )
        await connection.execute(
            text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} TYPE "
                f"{_quote_identifier(temporary_name)} USING ({expression})"
            )
        )
    await connection.execute(
        text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            f"ALTER TYPE {_quote_identifier(transition.name)} "
            f"RENAME TO {_quote_identifier(old_name)}"
        )
    )
    await connection.execute(
        text(  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            f"ALTER TYPE {_quote_identifier(temporary_name)} "
            f"RENAME TO {_quote_identifier(transition.name)}"
        )
    )
    await connection.execute(text(f"DROP TYPE {_quote_identifier(old_name)}"))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
    logger.info("DbAdmin replaced enum {} atomically", transition.name)


async def prepare_enum_transitions(
    connection: AsyncConnection,
    transitions: tuple[EnumTransition, ...],
    registry: DbAdminRegistry,
) -> None:
    """Converge enum labels before Atlas sees their dependent columns/defaults."""

    for transition in transitions:
        live_set = set(transition.live_values)
        target_set = set(transition.target_values)
        existing_in_target_order = tuple(
            value for value in transition.target_values if value in live_set
        )
        if live_set <= target_set and existing_in_target_order == transition.live_values:
            await _add_labels(connection, transition)
        else:
            await _replace_enum(connection, transition, registry)
