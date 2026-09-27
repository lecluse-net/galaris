from __future__ import annotations

import pytest
from sqlalchemy import ARRAY, Column, Enum, Integer, MetaData, String, Table

from core.dbadmin._internal.enums import validate_enum_transitions
from core.dbadmin._internal.target import staged_metadata
from core.dbadmin.contracts import DbAdminFatalError, EnumTransition
from core.dbadmin.registry import DbAdminEnumMapping, DbAdminRegistry
from core.dbadmin.snapshot import LiveTable, SchemaSnapshot, compute_transitions, target_enum_values, validate_target_schema


def test_conflicting_enum_declarations_block_schema_generation():
    target = MetaData()
    Table("first", target, Column("state", Enum("ready", "done", name="shared_state")))
    Table("second", target, Column("state", Enum("ready", "failed", name="shared_state")))
    with pytest.raises(ValueError, match="contradictory declarations"):
        compute_transitions(SchemaSnapshot(tables={}, enums={}), target)


def test_only_named_native_enums_require_postgresql_enum_transitions():
    target = MetaData()
    Table("items", target, Column("native", Enum("ready", name="state")),
        Column("portable", Enum("local", name="portable", native_enum=False)),
        Column("array", ARRAY(Enum("ready", name="array_state"))),
        Column("unnamed", Enum("anonymous")))
    assert target_enum_values(target) == {"state": ("ready",), "array_state": ("ready",)}


@pytest.mark.parametrize("labels", [(), ("same", "same"), ("x" * 64,), ("é" * 32,), ("bad\x00label",)])
def test_invalid_enum_targets_fail_before_ddl(labels):
    with pytest.raises(DbAdminFatalError):
        validate_enum_transitions((EnumTransition("state", ("old",), labels),), DbAdminRegistry())


@pytest.mark.parametrize("schema", ["private", "vectors"])
@pytest.mark.parametrize("kind", ["table", "enum", "array_enum"])
def test_target_cannot_take_ownership_of_external_schemas(schema, kind):
    target = MetaData()
    if kind == "table":
        Table("records", target, Column("id", Integer), schema=schema)
    else:
        state = Enum("old", name="state", schema=schema)
        Table("records", target, Column("state", ARRAY(state) if kind == "array_enum" else state))
    with pytest.raises(ValueError, match="outside public"):
        validate_target_schema(target)


def test_new_required_column_is_staged_without_mutating_target() -> None:
    target = MetaData()
    Table(
        "items",
        target,
        Column("id", Integer, primary_key=True),
        Column("code", String, nullable=False),
    )
    live = SchemaSnapshot(
        tables={"items": LiveTable("items", frozenset({"id"}))},
        enums={},
    )

    transitions = compute_transitions(live, target)
    expansion = staged_metadata(target, transitions.required_columns)

    assert [item.key for item in transitions.required_columns] == ["items.code"]
    assert target.tables["items"].columns["code"].nullable is False
    assert expansion.tables["items"].columns["code"].nullable is True


def test_server_default_does_not_require_staging() -> None:
    target = MetaData()
    Table(
        "items",
        target,
        Column("id", Integer, primary_key=True),
        Column("code", String, nullable=False, server_default="ready"),
    )
    live = SchemaSnapshot(
        tables={"items": LiveTable("items", frozenset({"id"}))},
        enums={},
    )

    transitions = compute_transitions(live, target)

    assert transitions.required_columns == ()


def test_nullable_column_from_previous_run_stays_staged() -> None:
    target = MetaData()
    Table(
        "items",
        target,
        Column("id", Integer, primary_key=True),
        Column("code", String, nullable=False),
    )
    live = SchemaSnapshot(
        tables={
            "items": LiveTable(
                "items",
                frozenset({"id", "code"}),
                nullable_columns=frozenset({"code"}),
            )
        },
        enums={},
    )

    transitions = compute_transitions(live, target)

    assert [item.key for item in transitions.required_columns] == ["items.code"]


def test_enum_removal_requires_total_mapping() -> None:
    transition = EnumTransition("state", ("open", "closed"), ("open",))

    with pytest.raises(DbAdminFatalError, match="closed"):
        validate_enum_transitions((transition,), DbAdminRegistry())


def test_enum_removal_accepts_developer_mapping() -> None:
    transition = EnumTransition("state", ("open", "closed"), ("open",))
    registry = DbAdminRegistry()
    registry.register_enum_mapping(
        DbAdminEnumMapping("state", {"closed": "open"})
    )

    validate_enum_transitions((transition,), registry)


def test_enum_addition_needs_no_mapping() -> None:
    target = MetaData()
    Table(
        "items",
        target,
        Column("id", Integer, primary_key=True),
        Column("state", Enum("open", "closed", name="state"), nullable=False),
    )
    live = SchemaSnapshot(
        tables={"items": LiveTable("items", frozenset({"id", "state"}))},
        enums={"state": ("open",)},
    )

    transitions = compute_transitions(live, target)

    validate_enum_transitions(transitions.enums, DbAdminRegistry())
    assert transitions.enums[0].target_values == ("open", "closed")
