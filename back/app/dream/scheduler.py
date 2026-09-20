"""Single sequential trigger for every opportunistic Dream mechanism."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.llm import llm_correlation_scope, llm_execution_scope
from app.task import has_active_task_work
from app.voice import (
    has_active_voice_calls,
    register_voice_activity_listener,
    unregister_voice_activity_listener,
)
from core import websocket
from core.params import runtime_settings

from .contracts import (
    DreamClaim,
    DreamMechanism,
    DreamRuntimePhase,
    DreamRuntimeReason,
    DreamRuntimeSnapshot,
    DreamRuntimeStatus,
)
from .events import MONITORING_ROOM
from .registry import mechanisms, register_default_mechanisms
from .service import (
    mark_failure,
    mark_success,
    reconcile_expired_receipts,
    receipt_correlation_ref,
    release_interrupted,
    store_prepared,
)


_worker_task: asyncio.Task[None] | None = None
_runtime_update_task: asyncio.Task[None] | None = None
_runtime_update_pending = False
_current_work: asyncio.Task[None] | None = None
_current_mechanism: str | None = None
_current_claim: DreamClaim | None = None
_last_cycle_at: datetime | None = None
_last_cycle_finished_at: datetime | None = None
_next_cycle_at: datetime | None = None
_state_changed_at: datetime | None = None
_cycle_count = 0
_last_error_type: str | None = None
_runtime_status: DreamRuntimeStatus = "stopped"
_runtime_phase: DreamRuntimePhase = "stopped"
_runtime_reason: DreamRuntimeReason = "not_started"
_wake_event: asyncio.Event | None = None
_worker_started_event: asyncio.Event | None = None
_stopping = False
_next_mechanism_index = 0
_MESSAGE_TOPIC_KEY = "topic.classify_message"
_TASK_TOPIC_KEY = "topic.classify_task"


def _ordered_mechanisms(
    registered: tuple[DreamMechanism, ...], start_index: int
) -> list[DreamMechanism]:
    """Rotate fairly while preserving Message Topic precedence over Task Topic."""

    if not registered:
        return []
    normalized_start = start_index % len(registered)
    ordered = list(registered[normalized_start:] + registered[:normalized_start])
    message_index = next(
        (index for index, item in enumerate(ordered) if item.key == _MESSAGE_TOPIC_KEY),
        None,
    )
    task_index = next(
        (index for index, item in enumerate(ordered) if item.key == _TASK_TOPIC_KEY),
        None,
    )
    if message_index is None or task_index is None or message_index < task_index:
        return ordered
    message_mechanism = ordered[message_index]
    ordered.remove(message_mechanism)
    task_index = next(
        index for index, item in enumerate(ordered) if item.key == _TASK_TOPIC_KEY
    )
    ordered.insert(task_index, message_mechanism)
    return ordered


def _set_runtime_state(
    *,
    status: DreamRuntimeStatus,
    phase: DreamRuntimePhase,
    reason: DreamRuntimeReason,
    next_cycle_at: datetime | None = None,
    last_error_type: str | None = None,
) -> None:
    """Publish a cheap, process-local snapshot for monitoring."""

    global _last_error_type, _next_cycle_at, _runtime_phase
    global _runtime_reason, _runtime_status, _state_changed_at
    changed = (
        status != _runtime_status
        or phase != _runtime_phase
        or reason != _runtime_reason
        or next_cycle_at != _next_cycle_at
        or last_error_type != _last_error_type
    )
    _runtime_status = status
    _runtime_phase = phase
    _runtime_reason = reason
    _next_cycle_at = next_cycle_at
    _last_error_type = last_error_type
    if changed:
        _state_changed_at = datetime.now(timezone.utc)
        logger.debug(
            "Dream runtime state status={} phase={} reason={}",
            status,
            phase,
            reason,
        )
        # The synchronous snapshot remains current through every internal phase.
        # Clients only need invalidation at an externally useful state boundary.
        if phase in {"waiting", "faulted", "starting", "stopped", "applying"}:
            _schedule_runtime_update()


def _schedule_runtime_update() -> None:
    """Coalesce state invalidations; slow clients cannot grow a task backlog."""

    global _runtime_update_task, _runtime_update_pending
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _runtime_update_pending = True
    if _runtime_update_task is None or _runtime_update_task.done():
        _runtime_update_task = loop.create_task(
            _emit_runtime_updates(), name="dream-runtime-websocket"
        )


async def _emit_runtime_updates() -> None:
    global _runtime_update_pending
    while _runtime_update_pending:
        _runtime_update_pending = False
        try:
            await websocket.emit("dream", "update", {"scope": "runtime"}, MONITORING_ROOM)
        except Exception:
            logger.exception("Dream runtime notification failed")


def _on_voice_activity(active: bool) -> None:
    """Preempt background inference synchronously when a call becomes active."""

    if active:
        _set_runtime_state(
            status="paused_voice",
            phase="waiting",
            reason="voice_active",
        )
        current = _current_work
        if current is not None and not current.done():
            current.cancel()
    event = _wake_event
    if event is not None:
        event.set()


async def run_cycle() -> int:
    """Run at most one operation, rotating fairly across mechanisms."""

    global _current_claim, _current_mechanism, _current_work, _cycle_count
    global _last_cycle_at, _last_cycle_finished_at, _next_mechanism_index
    _last_cycle_at = datetime.now(timezone.utc)
    _cycle_count += 1
    _set_runtime_state(
        status="idle",
        phase="checking",
        reason="checking_activity",
    )
    try:
        if not runtime_settings.DREAM_ENABLED:
            _set_runtime_state(
                status="disabled",
                phase="waiting",
                reason="disabled",
            )
            return 0
        if has_active_voice_calls():
            _set_runtime_state(
                status="paused_voice",
                phase="waiting",
                reason="voice_active",
            )
            return 0
        if await has_active_task_work():
            _set_runtime_state(
                status="paused_tasks",
                phase="waiting",
                reason="task_active",
            )
            return 0

        registered_mechanisms = mechanisms()
        mechanism_count = len(registered_mechanisms)
        start_index = (
            _next_mechanism_index % mechanism_count
            if mechanism_count
            else 0
        )
        ordered_mechanisms = _ordered_mechanisms(
            registered_mechanisms,
            start_index,
        )
        completed = 0
        available_mechanisms = 0
        for mechanism in ordered_mechanisms:
            if has_active_voice_calls():
                _set_runtime_state(
                    status="paused_voice",
                    phase="waiting",
                    reason="voice_active",
                )
                break
            if await has_active_task_work():
                _set_runtime_state(
                    status="paused_tasks",
                    phase="waiting",
                    reason="task_active",
                )
                break
            _current_mechanism = mechanism.key
            _set_runtime_state(
                status="idle",
                phase="checking",
                reason="checking_mechanism",
            )
            if not await mechanism.is_available():
                _current_mechanism = None
                continue
            available_mechanisms += 1
            _set_runtime_state(
                status="idle",
                phase="claiming",
                reason="claiming_subject",
            )
            claim = await mechanism.claim_one()
            if claim is None:
                _current_mechanism = None
                continue
            _next_mechanism_index = (
                registered_mechanisms.index(mechanism) + 1
            ) % mechanism_count
            _current_claim = claim
            _current_work = asyncio.create_task(
                _run_claim(mechanism, claim),
                name=f"dream:{mechanism.key}:{claim.subject_id}",
            )
            try:
                await _current_work
            finally:
                _current_work = None
                _current_mechanism = None
                _current_claim = None
            completed += 1
            break

        if _runtime_status not in ("paused_voice", "paused_tasks", "faulted"):
            if completed:
                _set_runtime_state(
                    status="idle",
                    phase="waiting",
                    reason="cycle_completed",
                )
            elif available_mechanisms:
                _set_runtime_state(
                    status="idle",
                    phase="waiting",
                    reason="no_eligible_subject",
                )
            else:
                _set_runtime_state(
                    status="unavailable",
                    phase="waiting",
                    reason="mechanism_unavailable",
                )
        return completed
    finally:
        _last_cycle_finished_at = datetime.now(timezone.utc)


def _claim_timeout() -> float:
    """Claim execution budget clamped below the lease so the lease cannot
    expire while a healthy claim is still applying in another worker."""

    return min(
        runtime_settings.DREAM_CLAIM_TIMEOUT_SECONDS,
        max(5.0, float(runtime_settings.DREAM_LEASE_SECONDS) - 60.0),
    )


async def _run_claim(mechanism: DreamMechanism, claim: DreamClaim) -> None:
    phase: str = "preparing"
    try:
        payload = claim.prepared_payload
        if payload is None or payload.get("_dream_stage") == "evidence":
            _set_runtime_state(
                status="running",
                phase="preparing",
                reason="preparing_subject",
            )
            async with asyncio.timeout(_claim_timeout()):
                with llm_correlation_scope(receipt_correlation_ref(claim.receipt_id)):
                    with llm_execution_scope(
                        source_kind=claim.subject_kind,
                        source_id=claim.subject_id,
                        messenger_origin=claim.subject_kind in {"message", "conversation_round"},
                    ):
                        prepared = await mechanism.prepare(claim)
                payload = prepared.payload
                await store_prepared(claim, payload, cost=prepared.cost)
        if has_active_voice_calls():
            await release_interrupted(claim, "Interrupted by active Voice conversation.")
            return
        _set_runtime_state(
            status="running",
            phase="applying",
            reason="applying_subject",
        )
        phase = "applying"
        async with asyncio.timeout(_claim_timeout()):
            result_count = await mechanism.apply(claim, payload)
            await mark_success(claim, result_count=result_count)
        if mechanism.key == "memory.maintain_findings" and result_count == 0:
            # Scanning an unchanged item cannot affect graph membership. During
            # reindexing, these no-ops otherwise each trigger a global vector scan.
            return
        try:
            from app.memory.automation import enqueue_dream_link_reconciliation

            await enqueue_dream_link_reconciliation(
                mechanism_key=mechanism.key,
                subject_kind=claim.subject_kind,
                subject_id=claim.subject_id,
                payload=payload,
            )
        except Exception:
            # The daily Memory sweep repairs a missed notification. A link job
            # must never turn an already-applied Dream effect into a failure.
            logger.exception(
                "Could not enqueue post-Dream memory-link reconciliation "
                "mechanism={} subject={}:{}",
                mechanism.key,
                claim.subject_kind,
                claim.subject_id,
            )
    except asyncio.CancelledError:
        await asyncio.shield(
            release_interrupted(claim, "Preempted by foreground activity.")
        )
        if _stopping:
            raise
    except TimeoutError:
        # A claim phase ran past its hard budget on an unbounded await.
        # Fail the receipt instead of wedging the single sequential worker.
        _set_runtime_state(
            status="faulted",
            phase="faulted",
            reason="worker_error",
            last_error_type="ClaimTimeout",
        )
        logger.error(
            "Dream claim timed out after {:.0f}s mechanism={} phase={} subject={}:{} receipt={}",
            _claim_timeout(),
            mechanism.key,
            phase,
            claim.subject_kind,
            claim.subject_id,
            claim.receipt_id,
        )
        try:
            # Shielded: if the failure transition itself hangs (e.g. a held
            # row lock), detach it and keep cycling. An unreleased running
            # receipt is reclaimed through its lease expiry.
            await asyncio.wait_for(
                asyncio.shield(
                    mark_failure(claim, TimeoutError("Dream claim timed out."))
                ),
                timeout=_claim_timeout(),
            )
        except Exception:
            logger.exception(
                "Dream claim timeout recovery failed mechanism={} subject={}:{} receipt={}",
                mechanism.key,
                claim.subject_kind,
                claim.subject_id,
                claim.receipt_id,
            )
    except Exception as exc:
        _set_runtime_state(
            status="faulted",
            phase="faulted",
            reason="worker_error",
            last_error_type=type(exc).__name__,
        )
        logger.exception(
            "Dream mechanism failed mechanism={} subject={}:{}",
            mechanism.key,
            claim.subject_kind,
            claim.subject_id,
        )
        await mark_failure(claim, exc)


async def _worker() -> None:
    global _last_cycle_finished_at
    started = _worker_started_event
    if started is not None:
        started.set()
    try:
        while True:
            try:
                completed = await run_cycle()
                await _wait_for_next_cycle(
                    full_operation_delay=completed > 0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _last_cycle_finished_at = datetime.now(timezone.utc)
                _set_runtime_state(
                    status="faulted",
                    phase="faulted",
                    reason="worker_error",
                    last_error_type=type(exc).__name__,
                )
                logger.exception("Dream scheduler iteration failed")
                await _wait_for_next_cycle(full_operation_delay=False)
    finally:
        if not _stopping:
            _set_runtime_state(
                status="stopped",
                phase="stopped",
                reason="not_started",
            )


async def _wait_for_next_cycle(*, full_operation_delay: bool) -> None:
    deadline = datetime.now(timezone.utc) + timedelta(
        seconds=runtime_settings.DREAM_POLL_SECONDS
    )
    _set_runtime_state(
        status=_runtime_status,
        phase="waiting",
        reason=_runtime_reason,
        next_cycle_at=deadline,
        last_error_type=_last_error_type,
    )
    if full_operation_delay:
        await asyncio.sleep(runtime_settings.DREAM_POLL_SECONDS)
        return
    event = _wake_event
    if event is None:
        await asyncio.sleep(runtime_settings.DREAM_POLL_SECONDS)
        return
    event.clear()
    try:
        await asyncio.wait_for(
            event.wait(),
            timeout=runtime_settings.DREAM_POLL_SECONDS,
        )
    except asyncio.TimeoutError:
        pass


async def start() -> None:
    global _worker_started_event, _worker_task, _wake_event, _stopping
    if _worker_task is not None and not _worker_task.done():
        return
    register_default_mechanisms()
    await reconcile_expired_receipts()
    _stopping = False
    _wake_event = asyncio.Event()
    _worker_started_event = asyncio.Event()
    _set_runtime_state(
        status="starting",
        phase="starting",
        reason="startup",
    )
    register_voice_activity_listener(_on_voice_activity)
    _worker_task = asyncio.create_task(_worker(), name="dream-scheduler")
    try:
        await asyncio.wait_for(_worker_started_event.wait(), timeout=1.0)
    except TimeoutError:
        _worker_task.cancel()
        await asyncio.gather(_worker_task, return_exceptions=True)
        _worker_task = None
        _set_runtime_state(
            status="faulted",
            phase="faulted",
            reason="worker_error",
            last_error_type="StartupTimeout",
        )
        raise RuntimeError("Dream worker did not start within one second.")
    logger.info("Dream scheduler started mechanisms={}", len(mechanisms()))


async def stop() -> None:
    global _worker_started_event, _worker_task, _current_work, _wake_event, _stopping
    global _runtime_update_task, _runtime_update_pending
    _stopping = True
    _set_runtime_state(
        status="stopped",
        phase="stopped",
        reason="stopping",
    )
    unregister_voice_activity_listener(_on_voice_activity)
    current = _current_work
    if current is not None and not current.done():
        current.cancel()
        await asyncio.gather(current, return_exceptions=True)
    _current_work = None
    worker = _worker_task
    _worker_task = None
    _worker_started_event = None
    _wake_event = None
    if worker is not None:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    _set_runtime_state(
        status="stopped",
        phase="stopped",
        reason="not_started",
    )
    notification = _runtime_update_task
    _runtime_update_task = None
    _runtime_update_pending = False
    if notification is not None:
        notification.cancel()
        await asyncio.gather(notification, return_exceptions=True)
    logger.info("Dream scheduler stopped")


def is_running() -> bool:
    return (
        _worker_task is not None
        and not _worker_task.done()
        and _worker_started_event is not None
        and _worker_started_event.is_set()
    )


async def runtime_snapshot() -> DreamRuntimeSnapshot:
    """Return the scheduler's process-local state without DB or model work."""

    worker_running = is_running()
    current = _current_claim
    return DreamRuntimeSnapshot(
        status=_runtime_status,
        phase=_runtime_phase,
        reason=_runtime_reason,
        worker_running=worker_running,
        current_mechanism=_current_mechanism,
        current_subject_kind=current.subject_kind if current is not None else None,
        current_subject_id=current.subject_id if current is not None else None,
        last_cycle_at=_last_cycle_at,
        last_cycle_finished_at=_last_cycle_finished_at,
        next_cycle_at=_next_cycle_at,
        state_changed_at=_state_changed_at,
        cycle_count=_cycle_count,
        last_error_type=_last_error_type,
    )


__all__ = ["is_running", "run_cycle", "runtime_snapshot", "start", "stop"]
