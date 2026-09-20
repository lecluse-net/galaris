"""Opt-in populated-table qualification, always against the ephemeral test DB."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import time

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, text

from core.database import engine
from core.dbadmin._internal.atlas import apply_target
from core.dbadmin._internal.target import load_target_metadata, render_target_sql, staged_metadata
from core.dbadmin.scope import DbAdminDdlFilters
from core.dbadmin.snapshot import compute_transitions, inspect_public_schema


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("DBADMIN_LOAD_TEST") != "1", reason="Opt-in populated-table qualification")
async def test_populated_table_nullable_backfill_contract_and_concurrent_writes():
    rows = int(os.environ.get("DBADMIN_LOAD_ROWS", "100000"))
    assert 1000 <= rows <= 1000000
    canonical = load_target_metadata()

    def target(required=False, indexed=False):
        metadata = MetaData()
        for table in canonical.tables.values():
            table.to_metadata(metadata)
        columns = [Column("id", Integer, primary_key=True), Column("writes", Integer, server_default="0")]
        if required:
            columns.append(Column("code", String(50), nullable=False))
        table = Table("dbadmin_volume_probe", metadata, *columns)
        if indexed:
            Index("ix_dbadmin_volume_code", table.c.code)
        return metadata

    scope = DbAdminDdlFilters()
    samples = []
    phases = []
    current_phase = "setup"
    done = asyncio.Event()

    @asynccontextmanager
    async def phase(name):
        nonlocal current_phase
        current_phase = name
        started = time.monotonic()
        try:
            yield
        finally:
            phases.append({"phase": name, "seconds": time.monotonic() - started})

    async def writer():
        while not done.is_set():
            started = time.monotonic()
            admitted_phase = current_phase
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL application_name = 'galaris-dbadmin-volume-writer'"))
                await connection.execute(text("UPDATE dbadmin_volume_probe SET writes = writes + 1 WHERE id = 1"))
            samples.append({"phase": admitted_phase, "seconds": time.monotonic() - started})
            await asyncio.sleep(0.005)

    worker = None
    started = time.monotonic()
    try:
        async with phase("create"):
            await apply_target(render_target_sql(target()), scope=scope)
        async with phase("seed"):
            async with engine.begin() as connection:
                await connection.execute(text("INSERT INTO dbadmin_volume_probe (id) SELECT generate_series(1, :rows)"), {"rows": rows})
        async with phase("inspect"):
            worker = asyncio.create_task(writer())
            desired = target(True)
            async with engine.connect() as connection:
                live = await inspect_public_schema(connection)
            transitions = compute_transitions(live, desired)
            expansion = staged_metadata(desired, transitions.required_columns)
        async with phase("exclusive_lock_and_interruption"):
            async with engine.begin() as blocker:
                await blocker.execute(text("LOCK TABLE dbadmin_volume_probe IN ACCESS EXCLUSIVE MODE"))
                # Observe a real PostgreSQL lock wait instead of inferring it from elapsed time.
                async with asyncio.timeout(5):
                    while True:
                        async with engine.connect() as observer:
                            blocked = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE application_name = 'galaris-dbadmin-volume-writer' AND wait_event_type = 'Lock'"))
                        if blocked:
                            break
                        await asyncio.sleep(0.01)
                interrupted = asyncio.create_task(apply_target(render_target_sql(expansion), scope=scope))
                await asyncio.sleep(0.1)
                interrupted.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await interrupted
        async with phase("nullable_expansion"):
            await apply_target(render_target_sql(expansion), scope=scope)
        async with phase("backfill"):
            async with engine.begin() as connection:
                assert await connection.scalar(text("SELECT count(*) FROM dbadmin_volume_probe WHERE code IS NULL")) == rows
                await connection.execute(text("UPDATE dbadmin_volume_probe SET code = 'ready'"))
        async with phase("not_null_contraction"):
            await apply_target(render_target_sql(desired), scope=scope)
        async with phase("index_creation"):
            desired = target(True, True)
            await apply_target(render_target_sql(desired), scope=scope)
        async with phase("idempotent_replay"):
            assert not (await apply_target(render_target_sql(desired), scope=scope)).changed
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM dbadmin_volume_probe WHERE code = 'ready'")) == rows
            assert await connection.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='dbadmin_volume_probe' AND column_name='code'")) == "NO"
            assert await connection.scalar(text("SELECT count(*) FROM pg_indexes WHERE tablename = 'dbadmin_volume_probe' AND indexname = 'ix_dbadmin_volume_code'")) == 1
        done.set()
        await worker
        assert samples and max(sample["seconds"] for sample in samples) >= 0.1
        assert time.monotonic() - started < 120
        for entry in phases:
            durations = sorted(sample["seconds"] for sample in samples if sample["phase"] == entry["phase"])
            entry.update(writer_commits=len(durations), writer_max_seconds=max(durations, default=0),
                         writer_p95_seconds=durations[int((len(durations) - 1) * 0.95)] if durations else None)
        report = {"rows": rows, "seconds": time.monotonic() - started,
                  "writer_commits": len(samples), "observed_postgresql_lock_wait": True, "phases": phases}
        destination = Path(__file__).resolve().parents[4] / "artifacts/dbadmin-volume-benchmark.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        done.set()
        if worker is not None:
            await worker
        await apply_target(render_target_sql(canonical), scope=scope)
        await engine.dispose()
