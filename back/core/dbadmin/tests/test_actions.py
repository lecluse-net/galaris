from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin.actions import run_actions
from core.dbadmin.contracts import DbAdminActionStatus, DbAdminPhase, SchemaTransitionSet
from core.dbadmin.models import DbAdminActionRecord
from core.dbadmin.registry import DbAdminAction, DbAdminRegistry
from core.dbadmin.actions import validate_open_actions
from core.dbadmin.contracts import DbAdminFatalError
from core.dbadmin.models import DbAdminActionRevision
from unittest.mock import AsyncMock
from loguru import logger


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [DbAdminPhase.BEFORE_EXPAND, DbAdminPhase.AFTER_EXPAND])
async def test_missing_schema_prerequisite_blocks_handler_and_postcondition(db, phase):
    condition = AsyncMock(return_value=False)
    handler = AsyncMock()
    registry = DbAdminRegistry()
    registry.register_action(DbAdminAction(
        key="test.schema_prerequisite", phase=phase, checksum="v1",
        predicate=lambda _: True, handler=handler, postcondition=condition,
        requires_schema=frozenset({"users.synthetic_future_column"}),
    ))
    results, issues = await run_actions(registry, phase, SchemaTransitionSet())
    assert results[0].status is DbAdminActionStatus.FAILED
    assert issues[0].fatal and "users.synthetic_future_column" in issues[0].message
    condition.assert_not_awaited()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_present_schema_prerequisite_allows_action(db):
    condition = AsyncMock(return_value=True)
    registry = DbAdminRegistry()
    registry.register_action(DbAdminAction(
        key="test.present_schema", phase=DbAdminPhase.AFTER_EXPAND, checksum="v1",
        predicate=lambda _: True, handler=AsyncMock(), postcondition=condition,
        requires_schema=frozenset({"users", "users.id"}),
    ))
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    assert not issues and results[0].status is DbAdminActionStatus.ALREADY_SATISFIED
    condition.assert_awaited_once()


@pytest.fixture
def action_diagnostics():
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)), format="{message}")
    try:
        yield messages
    finally:
        logger.remove(sink)


@pytest.mark.asyncio
async def test_validation_reports_all_previous_causes_before_a_fatal_mismatch(db, action_diagnostics):
    db.add_all([
        DbAdminActionRecord(key="test.first", phase="before_expand", checksum="v1", status="failed",
            last_error="Synthetic first cause; password=synthetic-first-secret"),
        DbAdminActionRecord(key="test.second", phase="after_expand", checksum="v1", status="failed",
            last_error="Synthetic second cause; token=synthetic-second-secret"),
    ])
    await db.commit()
    with pytest.raises(DbAdminFatalError, match="no longer registered"):
        await validate_open_actions(DbAdminRegistry())
    messages = "\n".join(action_diagnostics)
    assert "Synthetic first cause" in messages and "Synthetic second cause" in messages
    assert "synthetic-first-secret" not in messages and "synthetic-second-secret" not in messages


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("compatible", [False, True])
@pytest.mark.parametrize("satisfied", [False, True])
async def test_changed_action_requires_explicit_compatibility(db, required, compatible, satisfied, action_diagnostics):
    key = "test.changed_action"
    db.add(DbAdminActionRecord(key=key, phase="after_expand", checksum="v1", status="failed",
        last_error="Synthetic original conversion cause; password=synthetic-private-value"))
    await db.commit()
    condition = AsyncMock(side_effect=[satisfied, True])
    handler = AsyncMock()
    registry = DbAdminRegistry()
    registry.register_action(DbAdminAction(
        key=key, phase=DbAdminPhase.AFTER_EXPAND, checksum="v2", required=required,
        compatible_checksums=frozenset({"v1"}) if compatible else frozenset(),
        predicate=lambda _: False, handler=handler, postcondition=condition,
    ))
    if required and not compatible:
        with pytest.raises(DbAdminFatalError, match="checksum") as failure:
            await validate_open_actions(registry)
        assert "recorded_checksum='v1'" in str(failure.value)
        assert "expected_checksum='v2'" in str(failure.value)
        assert "status='failed'" in str(failure.value)
        assert any("Synthetic original conversion cause" in message for message in action_diagnostics)
        assert all("synthetic-private-value" not in message for message in action_diagnostics)
        condition.assert_not_awaited()
        return
    validation = await validate_open_actions(registry)
    assert any("Synthetic original conversion cause" in message for message in action_diagnostics)
    assert all("synthetic-private-value" not in message for message in action_diagnostics)
    results, issues = await run_actions(registry, DbAdminPhase.AFTER_EXPAND, SchemaTransitionSet())
    record = await db.get_one(DbAdminActionRecord, key)
    await db.refresh(record)
    if compatible:
        assert not validation and not issues
        assert record.checksum == "v2"
        assert record.status == ("already_satisfied" if satisfied else "applied")
        assert handler.await_count == (0 if satisfied else 1)
    else:
        assert validation and all(not issue.fatal for issue in (*validation, *issues))
        assert results[0].status is DbAdminActionStatus.DEFERRED
        assert record.checksum == "v1" and record.status == "failed"
        handler.assert_not_awaited()
        condition.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [False, True])
async def test_disappeared_action_preserves_journaled_criticality(db, required):
    db.add(DbAdminActionRecord(key="test.missing", phase="after_expand", checksum="v1", status="failed"))
    await db.flush()
    db.add(DbAdminActionRevision(action_key="test.missing", checksum="v1", required=required))
    await db.commit()
    if required:
        with pytest.raises(DbAdminFatalError, match="no longer registered"):
            await validate_open_actions(DbAdminRegistry())
    else:
        issues = await validate_open_actions(DbAdminRegistry())
        assert len(issues) == 1 and not issues[0].fatal


@pytest.mark.asyncio
@pytest.mark.parametrize("open_status", ["running", "deferred", "failed", "before_ddl"])
async def test_unfinished_action_is_retried_after_schema_delta_disappears(
    db: AsyncSession,
    open_status: str,
) -> None:
    key = f"test.retry_without_delta.{open_status}"
    state = {"satisfied": False, "handler_calls": 0}

    async def handler(
        _session: AsyncSession,
        _transitions: SchemaTransitionSet,
    ) -> None:
        state["handler_calls"] += 1
        state["satisfied"] = True

    async def postcondition(
        _session: AsyncSession,
        _transitions: SchemaTransitionSet,
    ) -> bool:
        return bool(state["satisfied"])

    registry = DbAdminRegistry()
    registry.register_action(
        DbAdminAction(
            key=key,
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1",
            predicate=lambda transitions: transitions.column_added("probe", "value"),
            handler=handler,
            postcondition=postcondition,
        )
    )
    if open_status == "before_ddl":
        from core.dbadmin.actions import stage_actions

        # Persist the obligation, then simulate DDL completing and the process
        # dying before AFTER_EXPAND ever gets a chance to run.
        await stage_actions(registry, SchemaTransitionSet(added_columns=frozenset({"probe.value"})))
        assert state["handler_calls"] == 0
    else:
        db.add(DbAdminActionRecord(
            key=key, phase=DbAdminPhase.AFTER_EXPAND.value,
            checksum="v1", status=open_status,
        ))
        await db.commit()

    results, issues = await run_actions(
        registry,
        DbAdminPhase.AFTER_EXPAND,
        SchemaTransitionSet(),
    )

    assert issues == ()
    assert len(results) == 1
    assert results[0].status is DbAdminActionStatus.APPLIED
    assert state["handler_calls"] == 1
    record = await db.get_one(DbAdminActionRecord, key)
    await db.refresh(record)
    assert record.status == "applied"


@pytest.mark.asyncio
async def test_completed_action_without_schema_delta_stays_inactive(
    db: AsyncSession,
) -> None:
    key = "test.completed_without_delta"
    handler_calls = 0

    async def handler(
        _session: AsyncSession,
        _transitions: SchemaTransitionSet,
    ) -> None:
        nonlocal handler_calls
        handler_calls += 1

    async def postcondition(
        _session: AsyncSession,
        _transitions: SchemaTransitionSet,
    ) -> bool:
        return True

    registry = DbAdminRegistry()
    registry.register_action(
        DbAdminAction(
            key=key,
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1",
            predicate=lambda _transitions: False,
            handler=handler,
            postcondition=postcondition,
        )
    )
    db.add(
        DbAdminActionRecord(
            key=key,
            phase=DbAdminPhase.AFTER_EXPAND.value,
            checksum="v1",
            status="applied",
        )
    )
    await db.commit()

    results, issues = await run_actions(
        registry,
        DbAdminPhase.AFTER_EXPAND,
        SchemaTransitionSet(),
    )

    assert results == ()
    assert issues == ()
    assert handler_calls == 0
