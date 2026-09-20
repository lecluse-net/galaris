"""Durable task scheduler.

The scheduler keeps no domain state in memory. It reads the next action from PostgreSQL,
executes one step, and repeats. Persisted phases are sufficient to recover after a reload
or process crash.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

from loguru import logger
import logfire
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.params import runtime_settings
from core.database import get_db, get_db_session
from core.i18n import default_language, is_supported, render_prompt, t
from app.agent.contracts import ReasoningDegenerationError, StaleAgentRunError
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus
from app.task.agent_slot import try_lock_agent
from .startup_timing import CLAIMED_AT_DATA_KEY, STARTUP_TIMING_DATA_KEY, startup_timing
from app.task.workflow import (
    TaskAction,
    TaskEvent,
    scheduler_action,
    transition,
)


_POLL_INTERVAL = 2.0
# Backstop for suspended parents after a lost wake-up or crash.
_RECONCILE_INTERVAL = 15.0
_last_reconcile = 0.0
_last_lease_recovery = 0.0
_scheduler_task: asyncio.Task[None] | None = None
_wake_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None
_running: dict[UUID, asyncio.Task[None]] = {}
_running_agents: dict[UUID, int] = {}  # task_id -> agent_id for running actions
_activity_events: dict[UUID, asyncio.Event] = {}


@dataclass(frozen=True)
class _PeriodicJob:
    callback: Callable[[], Awaitable[object]]
    interval: float
    timeout: float


_periodic_jobs: dict[str, _PeriodicJob] = {}
_periodic_duration = logfire.metric_histogram("scheduler_periodic_duration_seconds", unit="s")
_periodic_outcomes = logfire.metric_counter("scheduler_periodic_runs_total")
_queue_wait = logfire.metric_histogram("task_initial_queue_wait_upper_bound_seconds", unit="s")
_preparation_duration = logfire.metric_histogram("task_objective_preparation_seconds", unit="s")
_admission_duration = logfire.metric_histogram("task_admission_seconds", unit="s")
_periodic_last_run: dict[str, float] = {}
_periodic_running: dict[str, asyncio.Task[None]] = {}
_fast_path: deque[UUID] = deque()
_fast_path_ids: set[UUID] = set()
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"

ClaimedTask = tuple[UUID, TaskStatus, int, int, UUID]


def notify_task_activity(task_id: UUID) -> None:
    """Reset the local stall watchdog after durable progress was committed."""

    event = _activity_events.get(task_id)
    if event is not None:
        event.set()


def _task_language(task: Task) -> str:
    """Return the durable language stored on a task."""

    data = task.data if isinstance(task.data, dict) else {}
    raw = str(data.get("language") or "").strip().lower()
    return raw if is_supported(raw) else default_language()


def _task_message(task: Task, key: str, **values: Any) -> str:
    """Render a scheduler message in the task's durable language."""

    return render_prompt(t(f"task_scheduler.{key}", _task_language(task)), **values)


class LeaseLostError(RuntimeError):
    """The lease was removed or durable cancellation was requested."""


class InlineClaimUnavailable(RuntimeError):
    """An interactive caller could not reserve a task for immediate execution."""


_NETWORK_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "name or service not known",
    "dns",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "connection aborted",
    "client disconnected",
    "peer closed connection",
    "incomplete chunked read",
    "deconnect",  # Covers localized variants of “disconnected”.
    "server disconnected",
    "connecterror",
    "connecttimeout",
    "remoteprotocolerror",
    "readerror",
    "readtimeout",
    "pooltimeout",
    "http 502",
    "http 503",
    "http 504",
)
_RETRY_TRACE_ONLY_TOOLS = frozenset(
    {"approval", "budget_guard", "final_result", "thinking"}
)


def _is_network_failure(error: str) -> bool:
    """Return whether a transport failure warrants the longer retry window."""

    normalized = error.lower()
    return any(marker in normalized for marker in _NETWORK_ERROR_MARKERS)


def _retry_policy(error: str, consecutive_failures: int) -> tuple[int, float, bool]:
    """Return ``(max_attempts, delay, is_network)`` for the current failure."""

    network = _is_network_failure(error)
    max_attempts = (
        runtime_settings.TASK_NETWORK_MAX_ATTEMPTS
        if network
        else runtime_settings.TASK_ACTION_MAX_ATTEMPTS
    )
    base = (
        runtime_settings.TASK_NETWORK_RETRY_BASE_SECONDS
        if network
        else runtime_settings.TASK_ACTION_RETRY_BASE_SECONDS
    )
    cap = runtime_settings.TASK_NETWORK_RETRY_MAX_SECONDS if network else 300.0
    delay = float(
        min(base * (2 ** max(0, consecutive_failures - 1)), cap)
    )
    return max_attempts, delay, network


def start() -> None:
    """Start the scheduling loop if it is not already running."""
    global _scheduler_task, _wake_event, _loop
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _loop = asyncio.get_running_loop()
    _wake_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_run_loop(), name="task-scheduler")
    logger.info("Task scheduler started")


def is_running() -> bool:
    """Return whether the scheduler root loop is alive."""
    return _scheduler_task is not None and not _scheduler_task.done()


def register_periodic_job(
    name: str,
    callback: Callable[[], Awaitable[object]],
    *,
    interval: float,
    timeout: float = 900.0,
) -> None:
    """Host an application maintenance callback in the existing loop.

    Registration is idempotent and the callback receives its own database session. It runs in
    a separate asyncio task so network-bound outbox work never blocks agent scheduling.
    """
    if timeout <= 0:
        raise ValueError("A periodic job timeout must be positive")
    _periodic_jobs[name] = _PeriodicJob(callback, max(0.5, float(interval)), timeout)


def unregister_periodic_job(name: str) -> None:
    _periodic_jobs.pop(name, None)
    _periodic_last_run.pop(name, None)


async def stop() -> None:
    """Stop the scheduling loop cleanly."""
    global _scheduler_task, _wake_event, _loop
    task = _scheduler_task
    _scheduler_task = None
    _wake_event = None
    _loop = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    for running_task in list(_running.values()):
        running_task.cancel()
    for periodic_task in list(_periodic_running.values()):
        periodic_task.cancel()
    if _running:
        await asyncio.gather(*_running.values(), return_exceptions=True)
    _running.clear()
    _running_agents.clear()
    if _periodic_running:
        await asyncio.gather(*_periodic_running.values(), return_exceptions=True)
    _periodic_running.clear()
    _fast_path.clear()
    _fast_path_ids.clear()
    logger.info("Task scheduler stopped")


def wake(
    task_id: UUID | str | None = None,
    *,
    delay: float = 0.0,
    fast: bool = False,
) -> None:
    """Wake the scheduler from any async or thread context.

    ``fast=True`` puts the task in an in-memory priority queue for interactive RUN actions and
    conversation replies that should precede background work.
    """
    loop = _loop
    if loop is None or loop.is_closed():
        return

    task_uuid = UUID(str(task_id)) if task_id is not None else None

    def _wake() -> None:
        if fast and task_uuid is not None:
            _queue_fast_path(task_uuid)
        _set_wake()

    if delay > 0:
        loop.call_soon_threadsafe(loop.call_later, delay, _wake)
    else:
        loop.call_soon_threadsafe(_wake)


def _queue_fast_path(task_id: UUID) -> None:
    if task_id in _fast_path_ids or task_id in _running:
        return
    _fast_path.append(task_id)
    _fast_path_ids.add(task_id)


def cancel(task_id: UUID | str) -> bool:
    """Cancel the in-memory scheduler action for a running task."""
    task_uuid = UUID(str(task_id))
    running = _running.get(task_uuid)
    cancelled = False
    if running is not None and not running.done():
        running.cancel()
        cancelled = True

    if task_uuid in _fast_path_ids:
        _fast_path_ids.discard(task_uuid)
        try:
            _fast_path.remove(task_uuid)
        except ValueError:
            pass
        cancelled = True
    return cancelled


def _set_wake() -> None:
    event = _wake_event
    if event is not None:
        event.set()


async def _run_loop() -> None:
    while True:
        try:
            _schedule_periodic_jobs()
            did_work = await _fill_slots()
            if did_work:
                continue
            await _reconcile_paused_parents()
            await _wait_for_work()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task scheduler failed")
            await asyncio.sleep(_POLL_INTERVAL)


def _schedule_periodic_jobs() -> None:
    now = time.monotonic()
    for name, job in tuple(_periodic_jobs.items()):
        running = _periodic_running.get(name)
        if running is not None and not running.done():
            continue
        if now - _periodic_last_run.get(name, 0.0) < job.interval:
            continue
        _periodic_last_run[name] = now
        task = asyncio.create_task(
            _run_periodic_job(name, job.callback, timeout=job.timeout), name=f"task-scheduler-periodic-{name}"
        )
        _periodic_running[name] = task
        task.add_done_callback(lambda done, job_name=name: _periodic_done(job_name, done))


async def _run_periodic_job(
    name: str, callback: Callable[[], Awaitable[object]], *, timeout: float = 900.0,
) -> None:
    started = time.monotonic()
    outcome = "success"
    try:
        async with asyncio.timeout(timeout), get_db_session():
            await callback()
    except TimeoutError:
        outcome = "timeout"
        raise
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        labels = {"job": name, "outcome": outcome}
        _periodic_duration.record(time.monotonic() - started, labels)
        _periodic_outcomes.add(1, labels)


def _periodic_done(name: str, task: asyncio.Task[None]) -> None:
    _periodic_running.pop(name, None)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Task scheduler maintenance job {} failed", name)


async def _wait_for_work() -> None:
    event = _wake_event
    if event is None:
        await asyncio.sleep(_POLL_INTERVAL)
        return
    event.clear()
    try:
        await asyncio.wait_for(event.wait(), timeout=_POLL_INTERVAL)
    except asyncio.TimeoutError:
        pass


async def _fill_slots() -> bool:
    await _recover_expired_leases()
    scheduled = False
    while len(_running) < _max_concurrency():
        next_task = await _next_task(set(_running), set(_running_agents.values()))
        if next_task is None:
            break
        task_id, status, priority, agent_id, lease_token = next_task
        if _must_keep_interactive_slot(priority):
            await _release_unstarted_claim(task_id, lease_token)
            break
        _schedule_action(task_id, status, priority, agent_id, lease_token)
        scheduled = True
    return scheduled


def _max_concurrency() -> int:
    return max(1, int(runtime_settings.TASK_SCHEDULER_MAX_CONCURRENCY or 1))


def _must_keep_interactive_slot(priority: int) -> bool:
    if priority < 2:
        return False
    max_concurrency = _max_concurrency()
    if max_concurrency <= 1:
        return False
    return len(_running) >= max_concurrency - 1


def _schedule_action(
    task_id: UUID,
    status: TaskStatus,
    priority: int,
    agent_id: int,
    lease_token: UUID,
) -> None:
    logger.info(
        "Task scheduler: scheduling {} agent={} status={} priority={} running={}/{}",
        task_id,
        agent_id,
        status.value,
        priority,
        len(_running) + 1,
        _max_concurrency(),
    )
    task = asyncio.create_task(
        _run_claimed_action(task_id, status, lease_token),
        name=f"task-scheduler-{task_id}",
    )
    _running[task_id] = task
    _running_agents[task_id] = agent_id
    task.add_done_callback(lambda done, tid=task_id: _on_action_done(tid, done))


def _on_action_done(task_id: UUID, task: asyncio.Task[None]) -> None:
    _running.pop(task_id, None)
    _running_agents.pop(task_id, None)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("Task scheduler: action cancelled {}", task_id)
    except Exception:
        logger.exception("Task scheduler: action failed {}", task_id)
    wake()


async def run_once() -> bool:
    """Execute one scheduler action immediately, primarily for tests."""
    next_task = await _next_task(set(), set())
    if next_task is None:
        return False
    task_id, status, _priority, _agent_id, lease_token = next_task
    await _run_claimed_action(task_id, status, lease_token)
    return True


async def _run_claimed_action(
    task_id: UUID,
    status: TaskStatus,
    lease_token: UUID,
) -> None:
    """Execute an action under a lease with stall detection and durable finalization."""
    activity = asyncio.Event()
    _activity_events[task_id] = activity
    action = asyncio.create_task(
        _run_action(task_id, status), name=f"task-action-{task_id}"
    )
    heartbeat = asyncio.create_task(
        _heartbeat_lease(task_id, lease_token), name=f"task-lease-heartbeat-{task_id}"
    )
    stall_timeout_seconds = runtime_settings.TASK_ACTION_TIMEOUT_SECONDS
    try:
        while True:
            activity_wait = asyncio.create_task(
                activity.wait(), name=f"task-activity-{task_id}"
            )
            done, _pending = await asyncio.wait(
                {action, heartbeat, activity_wait},
                timeout=stall_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if activity_wait not in done:
                activity_wait.cancel()
                await asyncio.gather(activity_wait, return_exceptions=True)
            if not done:
                raise TimeoutError
            # Durable cancellation wins a completion race so another worker's pause request
            # cannot be overwritten by late completion.
            if heartbeat in done:
                await heartbeat
            if action in done:
                await action
                break
            activity.clear()
    except LeaseLostError:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        await _release_cancelled_claim(task_id, lease_token)
        return
    except asyncio.CancelledError:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        await asyncio.shield(_release_cancelled_claim(task_id, lease_token))
        raise
    except StaleAgentRunError:
        # An amendment already routed the durable Task to its revised objective. Treat the
        # superseded worker like a cancellation: it must neither consume a retry nor publish
        # an error over the amended Task.
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        await _release_cancelled_claim(task_id, lease_token)
        return
    except TimeoutError as exc:
        exceeded_action_deadline = not action.done()
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        failure = (
            TimeoutError(
                "Task action made no durable progress for its configured deadline of "
                f"{stall_timeout_seconds:g} seconds."
            )
            if exceeded_action_deadline
            else exc
        )
        await _fail_claim(task_id, status, lease_token, failure)
    except Exception as exc:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        await _fail_claim(task_id, status, lease_token, exc)
    else:
        await _complete_claim(task_id, status, lease_token)
    finally:
        if _activity_events.get(task_id) is activity:
            _activity_events.pop(task_id, None)
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def _run_action(task_id: UUID, status: TaskStatus) -> None:
    action = scheduler_action(status)
    if action == TaskAction.DISPATCH:
        await _dispatch(task_id)
        return
    if action == TaskAction.BRIEF:
        await _brief(task_id)
        return
    if action == TaskAction.EXECUTE:
        await _execute(task_id)
        return
    if action == TaskAction.ADVANCE_PLAN:
        await _plan(task_id)
        return


async def _next_task(
    running_ids: set[UUID], busy_agents: set[int]
) -> ClaimedTask | None:
    fairness_seconds = runtime_settings.TASK_SCHEDULER_FAIRNESS_SECONDS
    if not fairness_seconds:
        fast_task = await _next_fast_path(running_ids, busy_agents)
        if fast_task is not None:
            return fast_task

    async with get_db_session() as db:
        now = datetime.now(timezone.utc)
        priority = case(
            (Task.updated_at < now - timedelta(seconds=fairness_seconds), -1),
            (Task.message_group_id.is_not(None), 0),
            (Task.message_platform.is_not(None), 0),
            (Task.requester_agent_id.is_not(None), 1),
            else_=2,
        )
        if not fairness_seconds:
            priority = case(
                (Task.message_group_id.is_not(None), 0),
                (Task.message_platform.is_not(None), 0),
                (Task.requester_agent_id.is_not(None), 1),
                else_=2,
            )
        blocked_agents: set[int] = set()
        while True:
            query = (
                select(
                    Task.id,
                    Task.status,
                    Task.agent_id,
                    priority.label("scheduler_priority"),
                )
                .where(
                    Task.status.in_(
                        (
                            TaskStatus.CREATE,
                            TaskStatus.DISPATCH,
                            TaskStatus.BRIEFING,
                            TaskStatus.PLAN,
                        )
                    )
                )
                .where(Task.paused.is_(False))
                .where(Task.agent_id.is_not(None))
                .where(or_(Task.lease_token.is_(None), Task.lease_expires_at <= now))
                .where(or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now))
                .order_by(priority.asc(), Task.updated_at.asc(), Task.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if running_ids:
                query = query.where(Task.id.not_in(list(running_ids)))
            if blocked_agents:
                query = query.where(Task.agent_id.not_in(list(blocked_agents)))
            row = (await db.execute(Task.histo_filter(query))).first()
            if row is None:
                return None
            task_id, status, agent_id, scheduler_priority = row
            claimed = await _claim_locked_task(
                db,
                task_id=task_id,
                status=status,
                agent_id=int(agent_id),
                priority=int(scheduler_priority),
                now=now,
            )
            if claimed is not None:
                return claimed
            # A capped or concurrently locked agent must not hide runnable work owned by
            # another agent later in the queue.
            blocked_agents.add(int(agent_id))


async def _next_fast_path(
    running_ids: set[UUID], busy_agents: set[int]
) -> ClaimedTask | None:
    del busy_agents
    deferred: list[UUID] = []  # Fast tasks to requeue while their agent is busy.
    result: ClaimedTask | None = None
    while _fast_path:
        task_id = _fast_path.popleft()
        _fast_path_ids.discard(task_id)
        if task_id in running_ids:
            continue
        async with get_db_session() as db:
            query = (
                select(Task.id, Task.status, Task.agent_id)
                .where(Task.id == task_id)
                .where(
                    Task.status.in_(
                        (
                            TaskStatus.CREATE,
                            TaskStatus.DISPATCH,
                            TaskStatus.BRIEFING,
                            TaskStatus.PLAN,
                        )
                    )
                )
                .where(Task.paused.is_(False))
                .where(Task.agent_id.is_not(None))
                .limit(1)
            )
            row = (await db.execute(Task.histo_filter(query))).first()
        if row is None:
            continue
        fast_task_id, _status, _agent_id = row
        claimed = await _claim_specific(fast_task_id, priority=-1)
        if claimed is None:
            deferred.append(fast_task_id)
            continue
        result = claimed
        break
    for tid in reversed(deferred):  # Restore at the head while preserving order.
        _fast_path.appendleft(tid)
        _fast_path_ids.add(tid)
    return result


async def _claim_specific(task_id: UUID, *, priority: int) -> ClaimedTask | None:
    async with get_db_session() as db:
        now = datetime.now(timezone.utc)
        query = (
            select(Task.id, Task.status, Task.agent_id)
            .where(Task.id == task_id)
            .where(
                Task.status.in_(
                    (
                        TaskStatus.CREATE,
                        TaskStatus.DISPATCH,
                        TaskStatus.BRIEFING,
                        TaskStatus.PLAN,
                    )
                )
            )
            .where(Task.paused.is_(False))
            .where(Task.agent_id.is_not(None))
            .where(or_(Task.lease_token.is_(None), Task.lease_expires_at <= now))
            .where(or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now))
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = (await db.execute(Task.histo_filter(query))).first()
        if row is None:
            return None
        claimed_id, status, agent_id = row
        return await _claim_locked_task(
            db,
            task_id=claimed_id,
            status=status,
            agent_id=int(agent_id),
            priority=priority,
            now=now,
        )


async def _claim_locked_task(
    db: AsyncSession,
    *,
    task_id: UUID,
    status: TaskStatus,
    agent_id: int,
    priority: int,
    now: datetime,
) -> ClaimedTask | None:
    """Claim a locked row after enforcing the selected Harness limit."""
    if not await try_lock_agent(db, agent_id):
        return None

    from app.agent import max_parallel_tasks_for_agent

    max_parallel_tasks = await max_parallel_tasks_for_agent(agent_id)
    if max_parallel_tasks is not None:
        active_claims = int(
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.id != task_id,
                    Task.agent_id == agent_id,
                    Task.lease_token.is_not(None),
                    or_(
                        Task.lease_expires_at.is_(None),
                        Task.lease_expires_at > now,
                    ),
                )
            )
            or 0
        )
        if active_claims >= max_parallel_tasks:
            return None

    task = await db.get(Task, task_id)
    if task is None:
        return None
    from .replacement import replacement_pending
    if replacement_pending(task):
        return None
    from .budget import admit

    if not await admit(db, task, now, agent_id=agent_id):
        await db.flush()
        return None
    claimed_at = datetime.now(timezone.utc)
    if task.attempt_count == 0:
        timing = startup_timing(task.id, task.label, (task.data or {}).get(STARTUP_TIMING_DATA_KEY), claimed_at, task.lifecycle_timing)
        for metric, duration in (
            (_queue_wait, timing.queue_wait_upper_bound_seconds),
            (_preparation_duration, timing.preparation_seconds),
            (_admission_duration, timing.admission_seconds),
        ):
            if duration is not None:
                metric.record(duration, {"phase": status.value})
    token = uuid4()
    task.attempt_count += 1
    task.lease_token = token
    task.lease_owner = _WORKER_ID
    task.lease_expires_at = now + timedelta(seconds=runtime_settings.TASK_SCHEDULER_LEASE_SECONDS)
    task.next_attempt_at = None
    task.cancel_requested = False
    db.add(
        TaskAttempt(
            task_id=task.id,
            attempt_number=task.attempt_count,
            phase=status.value,
            started_at=claimed_at,
            status=TaskAttemptStatus.CLAIMED.value,
            worker_id=_WORKER_ID,
            lease_token=token,
            data={"base_cost": float(task.cost or 0.0), "priority": priority,
                  CLAIMED_AT_DATA_KEY: claimed_at.isoformat()},
        )
    )
    await db.flush()
    return task.id, status, priority, agent_id, token


async def claim_inline_execution(task_id: UUID) -> UUID:
    """Atomically reserve a paused task for an interactive in-process caller.

    Voice and other latency-sensitive entry points execute their task immediately
    instead of asking the scheduler to start it. They still need a durable lease:
    otherwise orphan recovery sees the transient ``EXEC`` phase and races the live
    driver. The task is unpaused and claimed in one transaction, so no scheduler
    worker can observe an unclaimed runnable row in between.
    """
    from app.task import task_service

    db = get_db()
    now = datetime.now(timezone.utc)
    task = await db.scalar(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    if task is None:
        raise InlineClaimUnavailable(f"Task {task_id} no longer exists.")
    if task.status != TaskStatus.DISPATCH:
        raise InlineClaimUnavailable(
            f"Task {task_id} is in {task.status.value}, expected DISPATCH."
        )
    if task.agent_id is None:
        raise InlineClaimUnavailable(f"Task {task_id} has no assigned agent.")
    if task.lease_token is not None and (
        task.lease_expires_at is None or task.lease_expires_at > now
    ):
        raise InlineClaimUnavailable(f"Task {task_id} is already leased.")

    claimed = await _claim_locked_task(
        db,
        task_id=task.id,
        status=task.status,
        agent_id=int(task.agent_id),
        priority=0,
        now=now,
    )
    if claimed is None:
        raise InlineClaimUnavailable(
            f"Agent {task.agent_id} is already executing another task."
        )
    task_service.clear_pauses(task)
    await db.commit()
    return claimed[4]


async def maintain_inline_execution(task_id: UUID, lease_token: UUID) -> None:
    """Renew an interactive claim until its caller cancels this coroutine."""
    await _heartbeat_lease(task_id, lease_token)


async def finish_inline_execution(
    task_id: UUID,
    lease_token: UUID,
    *,
    error: str | None = None,
    cancelled: bool = False,
) -> None:
    """Finish an interactive claim without scheduling a delayed replay.

    A spoken turn is no longer useful if its caller interrupted it or its provider
    failed. The durable task and attempt retain that outcome, but unlike a normal
    background action the scheduler must never replay the utterance later.
    """
    from app.task import task_service

    async with get_db_session() as db:
        task = await db.scalar(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        if task is None or task.lease_token != lease_token:
            return

        attempt = await _attempt_for_token(db, lease_token)
        failure = (error or "").strip()[:4000]
        if task.status not in (TaskStatus.SUCCESS, TaskStatus.ERROR) and (
            cancelled or failure
        ):
            transition(
                task,
                TaskEvent.CANCEL if cancelled else TaskEvent.FAIL,
            )
            task_service.clear_pauses(task)
        if failure:
            task.last_error = failure
            task.feedback = failure
            task.consecutive_failures += 1

        if attempt is not None:
            if cancelled:
                attempt.status = TaskAttemptStatus.CANCELLED.value
            elif failure or task.status == TaskStatus.ERROR:
                attempt.status = TaskAttemptStatus.ERROR.value
            else:
                attempt.status = TaskAttemptStatus.SUCCESS.value
            attempt.finished_at = datetime.now(timezone.utc)
            attempt.retryable = False
            attempt.error = failure or None
            attempt.data = {**(attempt.data or {}), "inline_execution": True}
            base_cost = float((attempt.data or {}).get("base_cost", 0.0) or 0.0)
            attempt.cost = max(0.0, float(task.cost or 0.0) - base_cost)

        task.next_attempt_at = None
        _clear_lease(task)


def _clear_lease(task: Task) -> None:
    task.lease_token = None
    task.lease_owner = None
    task.lease_expires_at = None
    task.cancel_requested = False


async def _attempt_for_token(db: AsyncSession, lease_token: UUID) -> TaskAttempt | None:
    return await db.scalar(
        select(TaskAttempt).where(TaskAttempt.lease_token == lease_token).limit(1)
    )


async def _release_unstarted_claim(task_id: UUID, lease_token: UUID) -> None:
    async with get_db_session() as db:
        task = await db.scalar(
            select(Task).where(Task.id == task_id).with_for_update(skip_locked=True)
        )
        if task is None or task.lease_token != lease_token:
            return
        attempt = await _attempt_for_token(db, lease_token)
        if attempt is not None:
            attempt.status = TaskAttemptStatus.CANCELLED.value
            attempt.finished_at = datetime.now(timezone.utc)
            attempt.error = _task_message(task, "interactive_slot_reserved")
        _clear_lease(task)


async def _heartbeat_lease(task_id: UUID, lease_token: UUID) -> None:
    interval = max(5.0, runtime_settings.TASK_SCHEDULER_LEASE_SECONDS / 6)
    while True:
        await asyncio.sleep(interval)
        async with get_db_session():
            if not await _renew_lease(task_id, lease_token):
                raise LeaseLostError(f"Lease lost or cancellation requested for {task_id}")


async def _renew_lease(task_id: UUID, lease_token: UUID) -> bool:
    """Renew a live owner without changing the Task's definition or JSON state."""
    now = datetime.now(timezone.utc)
    renewed = await get_db().scalar(
        update(Task).where(
            Task.id == task_id,
            Task.lease_token == lease_token,
            Task.lease_expires_at > now,
            Task.deleted_at.is_(None),
            Task.paused.is_(False),
            Task.cancel_requested.is_(False),
        ).values(lease_expires_at=now + timedelta(seconds=runtime_settings.TASK_SCHEDULER_LEASE_SECONDS))
        .returning(Task.id)
    )
    return renewed is not None


def _finalize_claim_outcome(task: Task, attempt: TaskAttempt | None) -> None:
    """Close a claim whose durable task outcome is already authoritative."""
    from app.task import task_service

    waiting_children = task.paused and (
        task_service.is_paused_for(task, task_service.PAUSE_AWAIT)
        or task_service.is_paused_for(task, task_service.PAUSE_CHILD)
    )
    if attempt is not None:
        if task.status == TaskStatus.ERROR:
            attempt.status = TaskAttemptStatus.ERROR.value
            # A failed run that terminates without raising carries its error only
            # in the execution result; surface it for the attempt log and the UI.
            failed_result = task.get_execution_result()
            if failed_result is not None and not failed_result.success:
                failure = (failed_result.result or "").strip()[:4000]
                if failure:
                    attempt.error = failure
                    task.last_error = failure
        elif waiting_children:
            attempt.status = TaskAttemptStatus.WAITING_CHILDREN.value
            attempt.data = {
                **(attempt.data or {}),
                "pause_reasons": task_service.pause_reasons(task),
            }
            partial_result = task.get_execution_result()
            if partial_result is not None and not partial_result.success:
                attempt.error = (
                    partial_result.result.strip()
                    or _task_message(task, "interrupted_after_children")
                )[:4000]
                attempt.data = {
                    **(attempt.data or {}),
                    "partial_execution_failure": True,
                }
        else:
            attempt.status = TaskAttemptStatus.SUCCESS.value
        attempt.finished_at = datetime.now(timezone.utc)
        base_cost = float((attempt.data or {}).get("base_cost", 0.0) or 0.0)
        attempt.cost = max(0.0, float(task.cost or 0.0) - base_cost)
    task.consecutive_failures = 0
    task.next_attempt_at = None
    if task.status != TaskStatus.ERROR:
        task.last_error = None
    _clear_lease(task)


async def _complete_claim(
    task_id: UUID,
    phase: TaskStatus,
    lease_token: UUID,
) -> None:
    """Finish an attempt as successful, waiting for children, failed, or retryable."""
    outcome_error: str | None = None
    async with get_db_session() as db:
        task = await db.scalar(
            select(Task).where(Task.id == task_id).with_for_update(skip_locked=True)
        )
        if task is None or task.lease_token != lease_token:
            return
        if task.status == TaskStatus.ERROR and _retry_is_safe(task, phase):
            outcome_error = task.feedback or _task_message(task, "action_failed")
        else:
            attempt = await _attempt_for_token(db, lease_token)
            _finalize_claim_outcome(task, attempt)
    if outcome_error is not None:
        await _fail_claim(task_id, phase, lease_token, RuntimeError(outcome_error))


def _retry_is_safe(task: Task, phase: TaskStatus) -> bool:
    """Prevent automatic replay after an attempt has already produced tool effects."""
    if phase == TaskStatus.PLAN and task.get_execution_result() is not None:
        # The planner already aggregated a terminal outcome, such as a failed child. Replaying
        # ``advance`` would only repeat the same abort.
        return False
    if phase != TaskStatus.DISPATCH:
        return True
    receipt = (task.data or {}).get("_delivery_receipt")
    if isinstance(receipt, dict) and cast(dict[str, Any], receipt).get("status") == "started":
        return False
    from app.agent import has_resumable_run_checkpoint

    result = task.get_execution_result()
    if result is not None and result.failure is not None:
        if result.failure.retry == "never":
            return False
        if result.failure.retry == "reconcile" and not has_resumable_run_checkpoint(task):
            return False

    if (task.data or {}).get("_agent_run_checkpoint") is not None:
        # A write-ahead effect may exist before tools_used or any result was saved.
        # Never let a blank result or a corrective guard bypass its recovery policy.
        return has_resumable_run_checkpoint(task)
    if (task.data or {}).get("_agent_run_identity") is not None:
        # Admission was persisted before entering the driver. A crashed worker may
        # have sent a remote mutation without receiving any result or tool event.
        # No recovery contract means no automatic replay, including on lease expiry.
        return False
    result = task.get_execution_result()
    if result is None or not any(
        name not in _RETRY_TRACE_ONLY_TOOLS for name in result.tools_used
    ):
        return True
    return has_resumable_run_checkpoint(task)


async def _release_cancelled_claim(task_id: UUID, lease_token: UUID) -> None:
    async with get_db_session() as db:
        task = await db.scalar(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        if task is None or task.lease_token != lease_token:
            return
        attempt = await _attempt_for_token(db, lease_token)
        if attempt is not None:
            attempt.status = TaskAttemptStatus.CANCELLED.value
            attempt.finished_at = datetime.now(timezone.utc)
            attempt.data = {**(attempt.data or {}), "local_execution_stopped": True}
        # Worker cancellation or reload must never leave the transient EXEC phase behind.
        if task.status == TaskStatus.EXEC:
            transition(task, TaskEvent.INTERRUPT_EXECUTION)
            transition(task, TaskEvent.ROUTE_TO_EXECUTION)
        _clear_lease(task)
        task.next_attempt_at = None
    if not task.paused and task.status in (
        TaskStatus.CREATE,
        TaskStatus.DISPATCH,
        TaskStatus.BRIEFING,
        TaskStatus.PLAN,
    ):
        wake(task.id)


async def _fail_claim(
    task_id: UUID,
    phase: TaskStatus,
    lease_token: UUID,
    exc: BaseException,
) -> None:
    """Persist a failure and schedule a bounded retry, or terminate the task as ERROR."""
    from app.task import task_service
    from app.agent.contracts import ExecutionResult
    from app.agent import HarnessExecutionError, classify_execution_error

    raw_error = f"{type(exc).__name__}: {exc}".strip()
    error = raw_error[:4000]
    retry_delay: float | None = None
    terminal = False
    async with get_db_session() as db:
        task = await db.scalar(
            select(Task).where(Task.id == task_id).with_for_update(skip_locked=True)
        )
        if task is None or task.lease_token != lease_token:
            return
        attempt = await _attempt_for_token(db, lease_token)
        if task.status == TaskStatus.SUCCESS:
            # The action committed its terminal result but the worker stopped before
            # finalizing the attempt. SUCCESS is immutable: recover the stale claim as
            # completed instead of trying the invalid SUCCESS -> ERROR transition.
            logger.warning(
                "Task scheduler: finalizing expired claim for successful task {}",
                task.id,
            )
            _finalize_claim_outcome(task, attempt)
            return
        task.consecutive_failures += 1
        safe_to_retry = _retry_is_safe(task, phase)
        if isinstance(exc, HarnessExecutionError) and exc.failure.retry == "reconcile":
            from app.agent import has_resumable_run_checkpoint

            safe_to_retry = safe_to_retry and has_resumable_run_checkpoint(task)
        max_attempts, retry_policy_delay, network_failure = _retry_policy(
            error, task.consecutive_failures
        )
        can_retry = (
            not isinstance(exc, ReasoningDegenerationError)
            and (not isinstance(exc, HarnessExecutionError) or exc.failure.retry != "never")
            and safe_to_retry
            and task.consecutive_failures < max_attempts
            and not task_service.is_held_by_user(task)
        )
        if attempt is not None:
            attempt.status = (
                TaskAttemptStatus.RETRY.value
                if can_retry
                else TaskAttemptStatus.ERROR.value
            )
            attempt.retryable = can_retry
            attempt.error = error
            attempt.finished_at = datetime.now(timezone.utc)
            attempt_data = {
                **(attempt.data or {}),
                "network_failure": network_failure,
                "harness_failure": classify_execution_error(exc).model_dump(mode="json"),
            }
            if isinstance(exc, ReasoningDegenerationError):
                attempt_data["reasoning_degeneration"] = True
            attempt.data = attempt_data
            base_cost = float((attempt.data or {}).get("base_cost", 0.0) or 0.0)
            attempt.cost = max(0.0, float(task.cost or 0.0) - base_cost)

        task.last_error = error
        _clear_lease(task)
        if can_retry:
            if task.status == TaskStatus.ERROR:
                if phase == TaskStatus.CREATE:
                    transition(task, TaskEvent.RETRY_ROUTING)
                else:
                    transition(task, TaskEvent.RETRY)
                    if phase == TaskStatus.PLAN:
                        transition(task, TaskEvent.ROUTE_TO_PLAN)
                    elif phase == TaskStatus.BRIEFING:
                        transition(task, TaskEvent.ROUTE_TO_BRIEFING)
                    else:
                        transition(task, TaskEvent.ROUTE_TO_EXECUTION)
            elif task.status == TaskStatus.EXEC:
                transition(task, TaskEvent.INTERRUPT_EXECUTION)
                transition(task, TaskEvent.ROUTE_TO_EXECUTION)
            delay = retry_policy_delay
            retry_delay = delay
            task.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            logger.warning(
                "Task scheduler: attempt {} failed for {}; retry{} in {:.1f}s: {}",
                task.consecutive_failures,
                task.id,
                " (network)" if network_failure else "",
                delay,
                error,
            )
        else:
            terminal = True
            if task.status != TaskStatus.ERROR:
                transition(task, TaskEvent.FAIL)
            task.next_attempt_at = None
            failure_feedback = _task_message(
                task,
                "failed_after_attempts",
                count=task.consecutive_failures,
                error=error,
            )
            task.feedback = failure_feedback
            task_service.clear_pauses(task)
            execution_result = task.get_execution_result()
            if execution_result is None:
                execution_result = ExecutionResult(
                    prompt=task.objective or "",
                    result=failure_feedback,
                    success=False,
                    cost=0.0,
                )
            else:
                execution_result.success = False
                if not execution_result.result.strip():
                    execution_result.result = failure_feedback
            task.set_execution_result(execution_result)
        await task_service.save(task)

    if retry_delay is not None:
        wake(task_id, delay=retry_delay)
        return
    if terminal:
        await _resume_after_terminal_failure(task_id)


async def _recover_expired_leases() -> None:
    """Turn expired leases into retryable failures, including after restart."""
    from app.task import task_service

    global _last_lease_recovery
    now_mono = time.monotonic()
    if now_mono - _last_lease_recovery < _RECONCILE_INTERVAL:
        return
    _last_lease_recovery = now_mono
    now = datetime.now(timezone.utc)
    orphaned_exec_ids: list[UUID] = []
    unsafe_orphan_ids: list[UUID] = []
    async with get_db_session() as db:
        # Compatibility for tasks created before leases or interrupted during deployment: an
        # EXEC task without a lease cannot belong to a live worker.
        orphaned_exec = list(
            (
                await db.scalars(
                    select(Task)
                    .where(
                        Task.status == TaskStatus.EXEC,
                        Task.lease_token.is_(None),
                        Task.deleted_at.is_(None),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for task in orphaned_exec:
            if _retry_is_safe(task, TaskStatus.DISPATCH):
                transition(task, TaskEvent.RECOVER_EXECUTION)
                transition(task, TaskEvent.ROUTE_TO_EXECUTION)
                task.next_attempt_at = now
                task.last_error = _task_message(task, "orphan_recovered")
                orphaned_exec_ids.append(task.id)
                continue

            transition(task, TaskEvent.FAIL)
            task.next_attempt_at = None
            task.last_error = _task_message(task, "orphan_unsafe")
            task.feedback = task.last_error
            task_service.clear_pauses(task)
            unsafe_orphan_ids.append(task.id)

        rows = (
            await db.execute(
                select(Task.id, Task.lease_token, TaskAttempt.phase)
                .join(TaskAttempt, TaskAttempt.lease_token == Task.lease_token)
                .where(
                    Task.lease_token.is_not(None),
                    Task.lease_expires_at <= now,
                    Task.deleted_at.is_(None),
                )
            )
        ).all()
    for orphaned_id in orphaned_exec_ids:
        logger.warning("Task scheduler: recovering orphaned EXEC task {}", orphaned_id)
        wake(orphaned_id)
    for unsafe_orphan_id in unsafe_orphan_ids:
        logger.error(
            "Task scheduler: orphaned EXEC task {} not replayed after tool usage",
            unsafe_orphan_id,
        )
        await _resume_after_terminal_failure(unsafe_orphan_id)
    for task_id, lease_token, raw_phase in rows:
        if lease_token is None:
            continue
        try:
            phase = TaskStatus(str(raw_phase))
        except ValueError:
            phase = TaskStatus.DISPATCH
        await _fail_claim(
            task_id,
            phase,
            lease_token,
            TimeoutError("Scheduler lease expired before the action completed."),
        )


async def _resume_after_terminal_failure(task_id: UUID) -> None:
    """Wake workflows waiting for a task that has become terminal."""
    from app.agent import handle_terminal_task
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task

    async with get_db_session():
        failed = await task_service.get_by_id(task_id)
        if failed is None:
            return
        await handle_terminal_task(as_agent_task(failed))


def running_task_ids_for_agent(
    agent_id: int,
    *,
    exclude_task_id: UUID | None = None,
) -> list[UUID]:
    """Return in-memory actions currently running for an agent."""
    return [
        task_id for task_id, running_agent_id in _running_agents.items()
        if running_agent_id == agent_id and task_id != exclude_task_id
    ]


async def _dispatch(task_id: UUID) -> None:
    from app.agent import run_workflow_step
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task

    logger.info("Task scheduler — dispatch {}", task_id)
    async with get_db_session():
        task = await task_service.get_by_id(task_id)
        if task is None or task.status != TaskStatus.CREATE or task.paused:
            return
        await run_workflow_step(as_agent_task(task))


async def _execute(task_id: UUID) -> None:
    from app.agent import run_workflow_step
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task

    logger.info("Task scheduler — execute {}", task_id)
    async with get_db_session():
        task = await task_service.get_by_id(task_id)
        if task is None or task.status != TaskStatus.DISPATCH or task.paused:
            return
        await run_workflow_step(as_agent_task(task))


async def _brief(task_id: UUID) -> None:
    from app.agent import run_workflow_step
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task

    logger.info("Task scheduler — briefing {}", task_id)
    async with get_db_session():
        task = await task_service.get_by_id(task_id)
        if task is None or task.status != TaskStatus.BRIEFING or task.paused:
            return
        await run_workflow_step(as_agent_task(task))


async def _plan(task_id: UUID) -> None:
    from app.agent import run_workflow_step
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task

    logger.info("Task scheduler — plan {}", task_id)
    async with get_db_session():
        task = await task_service.get_by_id(task_id)
        if task is None or task.status != TaskStatus.PLAN or task.paused:
            return
        await run_workflow_step(as_agent_task(task))


async def _reconcile_paused_parents() -> None:
    """Resume plan-suspended parents whose current child is already terminal.

    This lost-wake-up backstop is throttled and runs only while the scheduler is otherwise idle.
    """
    global _last_reconcile
    now = time.monotonic()
    if now - _last_reconcile < _RECONCILE_INTERVAL:
        return
    _last_reconcile = now

    from app.agent import reconcile_plan_parent, resume_expired_planner_clarifications
    from app.task import task_service
    from app.task.agent_adapter import as_agent_task, as_agent_tasks

    async with get_db_session() as db:
        query = select(Task.id).where(
            Task.paused.is_(True),
            Task.plan.is_not(None),
        )
        result = await db.execute(Task.histo_filter(query))
        parent_ids = [row[0] for row in result.all()]

    for parent_id in parent_ids:
        async with get_db_session():
            task = await task_service.get_by_id(parent_id)
            if (
                task is None
                or not task.plan
                or not task_service.is_paused_for(task, task_service.PAUSE_PLAN)
                or task_service.is_held_by_user(task)
            ):
                continue
            children = await task_service.get_children(parent_id)
            if await reconcile_plan_parent(
                as_agent_task(task),
                as_agent_tasks(children),
            ):
                logger.info("Task scheduler: reconciled and resumed parent {}", parent_id)
                wake(task.id)

    # Recover clarification questions and interaction handlers captured before a crash.
    async with get_db_session():
        await resume_expired_planner_clarifications()
        from app.messenger import interactions

        await interactions.retry_pending_interactions()

    # Collaboration backstops cover silent-peer timeouts and fan-in races. Both are idempotent.
    async with get_db_session():
        from app.task import collab

        await collab.resume_expired_awaits()
    async with get_db_session():
        from app.task import collab

        await collab.resume_completed_await_parents()
