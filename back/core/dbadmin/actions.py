"""Execution and durable tracking of registered DbAdmin contributions."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from core import settings
from core.database import get_db_session

from .contracts import (
    DbAdminActionResult,
    DbAdminActionStatus,
    DbAdminFatalError,
    DbAdminIssue,
    DbAdminPhase,
    SchemaTransitionSet,
)
from .dataset import reconcile_dataset
from .models import DbAdminActionRecord, DbAdminActionRevision
from .registry import DbAdminAction, DbAdminRegistry


def _bounded_error(exc: Exception) -> str:
    message = str(exc).replace("\x00", "")
    if settings.POSTGRES_PASSWORD:
        message = message.replace(settings.POSTGRES_PASSWORD, "***")
    return message[-4_000:]


async def validate_open_actions(registry: DbAdminRegistry) -> tuple[DbAdminIssue, ...]:
    """Never forget an unfinished obligation merely because its code disappeared."""

    registered = {action.key: action for action in registry.actions}
    async with get_db_session() as session:
        open_records = (
            await session.scalars(
                select(DbAdminActionRecord).where(
                    DbAdminActionRecord.status.in_(("running", "deferred", "failed"))
                )
            )
        ).all()
        revisions = {
            (revision.action_key, revision.checksum): revision.required
            for revision in await session.scalars(select(DbAdminActionRevision))
        }
    issues: list[DbAdminIssue] = []
    for record in open_records:
        action = registered.get(record.key)
        if action is not None and (
            action.checksum == record.checksum
            or record.checksum in action.compatible_checksums
        ):
            continue
        message = (
            "Unfinished DbAdmin action is no longer registered"
            if action is None else "Unfinished DbAdmin action changed checksum without declared compatibility"
        )
        # Legacy journals did not retain criticality. A present declaration can
        # identify an optional obligation; a disappeared unknown one stays fatal.
        required = revisions.get((record.key, record.checksum), action.required if action else True)
        if required or (action is not None and action.required):
            raise DbAdminFatalError(f"{message}: {record.key}")
        issues.append(DbAdminIssue("action_validation", message, record.key, fatal=False))
        logger.error("DbAdmin optional action deferred: key={} reason={}", record.key, message)
    return tuple(issues)


async def _record_status(
    action: DbAdminAction,
    status: str,
    *,
    error: str | None = None,
    increment_attempts: bool = False,
) -> None:
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        record = await session.get(DbAdminActionRecord, action.key)
        if record is None:
            record = DbAdminActionRecord(
                key=action.key,
                phase=action.phase.value,
                checksum=action.checksum,
                status=status,
                attempts=1 if increment_attempts else 0,
                last_error=error,
                started_at=now if increment_attempts else None,
                finished_at=now if status in {"applied", "already_satisfied"} else None,
            )
            session.add(record)
            await session.flush()
            session.add(DbAdminActionRevision(
                action_key=action.key, checksum=action.checksum, required=action.required,
            ))
            return
        if record.checksum != action.checksum and record.status not in {
            "applied",
            "already_satisfied",
        } and record.checksum not in action.compatible_checksums:
            raise DbAdminFatalError(
                f"DbAdmin action {action.key!r} changed checksum while unfinished"
            )
        revision = await session.scalar(select(DbAdminActionRevision).where(
            DbAdminActionRevision.action_key == action.key,
            DbAdminActionRevision.checksum == action.checksum,
        ))
        if revision is None:
            session.add(DbAdminActionRevision(
                action_key=action.key, checksum=action.checksum, required=action.required,
            ))
        record.phase = action.phase.value
        record.checksum = action.checksum
        record.status = status
        record.last_error = error
        if increment_attempts:
            record.attempts += 1
            record.started_at = now
        if status in {"applied", "already_satisfied"}:
            record.finished_at = now


async def run_actions(
    registry: DbAdminRegistry,
    phase: DbAdminPhase,
    transitions: SchemaTransitionSet,
) -> tuple[tuple[DbAdminActionResult, ...], tuple[DbAdminIssue, ...]]:
    """Run every applicable action independently and report all failures."""

    results: list[DbAdminActionResult] = []
    issues: list[DbAdminIssue] = []
    async with get_db_session() as session:
        unfinished = {
            record.key: record
            for record in await session.scalars(
                select(DbAdminActionRecord).where(
                    DbAdminActionRecord.status.in_(("running", "deferred", "failed")),
                )
            )
        }
    for action in (item for item in registry.actions if item.phase is phase):
        # A schema delta is transient evidence: after Atlas successfully expands the schema it
        # disappears on the next process start. The durable action journal therefore keeps every
        # unfinished obligation applicable until its postcondition is proven, including after a
        # crash or a failed handler transaction.
        if not action.predicate(transitions) and action.key not in unfinished:
            continue
        previous = unfinished.get(action.key)
        if previous is not None and previous.checksum != action.checksum and previous.checksum not in action.compatible_checksums:
            # validate_open_actions reports the mismatch and protects contraction.
            # Never run changed code against an incompatible partial transformation.
            message = "checksum changed without declared compatibility; source data preserved"
            results.append(DbAdminActionResult(action.key, phase, DbAdminActionStatus.DEFERRED, message))
            issues.append(DbAdminIssue(phase.value, message, action.key, fatal=action.required))
            continue
        try:
            async with get_db_session() as session:
                satisfied = await action.postcondition(session, transitions)
            if satisfied:
                await _record_status(action, "already_satisfied")
                results.append(
                    DbAdminActionResult(
                        action.key,
                        phase,
                        DbAdminActionStatus.ALREADY_SATISFIED,
                    )
                )
                continue

            await _record_status(action, "running", increment_attempts=True)
            async with get_db_session() as session:
                await action.handler(session, transitions)
                satisfied = await action.postcondition(session, transitions)
            if not satisfied:
                await _record_status(
                    action,
                    "deferred",
                    error="postcondition not satisfied",
                )
                results.append(
                    DbAdminActionResult(
                        action.key,
                        phase,
                        DbAdminActionStatus.DEFERRED,
                        "postcondition not satisfied",
                    )
                )
                issues.append(
                    DbAdminIssue(
                        phase.value,
                        "postcondition not satisfied",
                        action.key,
                        fatal=False,
                    )
                )
                continue
            await _record_status(action, "applied")
            results.append(
                DbAdminActionResult(
                    action.key,
                    phase,
                    DbAdminActionStatus.APPLIED,
                )
            )
        except Exception as exc:
            message = _bounded_error(exc)
            logger.error(
                "DbAdmin action failed: phase={} key={} error={}",
                phase.value,
                action.key,
                message,
            )
            try:
                await _record_status(action, "failed", error=message)
            except Exception as persist_exc:
                logger.error(
                    "Could not persist failed DbAdmin action {}: {}",
                    action.key,
                    _bounded_error(persist_exc),
                )
            results.append(
                DbAdminActionResult(
                    action.key,
                    phase,
                    DbAdminActionStatus.FAILED,
                    message,
                )
            )
            issues.append(
                DbAdminIssue(phase.value, message, action.key, fatal=action.required)
            )
    return tuple(results), tuple(issues)


async def run_datasets(
    registry: DbAdminRegistry,
) -> tuple[DbAdminIssue, ...]:
    """Run permanent dataset reconcilers independently in deterministic order."""

    issues: list[DbAdminIssue] = []
    for dataset in registry.datasets:
        try:
            async with get_db_session() as session:
                result = await reconcile_dataset(session, dataset)
                logger.info(
                    "DbAdmin dataset result: key={} inserted={} updated={} "
                    "restored={} removed={}",
                    dataset.key,
                    result.inserted,
                    result.updated,
                    result.restored,
                    result.removed,
                )
            logger.info("DbAdmin dataset converged: {}", dataset.key)
        except Exception as exc:
            message = _bounded_error(exc)
            logger.error(
                "DbAdmin dataset failed: {} error={}", dataset.key, message
            )
            issues.append(
                DbAdminIssue(
                    "dataset",
                    message,
                    dataset.key,
                    fatal=dataset.required,
                )
            )
    return tuple(issues)


async def run_reconcilers(
    registry: DbAdminRegistry,
) -> tuple[DbAdminIssue, ...]:
    """Run derived-state reconcilers after every authoritative dataset."""

    issues: list[DbAdminIssue] = []
    for reconciler in registry.reconcilers:
        try:
            async with get_db_session() as session:
                await reconciler.handler(session)
            logger.info("DbAdmin reconciler converged: {}", reconciler.key)
        except Exception as exc:
            message = _bounded_error(exc)
            logger.error(
                "DbAdmin reconciler failed: {} error={}", reconciler.key, message
            )
            issues.append(
                DbAdminIssue(
                    "reconciler",
                    message,
                    reconciler.key,
                    fatal=reconciler.required,
                )
            )
    return tuple(issues)
