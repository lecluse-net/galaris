"""Single orchestration authority for schema, datasets, and upgrade actions."""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4
from weakref import WeakSet

from loguru import logger
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from core import settings
from core.database import engine, wait_for_db

from .actions import run_actions, run_datasets, run_reconcilers, validate_open_actions
from .contracts import (
    DbAdminActionResult,
    DbAdminFatalError,
    DbAdminIssue,
    DbAdminMode,
    DbAdminPhase,
    DbAdminResult,
    DbAdminVerdict,
    RequiredColumnTransition,
    SchemaTransitionSet,
)
from .journal import persist_result_best_effort
from .models import DbAdminActionRecord, DbAdminActionRevision, DbAdminIssueRecord, DbAdminRun
from .registry import DbAdminRegistry, registry
from .scope import DbAdminDdlFilters
from .snapshot import compute_transitions, inspect_public_schema
from ._internal.atlas import apply_target
from ._internal.enums import prepare_enum_transitions, validate_enum_transitions
from ._internal.target import (
    load_target_metadata,
    render_target_sql,
    staged_metadata,
    target_fingerprint,
)


_LOCK_KEY = 6_749_151_842_021_806_167
_LOADED_REGISTRIES: WeakSet[DbAdminRegistry] = WeakSet()


def mode_from_environment() -> DbAdminMode:
    if settings.is_dev:
        return DbAdminMode.DEVELOPMENT
    return DbAdminMode.PRODUCTION


def _load_contributions(target_registry: DbAdminRegistry) -> None:
    if target_registry in _LOADED_REGISTRIES:
        return
    modules = importlib.import_module("modules")
    loader = getattr(modules, "load_dbadmin_contributions", None)
    if callable(loader):
        loader(target_registry)
    _LOADED_REGISTRIES.add(target_registry)


async def _bootstrap_journal() -> None:
    """Create only DbAdmin's own journal before developer actions can need it."""

    tables: tuple[Table, ...] = (
        cast(Table, DbAdminRun.__table__),
        cast(Table, DbAdminIssueRecord.__table__),
        cast(Table, DbAdminActionRecord.__table__),
        cast(Table, DbAdminActionRevision.__table__),
    )

    def create(sync_connection: Connection) -> None:
        DbAdminRun.metadata.create_all(sync_connection, tables=list(tables))

    async with engine.begin() as connection:
        await connection.run_sync(create)


async def _acquire_lock(timeout: float = 60.0) -> AsyncConnection:
    connection = await engine.connect()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY}
                )
            )
            if acquired:
                return connection
            if loop.time() >= deadline:
                raise DbAdminFatalError("Timed out waiting for the DbAdmin advisory lock")
            await asyncio.sleep(0.5)
    except BaseException:
        await connection.close()
        raise


async def _release_lock(connection: AsyncConnection) -> None:
    try:
        try:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY}
            )
        except Exception as exc:
            # A lost PostgreSQL session releases its advisory locks itself. Keep the
            # original fatal DbAdmin result instead of replacing it with cleanup noise.
            logger.error("DbAdmin advisory-lock cleanup failed: {}", _safe_error(exc))
    finally:
        try:
            await connection.close()
        except Exception as exc:
            logger.error("DbAdmin connection cleanup failed: {}", _safe_error(exc))


async def _remaining_required_columns(
    target: MetaData,
    transitions: tuple[RequiredColumnTransition, ...],
) -> tuple[RequiredColumnTransition, ...]:
    remaining: list[RequiredColumnTransition] = []
    async with engine.connect() as connection:
        for transition in transitions:
            table = target.tables[transition.table_name]
            column = table.columns[transition.column_name]
            has_null = await connection.scalar(
                select(select(table).where(column.is_(None)).exists())
            )
            if has_null:
                remaining.append(transition)
    return tuple(remaining)


def _verdict(
    issues: tuple[DbAdminIssue, ...],
    remaining: tuple[RequiredColumnTransition, ...],
) -> DbAdminVerdict:
    if any(issue.fatal for issue in issues):
        return DbAdminVerdict.FATAL
    if issues:
        return DbAdminVerdict.DEGRADED
    if remaining:
        return DbAdminVerdict.STAGED
    return DbAdminVerdict.CONVERGED


def _log_result(result: DbAdminResult) -> None:
    for column in result.transitions.required_columns:
        logger.error(
            "DbAdmin non-blocking: {} remains nullable because values are missing; "
            "populate these values, then synchronize again to enforce NOT NULL",
            column.key,
        )
    for issue in result.issues:
        logger.error(
            "DbAdmin issue: phase={} object={} fatal={} error={}",
            issue.phase,
            issue.object_name or "-",
            issue.fatal,
            issue.message,
        )
    logger.info(
        "DbAdmin summary: run={} verdict={} issues={} actions={} staged_columns={}",
        result.run_id,
        result.verdict.value,
        len(result.issues),
        len(result.action_results),
        len(result.transitions.required_columns),
    )


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\x00", "")
    password = settings.POSTGRES_PASSWORD
    if password:
        message = message.replace(password, "***")
    return message[-4_000:]


async def synchronize_database(
    *,
    mode: DbAdminMode | None = None,
    dry_run: bool = False,
    target_registry: DbAdminRegistry = registry,
) -> DbAdminResult:
    """Converge public schema and permanent data without operator interaction."""

    started_at = datetime.now(timezone.utc)
    run_id = str(uuid4())
    resolved_mode = mode or mode_from_environment()
    scope = DbAdminDdlFilters()
    scope.validate()
    canonical_target = load_target_metadata()
    canonical_sql = render_target_sql(canonical_target)
    fingerprint = target_fingerprint(canonical_sql)
    transitions = SchemaTransitionSet()
    action_results: list[DbAdminActionResult] = []
    issues: list[DbAdminIssue] = []
    remaining: tuple[RequiredColumnTransition, ...] = ()
    lock_connection: AsyncConnection | None = None

    try:
        _load_contributions(target_registry)
        await wait_for_db()
        lock_connection = await _acquire_lock()
        async with engine.connect() as connection:
            live = await inspect_public_schema(connection)
        transitions = compute_transitions(live, canonical_target)
        validate_enum_transitions(transitions.enums, target_registry)

        if dry_run:
            expansion_target = staged_metadata(
                canonical_target, transitions.required_columns
            )
            await apply_target(
                render_target_sql(expansion_target), scope=scope, dry_run=True,
                preserve_data=True,
            )
            remaining = transitions.required_columns
        else:
            await _bootstrap_journal()
            issues.extend(await validate_open_actions(target_registry))
            phase_results, phase_issues = await run_actions(
                target_registry, DbAdminPhase.BEFORE_EXPAND, transitions
            )
            action_results.extend(phase_results)
            issues.extend(phase_issues)
            if any(issue.fatal for issue in phase_issues):
                raise DbAdminFatalError(
                    "A required BEFORE_EXPAND action failed; source data is preserved"
                )

            async with engine.begin() as connection:
                await prepare_enum_transitions(
                    connection, transitions.enums, target_registry
                )

            expansion_target = staged_metadata(
                canonical_target, transitions.required_columns
            )
            await apply_target(
                render_target_sql(expansion_target), scope=scope, preserve_data=True
            )

            phase_results, phase_issues = await run_actions(
                target_registry, DbAdminPhase.AFTER_EXPAND, transitions
            )
            action_results.extend(phase_results)
            issues.extend(phase_issues)

            issues.extend(await run_datasets(target_registry))
            issues.extend(await run_reconcilers(target_registry))

            phase_results, phase_issues = await run_actions(
                target_registry, DbAdminPhase.AFTER_DATASET, transitions
            )
            action_results.extend(phase_results)
            issues.extend(phase_issues)

            remaining = await _remaining_required_columns(
                canonical_target, transitions.required_columns
            )
            if not any(issue.fatal for issue in issues):
                contraction_target = staged_metadata(canonical_target, remaining)
                try:
                    await apply_target(
                        render_target_sql(contraction_target), scope=scope,
                        preserve_data=bool(issues or remaining),
                    )
                except DbAdminFatalError as exc:
                    # Expansion already made the required objects available. A
                    # failed tightening/cleanup must not stop the usable app.
                    issues.append(DbAdminIssue("contract", _safe_error(exc), fatal=False))
                    remaining = await _remaining_required_columns(
                        canonical_target, transitions.required_columns
                    )
                if not issues and not remaining:
                    phase_results, phase_issues = await run_actions(
                        target_registry, DbAdminPhase.AFTER_CONTRACT, transitions
                    )
                    action_results.extend(phase_results)
                    issues.extend(phase_issues)
    except Exception as exc:
        message = _safe_error(exc)
        logger.error("DbAdmin fatal synchronization failure: {}", message)
        issues.append(DbAdminIssue("orchestrator", message, fatal=True))
    finally:
        if lock_connection is not None:
            await _release_lock(lock_connection)

    effective_transitions = SchemaTransitionSet(
        added_tables=transitions.added_tables,
        removed_tables=transitions.removed_tables,
        added_columns=transitions.added_columns,
        removed_columns=transitions.removed_columns,
        required_columns=remaining,
        enums=transitions.enums,
        definitions=transitions.definitions,
    )
    result = DbAdminResult(
        run_id=run_id,
        mode=resolved_mode,
        verdict=_verdict(tuple(issues), remaining),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        scope_fingerprint=scope.fingerprint,
        target_fingerprint=fingerprint,
        transitions=effective_transitions,
        action_results=tuple(action_results),
        issues=tuple(issues),
    )
    _log_result(result)
    if not dry_run:
        await persist_result_best_effort(result)
    return result
