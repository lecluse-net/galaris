"""Operator diagnostics and dry runs must not mutate application data."""

from datetime import datetime, timedelta, timezone
from io import StringIO
from uuid import uuid4

from loguru import logger
import pytest
from sqlalchemy import delete, func, select, text

from core.database import engine
from core.dbadmin import orchestrator, journal
from core.dbadmin._internal import atlas
from core.dbadmin.contracts import DbAdminFatalError, DbAdminIssue, DbAdminMode, DbAdminResult, DbAdminVerdict
from core.dbadmin.models import DbAdminIssueRecord, DbAdminRun
from core.dbadmin.registry import DbAdminRegistry
from core.dbadmin.scope import DbAdminDdlFilters


@pytest.mark.asyncio
@pytest.mark.parametrize("environment,expected", [
    ("dev", DbAdminMode.DEVELOPMENT),
    *((env, DbAdminMode.PRODUCTION) for env in ("prod", "pp", "test", "demo", "custom")),
])
async def test_dry_run_inspects_actual_schema_without_persisting_runs_or_applying_changes(db, monkeypatch, environment, expected):
    monkeypatch.setattr(orchestrator.settings, "APP_ENV", environment)
    before = await db.scalar(select(func.count()).select_from(DbAdminRun))
    result = await orchestrator.synchronize_database(dry_run=True, target_registry=DbAdminRegistry())
    assert result.mode == expected and result.exit_code == 0
    assert await db.scalar(select(func.count()).select_from(DbAdminRun)) == before
    assert result.action_results == ()


@pytest.mark.asyncio
async def test_operator_summary_is_bounded_and_returns_latest_persisted_verdict(db):
    now = datetime.now(timezone.utc)
    await db.execute(delete(DbAdminIssueRecord))
    await db.execute(delete(DbAdminRun))
    await db.commit()
    assert await journal.latest_summary() is None
    for index in range(2):
        result = DbAdminResult(run_id=str(uuid4()), mode=DbAdminMode.TEST,
            verdict=DbAdminVerdict.DEGRADED if index else DbAdminVerdict.CONVERGED,
            started_at=now + timedelta(seconds=index), finished_at=now + timedelta(seconds=index + 1),
            scope_fingerprint="scope", target_fingerprint="target",
            issues=tuple(DbAdminIssue("dataset", "problem " * 1000, f"source-{i}") for i in range(110)) if index else ())
        await journal.persist_result_best_effort(result)
    summary = await journal.latest_summary()
    assert summary["run_id"] == result.run_id and summary["verdict"] == "degraded"
    assert summary["summary"]["issues"] == 110
    issues = list(await db.scalars(select(DbAdminIssueRecord)))
    assert len(issues) == 100 and all(len(issue.message) == 4000 for issue in issues)


@pytest.mark.asyncio
async def test_journal_failure_preserves_verdict_and_logs_a_scrubbed_diagnostic(db, monkeypatch):
    now = datetime.now(timezone.utc)
    result = DbAdminResult(run_id=str(uuid4()), mode=DbAdminMode.TEST, verdict=DbAdminVerdict.FATAL,
        started_at=now, finished_at=now, scope_fingerprint="scope", target_fingerprint="target")
    await journal.persist_result(result)
    # A repeated write produces a real database uniqueness failure; its SQL
    # parameters contain this value, which must be redacted from the diagnostic.
    monkeypatch.setattr(journal.settings, "POSTGRES_PASSWORD", result.run_id)
    output = StringIO()
    sink = logger.add(output, format="{message}", filter=lambda record: record["name"] == journal.__name__)
    try:
        await journal.persist_result_best_effort(result)
    finally:
        logger.remove(sink)
    assert result.verdict == DbAdminVerdict.FATAL
    assert "could not persist" in output.getvalue()
    assert result.run_id not in output.getvalue()
    assert len(output.getvalue()) < 4100


@pytest.mark.asyncio
async def test_lock_contention_times_out_and_releases_failed_connection():
    first = await orchestrator._acquire_lock()
    try:
        with pytest.raises(DbAdminFatalError, match="advisory lock"):
            await orchestrator._acquire_lock(timeout=0)
    finally:
        await orchestrator._release_lock(first)
    next_owner = await orchestrator._acquire_lock(timeout=0)
    await orchestrator._release_lock(next_owner)
    assert first.closed and next_owner.closed


@pytest.mark.asyncio
async def test_lost_database_connection_during_unlock_still_closes_cleanly():
    connection = await orchestrator._acquire_lock()
    await connection.close()
    await orchestrator._release_lock(connection)
    assert connection.closed


@pytest.mark.asyncio
async def test_invalid_target_sql_fails_without_changing_application_schema(tmp_path):
    target = tmp_path / "invalid.sql"
    target.write_text("THIS IS NOT VALID SQL;")
    with pytest.raises(DbAdminFatalError, match="materialize Atlas target"):
        await atlas._materialize_target(target, "public")
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT to_regclass('public.users')")) == "users"


@pytest.mark.asyncio
async def test_atlas_command_failure_is_a_blocking_error():
    with pytest.raises(DbAdminFatalError, match="Atlas failed with exit code"):
        await atlas._run_atlas("--invalid-galaris-test-option")


@pytest.mark.parametrize("plan", ['ALTER TABLE private.records ADD COLUMN value text;',
    'DROP TABLE "vectors"."embeddings";', 'CREATE TYPE other.state AS ENUM (\'ready\');'])
def test_plan_outside_public_is_rejected_before_application(plan):
    with pytest.raises(DbAdminFatalError, match="outside public"):
        atlas._validate_plan_scope(plan, DbAdminDdlFilters())


def test_large_plan_preserves_beginning_and_end_without_exposing_password(monkeypatch):
    monkeypatch.setattr(atlas.settings, "POSTGRES_PASSWORD", "plan-secret")
    rendered = atlas._bounded_plan("START plan-secret " + "x" * 20000 + " plan-secret END")
    assert rendered.startswith("START") and rendered.endswith("END")
    assert "truncated" in rendered and len(rendered) < 12100
    assert "plan-secret" not in rendered
