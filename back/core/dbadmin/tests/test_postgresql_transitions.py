from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, text

from core.database import AsyncSessionLocal, engine
from core.dbadmin._internal.atlas import apply_target
from core.dbadmin._internal.enums import (
    prepare_enum_transitions,
    validate_enum_transitions,
)
from core.dbadmin._internal.target import (
    load_target_metadata,
    render_target_sql,
    staged_metadata,
)
from core.dbadmin.contracts import DbAdminVerdict, EnumTransition
from core.dbadmin.contracts import DbAdminPhase
from core.dbadmin.dataset import DbAdminDataset, reconcile_dataset
from core.dbadmin.orchestrator import synchronize_database
from core.dbadmin.registry import DbAdminEnumMapping, DbAdminRegistry
from core.dbadmin.registry import DbAdminAction
from core.dbadmin.scope import DbAdminDdlFilters
from core.dbadmin.snapshot import compute_transitions, inspect_public_schema


@pytest.mark.asyncio
async def test_snapshot_preserves_postgresql_check_and_exclusion_definitions() -> None:
    from sqlalchemy import CheckConstraint
    from sqlalchemy.dialects.postgresql import ExcludeConstraint, TSRANGE
    canonical = load_target_metadata()
    target = _copy_metadata(canonical)
    Table("dbadmin_constraint_probe", target, Column("id", Integer, primary_key=True),
          Column("period", TSRANGE), CheckConstraint("id > 0", name="ck_probe_positive"),
          ExcludeConstraint(("period", "&&"), name="ex_probe_period"))
    scope = DbAdminDdlFilters()
    try:
        await apply_target(render_target_sql(target), scope=scope)
        async with engine.connect() as connection:
            snapshot = await inspect_public_schema(connection)
        constraints = snapshot.tables["dbadmin_constraint_probe"].constraints
        assert constraints["ck_probe_positive"].kind == "check"
        assert "id > 0" in constraints["ck_probe_positive"].definition
        assert constraints["ex_probe_period"].kind == "exclusion"
        assert "period WITH &&" in constraints["ex_probe_period"].definition
    finally:
        await apply_target(render_target_sql(canonical), scope=scope)
        await engine.dispose()


def _copy_metadata(source: MetaData) -> MetaData:
    copied = MetaData()
    for table in source.tables.values():
        table.to_metadata(copied)
    return copied


@pytest.mark.asyncio
async def test_enum_additions_preserve_rows_order_and_quoted_labels_on_replay():
    registry = DbAdminRegistry()
    transition = EnumTransition("dbadmin_added_labels", ("middle",), ("before", "middle", "after", "quote's value"))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TYPE dbadmin_added_labels AS ENUM ('middle')"))
        await connection.execute(text("CREATE TABLE dbadmin_enum_additions (id integer PRIMARY KEY, state dbadmin_added_labels)"))
        await connection.execute(text("INSERT INTO dbadmin_enum_additions VALUES (1, 'middle'), (2, NULL)"))
    try:
        validate_enum_transitions((transition,), registry)
        for _ in range(2):
            async with engine.begin() as connection:
                await prepare_enum_transitions(connection, (transition,), registry)
        async with engine.begin() as connection:
            labels = await connection.scalar(text("SELECT enum_range(NULL::dbadmin_added_labels)::text"))
            assert labels == '{before,middle,after,"quote\'s value"}'
            rows = (await connection.execute(text("SELECT id, state::text FROM dbadmin_enum_additions ORDER BY id"))).all()
            assert rows == [(1, "middle"), (2, None)]
            await connection.execute(text("INSERT INTO dbadmin_enum_additions VALUES (3, 'after')"))
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS dbadmin_enum_additions"))
            await connection.execute(text("DROP TYPE IF EXISTS dbadmin_added_labels"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_not_null_column_expands_then_contracts_on_postgresql() -> None:
    canonical = load_target_metadata()
    initial = _copy_metadata(canonical)
    Table(
        "dbadmin_required_probe",
        initial,
        Column("id", Integer, primary_key=True),
    )
    scope = DbAdminDdlFilters()

    try:
        await apply_target(render_target_sql(initial), scope=scope)
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO dbadmin_required_probe (id) VALUES (1)")
            )

        evolved = _copy_metadata(canonical)
        Table(
            "dbadmin_required_probe",
            evolved,
            Column("id", Integer, primary_key=True),
            Column("code", String(50), nullable=False),
        )
        async with engine.connect() as connection:
            live = await inspect_public_schema(connection)
        transitions = compute_transitions(live, evolved)
        assert [item.key for item in transitions.required_columns] == [
            "dbadmin_required_probe.code"
        ]

        expansion = staged_metadata(evolved, transitions.required_columns)
        await apply_target(render_target_sql(expansion), scope=scope)
        async with engine.begin() as connection:
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='dbadmin_required_probe' AND column_name='code'"
                )
            )
            assert nullable == "YES"
            await connection.execute(
                text("UPDATE dbadmin_required_probe SET code = 'ready'")
            )

        await apply_target(render_target_sql(evolved), scope=scope)
        async with engine.connect() as connection:
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name='dbadmin_required_probe' AND column_name='code'"
                )
            )
        assert nullable == "NO"
    finally:
        await apply_target(render_target_sql(canonical), scope=scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_enum_replacement_maps_data_atomically() -> None:
    enum_name = "dbadmin_test_state"
    table_name = "dbadmin_enum_probe"
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
        await connection.execute(text(f'DROP TYPE IF EXISTS "{enum_name}"'))
        await connection.execute(
            text(f'CREATE TYPE "{enum_name}" AS ENUM (\'open\', \'closed\')')
        )
        await connection.execute(
            text(
                f'CREATE TABLE "{table_name}" '
                f'(id integer PRIMARY KEY, state "{enum_name}" NOT NULL)'
            )
        )
        await connection.execute(
            text(f'INSERT INTO "{table_name}" VALUES (1, \'closed\')')
        )

    transition = EnumTransition(
        enum_name,
        ("open", "closed"),
        ("open", "archived"),
    )
    registry = DbAdminRegistry()
    registry.register_enum_mapping(
        DbAdminEnumMapping(enum_name, {"closed": "archived"})
    )
    validate_enum_transitions((transition,), registry)

    try:
        async with engine.begin() as connection:
            await prepare_enum_transitions(connection, (transition,), registry)
        async with engine.connect() as connection:
            value = await connection.scalar(
                text(f'SELECT state::text FROM "{table_name}" WHERE id = 1')
            )
            labels = tuple(
                (
                    await connection.execute(
                        text(
                            "SELECT e.enumlabel FROM pg_type t "
                            "JOIN pg_enum e ON e.enumtypid=t.oid "
                            "WHERE t.typname=:name ORDER BY e.enumsortorder"
                        ),
                        {"name": enum_name},
                    )
                ).scalars()
            )
        assert value == "archived"
        assert labels == ("open", "archived")
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            await connection.execute(text(f'DROP TYPE IF EXISTS "{enum_name}"'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_canonical_target_has_no_atlas_diff_after_bootstrap() -> None:
    target = load_target_metadata()

    try:
        result = await apply_target(
            render_target_sql(target),
            scope=DbAdminDdlFilters(),
            dry_run=True,
        )
    finally:
        await engine.dispose()

    assert result.changed is False


@pytest.mark.asyncio
async def test_dataset_reconciliation_is_idempotent_and_restores_history() -> None:
    metadata = MetaData()
    table = Table(
        "dbadmin_dataset_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("code", String(50), nullable=False, unique=True),
        Column("label", String(100), nullable=False),
        Column("deleted_at", DateTime(timezone=True), nullable=True),
        Column("deleted_by", Integer, nullable=True),
    )
    definition = DbAdminDataset(
        key="dbadmin.dataset_probe",
        table=table,
        natural_key=("code",),
        rows=(
            {"code": "alpha", "label": "Alpha"},
            {"code": "beta", "label": "Beta"},
        ),
        delete_missing=True,
    )

    try:
        async with engine.begin() as connection:
            await connection.execute(text('DROP TABLE IF EXISTS "dbadmin_dataset_probe"'))
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                table.insert(),
                (
                    {
                        "code": "alpha",
                        "label": "Old alpha",
                        "deleted_at": datetime.now(timezone.utc),
                        "deleted_by": 7,
                    },
                    {
                        "code": "obsolete",
                        "label": "Obsolete",
                        "deleted_at": None,
                        "deleted_by": None,
                    },
                ),
            )

        async with AsyncSessionLocal() as session:
            first = await reconcile_dataset(session, definition)
            await session.commit()
        async with AsyncSessionLocal() as session:
            second = await reconcile_dataset(session, definition)
            await session.commit()

        async with engine.connect() as connection:
            rows = {
                row.code: row
                for row in (
                    await connection.execute(
                        text(
                            'SELECT code, label, deleted_at, deleted_by '
                            'FROM "dbadmin_dataset_probe"'
                        )
                    )
                )
            }

        assert first.inserted == 1
        assert first.updated == 1
        assert first.restored == 1
        assert first.removed == 1
        assert second == type(second)()
        assert rows["alpha"].label == "Alpha"
        assert rows["alpha"].deleted_at is None
        assert rows["alpha"].deleted_by is None
        assert rows["beta"].deleted_at is None
        assert rows["obsolete"].deleted_at is not None
    finally:
        async with engine.begin() as connection:
            await connection.execute(text('DROP TABLE IF EXISTS "dbadmin_dataset_probe"'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_complete_registered_dataset_cycle_is_idempotent() -> None:
    try:
        first = await synchronize_database()
        second = await synchronize_database()
    finally:
        await engine.dispose()

    assert first.verdict is DbAdminVerdict.CONVERGED
    assert second.verdict is DbAdminVerdict.CONVERGED
    assert second.issues == ()


@pytest.mark.asyncio
async def test_orchestrator_keeps_nullable_column_operational_until_later_backfill(monkeypatch):
    from core.dbadmin import orchestrator

    canonical = load_target_metadata()
    evolved = _copy_metadata(canonical)
    Table("dbadmin_operational_probe", evolved,
          Column("id", Integer, primary_key=True),
          Column("code", String(50), nullable=False))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE dbadmin_operational_probe (id integer PRIMARY KEY)"))
        await connection.execute(text("INSERT INTO dbadmin_operational_probe VALUES (1)"))
    monkeypatch.setattr(orchestrator, "load_target_metadata", lambda: evolved)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    try:
        first = await synchronize_database(target_registry=DbAdminRegistry())
        assert first.verdict is DbAdminVerdict.STAGED
        assert first.exit_code == 0
        assert [item.key for item in first.transitions.required_columns] == ["dbadmin_operational_probe.code"]
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM dbadmin_operational_probe WHERE code IS NULL")) == 1
            # The running app can write the new column before a future synchronization.
            await connection.execute(text("UPDATE dbadmin_operational_probe SET code='ready'"))
        second = await synchronize_database(target_registry=DbAdminRegistry())
        assert second.verdict is DbAdminVerdict.CONVERGED
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='dbadmin_operational_probe' AND column_name='code'")) == "NO"
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS dbadmin_operational_probe"))
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "deferred"])
async def test_unfinished_backup_preserves_source_data(monkeypatch, failure):
    from core.dbadmin import orchestrator
    from core.dbadmin.contracts import DbAdminPhase
    from core.dbadmin.registry import DbAdminAction

    canonical = load_target_metadata()
    evolved = _copy_metadata(canonical)
    Table("dbadmin_new_probe", evolved, Column("id", Integer, primary_key=True))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE dbadmin_source_probe (id integer PRIMARY KEY, payload text)"))
        await connection.execute(text("INSERT INTO dbadmin_source_probe VALUES (1, 'valuable')"))
    monkeypatch.setattr(orchestrator, "load_target_metadata", lambda: evolved)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    ready = False

    async def handler(session, transitions):
        if failure == "exception":
            raise RuntimeError("backup unavailable")

    async def postcondition(session, transitions):
        return ready

    registry = DbAdminRegistry()
    registry.register_action(DbAdminAction(
        key="test.backup_source", phase=DbAdminPhase.BEFORE_EXPAND, checksum="v1",
        predicate=lambda delta: "dbadmin_source_probe" in delta.removed_tables,
        handler=handler, postcondition=postcondition,
    ))
    try:
        first = await synchronize_database(target_registry=registry)
        assert first.verdict is (DbAdminVerdict.FATAL if failure == "exception" else DbAdminVerdict.DEGRADED)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT payload FROM dbadmin_source_probe WHERE id=1")) == "valuable"
            if failure == "deferred":
                assert await connection.scalar(text("SELECT to_regclass('dbadmin_new_probe')")) is not None
        ready = True
        second = await synchronize_database(target_registry=registry)
        assert second.verdict is DbAdminVerdict.CONVERGED
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('dbadmin_source_probe')")) is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS dbadmin_source_probe, dbadmin_new_probe"))
            await connection.execute(text("DELETE FROM dbadmin_actions WHERE key='test.backup_source'"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_contraction_keeps_successful_expansion_operational(monkeypatch):
    from core.dbadmin import orchestrator
    from core.dbadmin.contracts import DbAdminFatalError

    evolved = _copy_metadata(load_target_metadata())
    Table("dbadmin_contract_probe", evolved, Column("id", Integer, primary_key=True))
    monkeypatch.setattr(orchestrator, "load_target_metadata", lambda: evolved)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    calls = 0

    async def fail_contract(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DbAdminFatalError("simulated constraint lock timeout")
        return await apply_target(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "apply_target", fail_contract)
    try:
        result = await synchronize_database(target_registry=DbAdminRegistry())
        assert result.verdict is DbAdminVerdict.DEGRADED
        assert result.exit_code == 0
        assert any(issue.phase == "contract" and not issue.fatal for issue in result.issues)
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO dbadmin_contract_probe VALUES (1)"))
            assert await connection.scalar(text("SELECT id FROM dbadmin_contract_probe")) == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS dbadmin_contract_probe"))
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [DbAdminPhase.AFTER_EXPAND, DbAdminPhase.AFTER_DATASET])
@pytest.mark.parametrize("failure", ["required", "optional", "deferred"])
async def test_post_expansion_failure_preserves_sources_and_resumes(monkeypatch, phase, failure):
    from core.dbadmin import orchestrator

    evolved = _copy_metadata(load_target_metadata())
    Table("dbadmin_phase_destination", evolved, Column("id", Integer, primary_key=True))
    monkeypatch.setattr(orchestrator, "load_target_metadata", lambda: evolved)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    ready = False
    checked = False

    async def handler(session, transitions):
        if failure != "deferred":
            await session.execute(text("UPDATE dbadmin_phase_source SET payload='uncommitted'"))
            raise RuntimeError("Injected preparation failure")

    async def complete(session, transitions):
        return ready

    async def check_contract(session, transitions):
        nonlocal checked
        checked = True

    async def contract_complete(session, transitions):
        return checked

    registry = DbAdminRegistry()
    registry.register_action(DbAdminAction(
        key="test.phase_failure", phase=phase, checksum="v1",
        predicate=lambda delta: "dbadmin_phase_source" in delta.removed_tables,
        handler=handler, postcondition=complete, required=failure != "optional",
    ))
    registry.register_action(DbAdminAction(
        key="test.phase_contract", phase=DbAdminPhase.AFTER_CONTRACT, checksum="v1",
        predicate=lambda delta: True, handler=check_contract, postcondition=contract_complete,
    ))
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE dbadmin_phase_source (id integer PRIMARY KEY, payload text)"))
        await connection.execute(text("INSERT INTO dbadmin_phase_source VALUES (1, 'valuable')"))
    try:
        first = await synchronize_database(target_registry=registry)
        assert first.verdict is (DbAdminVerdict.FATAL if failure == "required" else DbAdminVerdict.DEGRADED)
        assert first.exit_code == (1 if failure == "required" else 0)
        assert not checked
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT payload FROM dbadmin_phase_source")) == "valuable"
            await connection.execute(text("INSERT INTO dbadmin_phase_destination VALUES (1)"))
        ready = True
        second = await synchronize_database(target_registry=registry)
        assert second.verdict is DbAdminVerdict.CONVERGED
        assert checked
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('dbadmin_phase_source')")) is None
            assert await connection.scalar(text("SELECT id FROM dbadmin_phase_destination")) == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS dbadmin_phase_source, dbadmin_phase_destination"))
            await connection.execute(text("DELETE FROM dbadmin_actions WHERE key IN ('test.phase_failure', 'test.phase_contract')"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_definition_deltas_describe_types_defaults_indexes_and_foreign_keys():
    from sqlalchemy import ForeignKey, Index
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE public.dbadmin_definition_probe (id integer primary key, user_id integer REFERENCES users(id), label varchar(12) DEFAULT 'old')"))
        await connection.execute(text("CREATE INDEX dbadmin_probe_label ON public.dbadmin_definition_probe(label)"))
    try:
        async with engine.connect() as connection:
            live = await inspect_public_schema(connection)
        target = MetaData()
        Table("users", target, Column("id", Integer, primary_key=True))
        table = Table("dbadmin_definition_probe", target,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, ForeignKey("users.id", name="dbadmin_definition_probe_user_id_fkey", ondelete="CASCADE")),
            Column("label", String(40), server_default="new"))
        Index("dbadmin_probe_label", table.c.label, unique=True)
        deltas = [item for item in compute_transitions(live, target).definitions if item.table_name == table.name]
        assert {item.kind for item in deltas} >= {"column_type", "column_default", "index", "foreign_key"}
        type_delta = next(item for item in deltas if item.kind == "column_type" and item.object_name == "label")
        assert type_delta.live_definition == "VARCHAR(12)"
        assert type_delta.target_definition == "VARCHAR(40)"
        # Inspection and evidence do not perform a transformation themselves.
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='dbadmin_definition_probe' AND column_name='label'")) == 12
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE public.dbadmin_definition_probe"))


@pytest.mark.asyncio
async def test_index_deltas_include_covering_operator_classes_and_storage_options():
    import json
    from sqlalchemy import Index
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE public.dbadmin_index_probe (id integer primary key, label text)"))
        await connection.execute(text("CREATE INDEX dbadmin_covering_probe ON public.dbadmin_index_probe (label text_pattern_ops) INCLUDE (id) WITH (fillfactor=70)"))
    try:
        async with engine.connect() as connection:
            live = await inspect_public_schema(connection)
        target = MetaData()
        table = Table("dbadmin_index_probe", target, Column("id", Integer, primary_key=True), Column("label", Text))
        Index("dbadmin_covering_probe", table.c.label, postgresql_include=["id"], postgresql_ops={"label": "text_pattern_ops"}, postgresql_with={"fillfactor": 70})
        # Equal definitions must not create a perpetual false delta.
        assert not [change for change in compute_transitions(live, target).definitions if change.kind == "index" and change.object_name == "dbadmin_covering_probe"]
        index = next(iter(table.indexes))
        index.dialect_options["postgresql"]["with"] = {"fillfactor": 80}
        change = next(change for change in compute_transitions(live, target).definitions if change.object_name == "dbadmin_covering_probe")
        previous = json.loads(change.live_definition)
        desired = json.loads(change.target_definition)
        assert previous["include"] == ["id"] and previous["ops"] == {"label": "text_pattern_ops"}
        assert previous["with"] == {"fillfactor": "70"} and desired["with"] == {"fillfactor": "80"}
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE public.dbadmin_index_probe"))
