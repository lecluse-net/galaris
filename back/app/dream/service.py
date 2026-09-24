"""Lease and state transitions shared by every Dream mechanism."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.sql.elements import ColumnElement

from core import websocket
from core.database import get_db, get_db_session
from core.params import runtime_settings

from .contracts import DreamClaim
from .events import MONITORING_ROOM
from .models import DreamReceipt


_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"


def receipt_correlation_ref(receipt_id: UUID) -> str:
    """Return the stable LLM-trace reference owned by one Dream receipt."""

    return f"dream-receipt:{receipt_id}"


def claim_execution_timeout() -> float:
    """Share the existing Dream execution budget, below its durable lease."""
    return min(
        runtime_settings.DREAM_CLAIM_TIMEOUT_SECONDS,
        max(5.0, float(runtime_settings.DREAM_LEASE_SECONDS) - 60.0),
    )


def _lease_expiry(now: datetime) -> datetime:
    return now + timedelta(seconds=runtime_settings.DREAM_LEASE_SECONDS)


def _claim_from_record(record: DreamReceipt, now: datetime) -> DreamClaim:
    token = uuid4()
    record.status = "running"
    record.attempts += 1
    record.lease_token = token
    record.lease_owner = _WORKER_ID
    record.lease_expires_at = _lease_expiry(now)
    record.last_error = None
    return DreamClaim(
        receipt_id=record.id,
        lease_token=token,
        subject_kind=record.subject_kind,
        subject_id=record.subject_id,
        attempts=record.attempts,
        prepared_payload=(
            dict(record.prepared_payload)
            if record.prepared_payload is not None
            else None
        ),
    )


async def claim_retry(
    mechanism_key: str,
    *,
    eligibility: ColumnElement[bool] | None = None,
) -> DreamClaim | None:
    """Claim an available retry or an expired crash lease before new work."""

    async with get_db_session():
        now = datetime.now(timezone.utc)
        statement = select(DreamReceipt).where(
            DreamReceipt.mechanism_key == mechanism_key,
            DreamReceipt.attempts < runtime_settings.DREAM_MAX_ATTEMPTS,
            or_(
                and_(
                    DreamReceipt.status == "retry",
                    DreamReceipt.available_at <= now,
                ),
                and_(
                    DreamReceipt.status == "running",
                    DreamReceipt.lease_expires_at.is_not(None),
                    DreamReceipt.lease_expires_at <= now,
                ),
            ),
        )
        if eligibility is not None:
            statement = statement.where(eligibility)
        record = await get_db().scalar(
            statement
            .order_by(DreamReceipt.available_at, DreamReceipt.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        return _claim_from_record(record, now)


def unverified_memory_application() -> ColumnElement[bool]:
    """Match a successful extraction whose operations lack complete write proof."""

    prepared_operations = DreamReceipt.prepared_payload["decision"]["operations"]
    applied_operations = DreamReceipt.prepared_payload["application"]["operations"]
    prepared_count = case(
        (
            func.jsonb_typeof(prepared_operations) == "array",
            func.jsonb_array_length(prepared_operations),
        ),
        else_=0,
    )
    applied_count = case(
        (
            func.jsonb_typeof(applied_operations) == "array",
            func.jsonb_array_length(applied_operations),
        ),
        else_=-1,
    )
    return and_(
        DreamReceipt.status == "success",
        prepared_count > 0,
        applied_count != prepared_count,
    )


def replayable_topic_application() -> ColumnElement[bool]:
    """Match a completed direct classification whose assignment can be replayed.

    Reuse decisions and automatic creations assign a Topic during ``apply`` and
    can therefore rebuild a missing subject projection from their durable
    checkpoint. Proposed creations only prove that an approval was requested;
    replaying them would repeatedly notify the user.
    """

    decision_action = DreamReceipt.prepared_payload["decision"]["action"].as_string()
    creation_mode = DreamReceipt.prepared_payload["creation_mode"].as_string()
    return and_(
        DreamReceipt.status == "success",
        DreamReceipt.prepared_payload.is_not(None),
        or_(
            decision_action == "reuse",
            and_(decision_action == "create", creation_mode == "auto"),
        ),
    )


async def claim_unverified_memory_application(
    mechanism_key: str,
    *,
    eligibility: ColumnElement[bool],
) -> DreamClaim | None:
    """Replay legacy success receipts until every operation has durable proof."""

    async with get_db_session():
        now = datetime.now(timezone.utc)
        record = await get_db().scalar(
            select(DreamReceipt)
            .where(
                DreamReceipt.mechanism_key == mechanism_key,
                unverified_memory_application(),
                eligibility,
            )
            .order_by(DreamReceipt.created_at, DreamReceipt.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.attempts = 0
        record.result_count = 0
        return _claim_from_record(record, now)


async def claim_replayable_topic_application(
    mechanism_key: str,
    *,
    subject_kind: str,
    eligibility: ColumnElement[bool],
) -> DreamClaim | None:
    """Replay a checkpointed Topic decision when its SQL assignment vanished."""

    async with get_db_session():
        now = datetime.now(timezone.utc)
        record = await get_db().scalar(
            select(DreamReceipt)
            .where(
                DreamReceipt.mechanism_key == mechanism_key,
                DreamReceipt.subject_kind == subject_kind,
                replayable_topic_application(),
                eligibility,
            )
            .order_by(DreamReceipt.created_at, DreamReceipt.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.attempts = 0
        record.result_count = 0
        return _claim_from_record(record, now)


async def claim_projection_receipt(
    mechanism_key: str,
    *,
    subject_kind: str,
    subject_id: str,
) -> DreamClaim | None:
    """Claim a new deterministic projection or replay a completed one.

    A durable receipt proves that Dream applied a projection at one point in
    time; it does not prove that the rebuildable SQL edge still exists.  A
    completed receipt can therefore be reused when the mechanism has detected
    that its projection is missing.  Active, retrying and terminal-error
    receipts keep their normal lifecycle.
    """

    async with get_db_session():
        now = datetime.now(timezone.utc)
        record = await get_db().scalar(
            select(DreamReceipt)
            .where(
                DreamReceipt.mechanism_key == mechanism_key,
                DreamReceipt.subject_kind == subject_kind,
                DreamReceipt.subject_id == subject_id,
            )
            .with_for_update()
        )
        if record is None:
            claim = create_running_receipt(
                mechanism_key=mechanism_key,
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
            await get_db().flush()
            return claim
        if record.status != "success":
            return None
        record.attempts = 0
        record.prepared_payload = None
        record.result_count = 0
        record.cost = 0.0
        return _claim_from_record(record, now)


async def reconcile_expired_receipts() -> None:
    """Release crash leases and close exhausted work during worker startup."""

    async with get_db_session():
        now = datetime.now(timezone.utc)
        await get_db().execute(
            update(DreamReceipt)
            .where(
                DreamReceipt.status == "running",
                DreamReceipt.lease_expires_at.is_not(None),
                DreamReceipt.lease_expires_at <= now,
            )
            .values(
                status="retry",
                available_at=now,
                lease_token=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error="Recovered after an expired Dream lease.",
            )
        )
        await get_db().execute(
            update(DreamReceipt)
            .where(
                DreamReceipt.status == "retry",
                DreamReceipt.attempts >= runtime_settings.DREAM_MAX_ATTEMPTS,
            )
            .values(
                status="error",
                last_error="Dream attempt budget exhausted after lease recovery.",
            )
        )


def create_running_receipt(
    *,
    mechanism_key: str,
    subject_kind: str,
    subject_id: str,
    prepared_payload: dict[str, Any] | None = None,
) -> DreamClaim:
    """Create and claim a new receipt in the caller's current transaction."""

    now = datetime.now(timezone.utc)
    record = DreamReceipt(
        id=uuid4(),
        mechanism_key=mechanism_key,
        subject_kind=subject_kind,
        subject_id=subject_id,
        status="running",
        attempts=0,
        available_at=now,
        prepared_payload=(dict(prepared_payload) if prepared_payload is not None else None),
    )
    get_db().add(record)
    # SQLAlchemy assigns the UUID default only when the row is flushed.
    claim = _claim_from_record(record, now)
    return claim


async def claim_observed_for_learning(
    mechanism_key: str,
    *,
    subject_kind: str,
) -> DreamClaim | None:
    """Reuse a prepared observe-mode receipt when governed writes become enabled."""

    async with get_db_session():
        now = datetime.now(timezone.utc)
        record = await get_db().scalar(
            select(DreamReceipt)
            .where(
                DreamReceipt.mechanism_key == mechanism_key,
                DreamReceipt.subject_kind == subject_kind,
                DreamReceipt.status == "success",
                DreamReceipt.prepared_payload["application_mode"].as_string()
                == "observe",
            )
            .order_by(DreamReceipt.created_at, DreamReceipt.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        return _claim_from_record(record, now)


async def replace_prepared_payload(
    claim: DreamClaim, payload: dict[str, Any]
) -> None:
    """Replace a prepared checkpoint while retaining the owned lease."""

    async with get_db_session():
        record = await _owned_receipt(claim)
        record.prepared_payload = dict(payload)


async def store_prepared(
    claim: DreamClaim,
    payload: dict[str, Any],
    *,
    cost: float,
) -> None:
    """Durably checkpoint model output before applying domain side effects."""

    async with get_db_session():
        record = await _owned_receipt(claim)
        record.prepared_payload = dict(payload)
        record.cost = float(cost)


async def add_application_cost(claim: DreamClaim, cost: float) -> None:
    """Retain application inference costs, including a failed application attempt."""
    if cost:
        async with get_db_session():
            record = await _owned_receipt(claim)
            record.cost += cost


async def mark_success(claim: DreamClaim, *, result_count: int) -> None:
    async with get_db_session():
        record = await _owned_receipt(claim)
        record.status = "success"
        record.result_count = max(0, int(result_count))
        record.lease_token = None
        record.lease_owner = None
        record.lease_expires_at = None
        record.last_error = None
    await _emit_receipt_update(claim.receipt_id)


async def mark_failure(claim: DreamClaim, exc: BaseException) -> None:
    async with get_db_session():
        record = await _owned_receipt(claim)
        terminal = record.attempts >= runtime_settings.DREAM_MAX_ATTEMPTS
        record.status = "error" if terminal else "retry"
        record.available_at = datetime.now(timezone.utc) + timedelta(
            seconds=min(900.0, 2.0 ** min(record.attempts + 4, 9))
        )
        record.lease_token = None
        record.lease_owner = None
        record.lease_expires_at = None
        record.last_error = f"{type(exc).__name__}: {exc}"[:4_000]
    await _emit_receipt_update(claim.receipt_id)


async def release_interrupted(claim: DreamClaim, reason: str) -> None:
    """Return preempted work to the queue without consuming its failure budget."""

    async with get_db_session():
        record = await _owned_receipt(claim)
        record.status = "retry"
        record.attempts = max(0, record.attempts - 1)
        record.available_at = datetime.now(timezone.utc)
        record.lease_token = None
        record.lease_owner = None
        record.lease_expires_at = None
        record.last_error = reason[:4_000]
    await _emit_receipt_update(claim.receipt_id)


async def _emit_receipt_update(receipt_id: UUID) -> None:
    await websocket.emit(
        "dream",
        "update",
        {"scope": "receipt", "id": str(receipt_id)},
        MONITORING_ROOM,
    )


async def _owned_receipt(claim: DreamClaim) -> DreamReceipt:
    record = await get_db().scalar(
        select(DreamReceipt)
        .where(
            DreamReceipt.id == claim.receipt_id,
            DreamReceipt.status == "running",
            DreamReceipt.lease_token == claim.lease_token,
        )
        .with_for_update()
    )
    if record is None:
        raise RuntimeError("Dream receipt lease was lost.")
    return record


__all__ = [
    "claim_projection_receipt",
    "claim_retry",
    "claim_replayable_topic_application",
    "claim_unverified_memory_application",
    "claim_observed_for_learning",
    "create_running_receipt",
    "mark_failure",
    "mark_success",
    "reconcile_expired_receipts",
    "release_interrupted",
    "receipt_correlation_ref",
    "replayable_topic_application",
    "replace_prepared_payload",
    "store_prepared",
    "unverified_memory_application",
]
