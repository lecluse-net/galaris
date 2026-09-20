"""A malformed contribution cannot partially overwrite permanent data."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table

from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminRegistry
from core.dbadmin.dataset import reconcile_dataset
from core.dbadmin.registry import DbAdminAction, DbAdminEnumMapping, DbAdminReconciler
from core.dbadmin.contracts import DbAdminPhase


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["empty_key", "unknown_key", "unknown_update", "unknown_merger", "unknown_column",
    "audit_column", "missing_key", "unhashable_key", "duplicate_key"])
async def test_invalid_dataset_is_rejected_before_any_sql_or_side_effect(db, fault):
    table = Table("dataset_validation_only", MetaData(), Column("id", Integer), Column("label", String), Column("created_at", DateTime))
    after = AsyncMock()
    definition = DbAdminDataset(key="invalid", table=table, natural_key=("id",), rows=({"id": 1, "label": "keep"},), after_merge=after)
    changes = {
        "empty_key": {"natural_key": ()}, "unknown_key": {"natural_key": ("missing",)},
        "unknown_update": {"update_columns": ("missing",)}, "unknown_merger": {"column_mergers": {"missing": lambda a, b: b}},
        "unknown_column": {"rows": ({"id": 1, "missing": "bad"},)},
        "audit_column": {"rows": ({"id": 1, "created_at": datetime.now(timezone.utc)},)},
        "missing_key": {"rows": ({"label": "no identity"},)}, "unhashable_key": {"rows": ({"id": []},)},
        "duplicate_key": {"rows": ({"id": 1}, {"id": 1})},
    }[fault]
    # The table deliberately does not exist: SQL access would fail instead of validation.
    with pytest.raises(ValueError):
        await reconcile_dataset(db, replace(definition, **changes))
    after.assert_not_awaited()
    assert db.is_active


@pytest.mark.parametrize("kind", ["source", "action", "reconciler", "enum"])
def test_duplicate_contributions_cannot_replace_existing_ownership(kind):
    registry = DbAdminRegistry()
    if kind == "source":
        register, first, other = registry.register_data_source, DbAdminDataSource("owner", lambda: ()), DbAdminDataSource("owner", lambda: ())
    elif kind == "action":
        first = DbAdminAction("owner", DbAdminPhase.AFTER_EXPAND, "v1", lambda _: True, AsyncMock(), AsyncMock())
        register, other = registry.register_action, replace(first, checksum="v2")
    elif kind == "reconciler":
        first = DbAdminReconciler("owner", AsyncMock())
        register, other = registry.register_reconciler, replace(first, handler=AsyncMock())
    else:
        first = DbAdminEnumMapping("owner", {"old": "new"})
        register, other = registry.register_enum_mapping, DbAdminEnumMapping("owner", {"old": "lost"})
    register(first)
    with pytest.raises(ValueError, match="Duplicate"):
        register(other)
    if kind == "enum":
        assert registry.enum_mapping("owner").values == {"old": "new"}


@pytest.mark.parametrize("fault", ["missing", "cycle"])
def test_unresolvable_reconciler_dependencies_stop_before_execution(fault):
    registry = DbAdminRegistry()
    first, second = AsyncMock(), AsyncMock()
    registry.register_reconciler(DbAdminReconciler("first", first, depends_on=("second",)))
    if fault == "cycle":
        registry.register_reconciler(DbAdminReconciler("second", second, depends_on=("first",)))
    with pytest.raises(ValueError, match="unknown" if fault == "missing" else "cycle"):
        _ = registry.reconcilers
    first.assert_not_called()
    second.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dataset", "reconciler"])
@pytest.mark.parametrize("required", [False, True])
async def test_failed_contribution_is_reported_and_independent_contribution_still_runs(db, kind, required):
    from core.dbadmin.actions import run_datasets, run_reconcilers
    from core import settings
    completed = []
    async def fail(session):
        raise ValueError("bad configuration " + settings.POSTGRES_PASSWORD + "\x00")
    async def succeed(session):
        completed.append(True)
        return ()
    registry = DbAdminRegistry()
    if kind == "dataset":
        table = Table("users", MetaData(), Column("id", Integer))
        registry.register_data_source(DbAdminDataSource("source", lambda: (
            DbAdminDataset("first", table, ("id",), fail, required=required),
            DbAdminDataset("second", table, ("id",), succeed),
        )))
        issues = await run_datasets(registry)
    else:
        registry.register_reconciler(DbAdminReconciler("first", fail, required=required))
        registry.register_reconciler(DbAdminReconciler("second", succeed))
        issues = await run_reconcilers(registry)
    assert completed == [True]
    assert len(issues) == 1 and issues[0].fatal == required
    assert issues[0].object_name == "first"
    assert settings.POSTGRES_PASSWORD not in issues[0].message and "\x00" not in issues[0].message
