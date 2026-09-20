"""Watchdog around Dream claim phases: a hung phase fails the receipt instead
of wedging the single sequential worker on an unbounded await."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.dream import scheduler
from app.dream.contracts import DreamClaim, DreamPrepared
from app.dream.models import DreamReceipt
from app.dream.registry import register_mechanism, reset_registry
from app.dream.service import claim_retry


class _HangingMechanism:
    """Mechanism whose prepare or apply blocks until cancelled by the watchdog."""

    def __init__(
        self,
        *,
        key: str,
        claim: DreamClaim,
        hang_phase: Literal["prepare", "apply"],
    ) -> None:
        self.key = key
        self._claim = claim
        self._hang_phase = hang_phase
        self.phase_started = asyncio.Event()
        self.phase_cancelled = asyncio.Event()

    async def is_available(self) -> bool:
        return True

    async def count_pending(self) -> int:
        return 1

    async def claim_one(self) -> DreamClaim | None:
        return self._claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        del claim
        if self._hang_phase == "prepare":
            await self._hang()
        return DreamPrepared(payload={})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim, payload
        if self._hang_phase == "apply":
            await self._hang()
        return 0

    async def _hang(self) -> None:
        self.phase_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.phase_cancelled.set()


async def _running_receipt(
    db: AsyncSession,
    *,
    mechanism_key: str,
    lease_expires_at: datetime | None = None,
) -> tuple[DreamReceipt, DreamClaim]:
    """Persist an owned running receipt whose claim matches its lease."""
    now = datetime.now(timezone.utc)
    token = uuid4()
    receipt = DreamReceipt(
        id=uuid4(),
        mechanism_key=mechanism_key,
        subject_kind="test",
        subject_id=str(uuid4()),
        status="running",
        attempts=1,
        available_at=now,
        lease_token=token,
        lease_owner="test-worker",
        lease_expires_at=lease_expires_at or now + timedelta(seconds=600),
    )
    db.add(receipt)
    await db.flush()
    claim = DreamClaim(
        receipt_id=receipt.id,
        lease_token=token,
        subject_kind="test",
        subject_id=receipt.subject_id,
        attempts=1,
        prepared_payload=None,
    )
    return receipt, claim


def _pump(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mechanism: _HangingMechanism,
) -> None:
    """Point the scheduler at one hanging mechanism with a tiny claim budget."""
    register_mechanism(mechanism)
    monkeypatch.setattr(scheduler.runtime_settings, "DREAM_ENABLED", True)
    monkeypatch.setattr(scheduler, "_claim_timeout", lambda: 0.1)
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)

    async def no_task_work() -> bool:
        return False

    monkeypatch.setattr(scheduler, "has_active_task_work", no_task_work)


def test_claim_timeout_clamps_below_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = scheduler.runtime_settings
    monkeypatch.setattr(rt, "DREAM_CLAIM_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(rt, "DREAM_LEASE_SECONDS", 600)
    assert scheduler._claim_timeout() == 300.0  # pyright: ignore[reportPrivateUsage]

    # Far above the lease: clamped to lease minus the 60 s safety margin.
    monkeypatch.setattr(rt, "DREAM_CLAIM_TIMEOUT_SECONDS", 5_000.0)
    monkeypatch.setattr(rt, "DREAM_LEASE_SECONDS", 120)
    assert scheduler._claim_timeout() == 60.0  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(rt, "DREAM_LEASE_SECONDS", 100)
    assert scheduler._claim_timeout() == 40.0  # pyright: ignore[reportPrivateUsage]

    # Never below the minimum so a healthy claim keeps a fair chance.
    monkeypatch.setattr(rt, "DREAM_LEASE_SECONDS", 60)
    assert scheduler._claim_timeout() == 5.0  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_hanging_apply_is_cancelled_and_failed(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, claim = await _running_receipt(db, mechanism_key="test.hang_apply")
    claim = DreamClaim(
        receipt_id=claim.receipt_id,
        lease_token=claim.lease_token,
        subject_kind=claim.subject_kind,
        subject_id=claim.subject_id,
        attempts=claim.attempts,
        prepared_payload={},
    )
    mechanism = _HangingMechanism(
        key="test.hang_apply",
        claim=claim,
        hang_phase="apply",
    )
    _pump(monkeypatch, mechanism=mechanism)
    try:
        completed = await scheduler.run_cycle()
    finally:
        reset_registry()

    # mark_failure ran in its own session; reload the row it transitioned.
    await db.refresh(receipt)
    assert completed == 1
    assert mechanism.phase_started.is_set()
    # The watchdog cancelled the hung phase instead of wedging the worker.
    assert mechanism.phase_cancelled.is_set()
    assert scheduler._last_error_type == "ClaimTimeout"  # pyright: ignore[reportPrivateUsage]
    assert receipt.status == "retry"
    assert receipt.lease_token is None
    assert receipt.lease_owner is None
    assert receipt.attempts == 1
    assert receipt.last_error is not None
    assert "TimeoutError" in receipt.last_error
    assert receipt.available_at > datetime.now(timezone.utc)

    # The worker keeps cycling: a follow-up cycle completes with no registry.
    assert await scheduler.run_cycle() == 0


@pytest.mark.asyncio
async def test_hanging_prepare_is_cancelled_and_failed(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, claim = await _running_receipt(db, mechanism_key="test.hang_prepare")
    mechanism = _HangingMechanism(
        key="test.hang_prepare",
        claim=claim,
        hang_phase="prepare",
    )
    _pump(monkeypatch, mechanism=mechanism)
    try:
        completed = await scheduler.run_cycle()
    finally:
        reset_registry()

    await db.refresh(receipt)
    assert completed == 1
    assert mechanism.phase_cancelled.is_set()
    assert scheduler._last_error_type == "ClaimTimeout"  # pyright: ignore[reportPrivateUsage]
    assert receipt.status == "retry"
    assert receipt.lease_token is None
    assert receipt.last_error is not None
    assert "TimeoutError" in receipt.last_error


@pytest.mark.asyncio
async def test_claim_timeout_survives_hanging_failure_recovery(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A held row lock can hang the failure transition itself; the recovery
    # wrap must detach and let the lease expiry reclaim the receipt.
    receipt, claim = await _running_receipt(
        db,
        mechanism_key="test.hang_recovery",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    claim = DreamClaim(
        receipt_id=claim.receipt_id,
        lease_token=claim.lease_token,
        subject_kind=claim.subject_kind,
        subject_id=claim.subject_id,
        attempts=claim.attempts,
        prepared_payload={},
    )
    mechanism = _HangingMechanism(
        key="test.hang_recovery",
        claim=claim,
        hang_phase="apply",
    )
    release = asyncio.Event()

    async def hanging_failure(_claim: DreamClaim, _exc: BaseException) -> None:
        await release.wait()

    monkeypatch.setattr(scheduler, "mark_failure", hanging_failure)
    _pump(monkeypatch, mechanism=mechanism)
    try:
        completed = await scheduler.run_cycle()
        assert completed == 1
        assert mechanism.phase_cancelled.is_set()
        assert scheduler._last_error_type == "ClaimTimeout"  # pyright: ignore[reportPrivateUsage]
        # The detached recovery never owned the receipt transition.
        assert receipt.status == "running"
        assert receipt.lease_token is not None
    finally:
        release.set()
        reset_registry()
        # Let the shielded failure task finish before the loop closes.
        await asyncio.sleep(0)

    # The expired lease is reclaimed by the next mechanism claim.
    reclaimed = await claim_retry("test.hang_recovery")
    assert reclaimed is not None
    assert reclaimed.receipt_id == receipt.id
    assert reclaimed.attempts == 2
