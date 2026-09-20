"""PostgreSQL and SQLAlchemy snapshots used to compute safe transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, cast
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Column, DefaultClause, MetaData, inspect, text
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import NullType, TypeEngine
from core.database import Vector
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from .contracts import (
    EnumTransition,
    RequiredColumnTransition,
    SchemaTransitionSet,
    SchemaObjectTransition,
)


@dataclass(frozen=True, slots=True)
class LiveConstraint:
    """PostgreSQL's exact expression, not a guessed semantic SQL equivalence."""

    kind: str
    definition: str
    validated: bool


@dataclass(frozen=True, slots=True)
class LiveTable:
    name: str
    columns: frozenset[str]
    nullable_columns: frozenset[str] = frozenset()
    definitions: dict[tuple[str, str], str] = field(default_factory=lambda: dict[tuple[str, str], str]())
    constraints: dict[str, LiveConstraint] = field(default_factory=lambda: dict[str, LiveConstraint]())


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    """The subset of the live public schema required for DbAdmin decisions."""

    tables: dict[str, LiveTable]
    enums: dict[str, tuple[str, ...]]


def _inspect_tables(connection: Connection) -> dict[str, LiveTable]:
    rows = connection.execute(
        text(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
        )
    ).all()
    columns_by_table: dict[str, set[str]] = {}
    nullable_by_table: dict[str, set[str]] = {}
    for table_name, column_name, is_nullable in rows:
        normalized_table = str(table_name)
        normalized_column = str(column_name)
        columns_by_table.setdefault(normalized_table, set()).add(normalized_column)
        if str(is_nullable) == "YES":
            nullable_by_table.setdefault(normalized_table, set()).add(normalized_column)
    tables = {
        table_name: LiveTable(
            table_name,
            frozenset(columns),
            frozenset(nullable_by_table.get(table_name, set())),
        )
        for table_name, columns in columns_by_table.items()
    }
    inspector = inspect(connection)
    cast(dict[str, type[TypeEngine[Any]]], ischema_names).setdefault("vector", Vector)
    for name, columns in inspector.get_multi_columns(schema="public").items():
        table = tables.get(name[1])
        if table is None:
            continue
        for column in columns:
            if not isinstance(column["type"], NullType):
                table.definitions[("column_type", column["name"])] = str(column["type"].compile(dialect=dialect())).upper()
            if column.get("default") is not None:
                table.definitions[("column_default", column["name"])] = str(column["default"]).strip()
    for name, indexes in inspector.get_multi_indexes(schema="public").items():
        table = tables.get(name[1])
        if table is None:
            continue
        for index in indexes:
            if index.get("duplicates_constraint"):
                continue
            table.definitions[("index", str(index["name"]))] = json.dumps({
                "columns": index.get("column_names"), "unique": bool(index.get("unique")),
                "where": str(index.get("dialect_options", {}).get("postgresql_where") or ""),
                "expressions": index.get("expressions"),
                "sorting": index.get("column_sorting", {}),
                "using": index.get("dialect_options", {}).get("postgresql_using") or "btree",
                "include": index.get("dialect_options", {}).get("postgresql_include") or [],
                "ops": index.get("dialect_options", {}).get("postgresql_ops") or {},
                "with": index.get("dialect_options", {}).get("postgresql_with") or {},
                "nulls_not_distinct": bool(index.get("dialect_options", {}).get("postgresql_nulls_not_distinct")),
            }, sort_keys=True)
    for name, foreign_keys in inspector.get_multi_foreign_keys(schema="public").items():
        table = tables.get(name[1])
        if table is None:
            continue
        for key in foreign_keys:
            table.definitions[("foreign_key", str(key["name"]))] = json.dumps({
                "columns": key["constrained_columns"], "table": key["referred_table"],
                "remote": key["referred_columns"], "options": key.get("options", {}),
            }, sort_keys=True)
    constraints = connection.execute(text(
        "SELECT rel.relname, con.conname, con.contype::text, pg_get_constraintdef(con.oid, true), con.convalidated "
        "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
        "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
        "WHERE ns.nspname = 'public' AND con.contype IN ('c', 'x')"
    ))
    for table_name, name, kind, definition, validated in constraints:
        table = tables.get(str(table_name))
        if table is not None:
            table.constraints[str(name)] = LiveConstraint(
                "check" if kind == "c" else "exclusion", str(definition), bool(validated),
            )
    return tables


async def inspect_public_schema(connection: AsyncConnection) -> SchemaSnapshot:
    """Inspect only ``public``; other schemas are deliberately invisible here."""

    tables = await connection.run_sync(_inspect_tables)
    enum_rows = (
        await connection.execute(
            text(
                "SELECT t.typname, e.enumlabel "
                "FROM pg_type AS t "
                "JOIN pg_enum AS e ON e.enumtypid = t.oid "
                "JOIN pg_namespace AS n ON n.oid = t.typnamespace "
                "WHERE n.nspname = 'public' "
                "ORDER BY t.typname, e.enumsortorder"
            )
        )
    ).all()
    enum_values: dict[str, list[str]] = {}
    for enum_name, enum_value in enum_rows:
        enum_values.setdefault(str(enum_name), []).append(str(enum_value))
    return SchemaSnapshot(
        tables=tables,
        enums={name: tuple(values) for name, values in enum_values.items()},
    )


def target_enum_values(metadata: MetaData) -> dict[str, tuple[str, ...]]:
    """Collect native PostgreSQL enum targets from SQLAlchemy metadata."""

    result: dict[str, tuple[str, ...]] = {}
    for table in metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, SqlEnum) or not column.type.native_enum:
                continue
            if column.type.name is None:
                continue
            name = str(column.type.name)
            values = tuple(str(value) for value in column.type.enums)
            previous = result.setdefault(name, values)
            if previous != values:
                raise ValueError(
                    f"SQLAlchemy enum {name!r} has contradictory declarations"
                )
    return result


def compute_transitions(
    live: SchemaSnapshot,
    target: MetaData,
) -> SchemaTransitionSet:
    """Compare live public objects to the authoritative SQLAlchemy target."""

    target_tables = {
        table.name: table
        for table in target.tables.values()
        if table.schema in {None, "public"}
    }
    live_names = frozenset(live.tables)
    target_names = frozenset(target_tables)
    added_columns: set[str] = set()
    removed_columns: set[str] = set()
    required_columns: list[RequiredColumnTransition] = []
    definitions: list[SchemaObjectTransition] = []

    for table_name in sorted(live_names & target_names):
        live_columns = live.tables[table_name].columns
        table = target_tables[table_name]
        wanted: dict[tuple[str, str], str] = {}
        for column in table.columns:
            wanted[("column_type", column.name)] = str(column.type.compile(dialect=dialect())).upper()
            if isinstance(column.server_default, DefaultClause):
                wanted[("column_default", column.name)] = str(column.server_default.arg).strip()
            elif column.primary_key and column.autoincrement in (True, "auto"):
                # PostgreSQL serial/identity defaults are implicit in the model.
                existing_default = live.tables[table_name].definitions.get(("column_default", column.name))
                if existing_default and existing_default.startswith("nextval("):
                    wanted[("column_default", column.name)] = existing_default
        for index in table.indexes:
            options = index.dialect_options["postgresql"]
            predicate = options.get("where")
            expressions = [expression if isinstance(expression, str) else str(expression.compile(dialect=dialect(), compile_kwargs={"include_table": False, "literal_binds": True})) for expression in index.expressions]
            columns = [expression.name if isinstance(expression, Column) else None for expression in index.expressions]
            wanted[("index", str(index.name))] = json.dumps({
                "columns": columns, "unique": bool(index.unique),
                "where": str(predicate) if predicate is not None else "",
                "expressions": expressions if None in columns else None,
                "sorting": {},
                "using": options.get("using") or "btree",
                "include": options.get("include") or [],
                "ops": options.get("ops") or {},
                "with": {str(key): str(value) for key, value in cast(dict[str, Any], options.get("with") or {}).items()},
                "nulls_not_distinct": bool(options.get("nulls_not_distinct")),
            }, sort_keys=True)
        for key in table.foreign_key_constraints:
            wanted[("foreign_key", str(key.name))] = json.dumps({
                "columns": list(key.column_keys), "table": key.referred_table.name,
                "remote": [element.column.name for element in key.elements],
                "options": {name: value for name, value in {
                    "ondelete": key.ondelete, "onupdate": key.onupdate,
                    "deferrable": key.deferrable, "initially": key.initially,
                }.items() if value is not None},
            }, sort_keys=True)
        observed = live.tables[table_name].definitions
        if observed:
            for kind, name in sorted(observed.keys() | wanted.keys()):
                previous, desired = observed.get((kind, name)), wanted.get((kind, name))
                if kind == "column_type" and previous is None and name in live_columns:
                    continue  # An unrecognized reflected type is not proof of a change.
                if previous != desired:
                    definitions.append(SchemaObjectTransition(table_name, name, kind, previous, desired))
        target_columns = frozenset(column.name for column in table.columns)
        for column_name in sorted(target_columns - live_columns):
            key = f"{table_name}.{column_name}"
            added_columns.add(key)
            column = table.columns[column_name]
            if not column.nullable and column.server_default is None:
                required_columns.append(
                    RequiredColumnTransition(table_name, column_name)
                )
        removed_columns.update(
            f"{table_name}.{column_name}"
            for column_name in live_columns - target_columns
        )
        for column_name in sorted(live_columns & target_columns):
            column = table.columns[column_name]
            if (
                not column.nullable
                and column_name in live.tables[table_name].nullable_columns
            ):
                required_columns.append(
                    RequiredColumnTransition(table_name, column_name)
                )

    enum_transitions = tuple(
        EnumTransition(name, live.enums[name], values)
        for name, values in sorted(target_enum_values(target).items())
        if name in live.enums and live.enums[name] != values
    )

    return SchemaTransitionSet(
        added_tables=target_names - live_names,
        removed_tables=live_names - target_names,
        added_columns=frozenset(added_columns),
        removed_columns=frozenset(removed_columns),
        required_columns=tuple(required_columns),
        enums=enum_transitions,
        definitions=tuple(definitions),
    )


def validate_target_schema(metadata: MetaData) -> None:
    """Fail before Atlas when a model escapes the authoritative public schema."""

    invalid = sorted(
        table.fullname
        for table in metadata.tables.values()
        if table.schema not in {None, "public"}
    )
    if invalid:
        raise ValueError(
            "DbAdmin target contains tables outside public: " + ", ".join(invalid)
        )
