import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.agent.contracts import ReasoningDegenerationError, StaleAgentRunError
from app.agent.models import Agent, Title
from app.task import scheduler
from app.task.models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus


@pytest.mark.asyncio
async def test_periodic_timeout_cleans_up_and_allows_the_next_run(monkeypatch):
    cleaned = asyncio.Event()
    calls = []

    @asynccontextmanager
    async def session():
        try:
            yield
        finally:
            cleaned.set()

    async def blocked():
        calls.append("blocked")
        await asyncio.Event().wait()

    monkeypatch.setattr(scheduler, "get_db_session", session)
    monkeypatch.setattr(scheduler, "_periodic_jobs", {})
    monkeypatch.setattr(scheduler, "_periodic_running", {})
    monkeypatch.setattr(scheduler, "_periodic_last_run", {})
    scheduler.register_periodic_job("test", blocked, interval=1, timeout=0.01)
    scheduler._schedule_periodic_jobs()
    first = scheduler._periodic_running["test"]
    with pytest.raises(TimeoutError):
        await first
    await asyncio.sleep(0)
    assert cleaned.is_set()
    assert "test" not in scheduler._periodic_running
    recovered = AsyncMock()
    scheduler.register_periodic_job("test", recovered, interval=1)
    scheduler._periodic_last_run.clear()
    scheduler._schedule_periodic_jobs()
    await scheduler._periodic_running["test"]
    recovered.assert_awaited_once()
    assert calls == ["blocked"]


@pytest.mark.asyncio
async def test_is_running_tracks_scheduler_root_task() -> None:
    original = scheduler._scheduler_task  # pyright: ignore[reportPrivateUsage]
    root = asyncio.create_task(asyncio.Event().wait())
    try:
        scheduler._scheduler_task = root  # pyright: ignore[reportPrivateUsage]
        assert scheduler.is_running() is True

        root.cancel()
        await asyncio.gather(root, return_exceptions=True)
        assert scheduler.is_running() is False
    finally:
        scheduler._scheduler_task = original  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_fill_slots_serializes_per_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclude a busy agent from selection so each agent runs at most one task."""
    scheduler._running.clear()  # pyright: ignore[reportPrivateUsage]
    scheduler._running_agents.clear()  # pyright: ignore[reportPrivateUsage]
    seen_busy: list[set[int]] = []
    # First pass: one task for agent 5. Second pass: nothing remains to schedule.
    queue: list[tuple[Any, TaskStatus, int, int, Any] | None] = [
        (uuid4(), TaskStatus.CREATE, 0, 5, uuid4()),
        None,
    ]

    async def fake_next_task(running_ids: set[Any], busy_agents: set[int]) -> Any:
        seen_busy.append(set(busy_agents))
        return queue.pop(0) if queue else None

    def fake_schedule(
        task_id: Any,
        status: TaskStatus,
        priority: int,
        agent_id: int,
        lease_token: Any,
    ) -> None:
        _ = (status, priority, lease_token)
        scheduler._running[task_id] = None  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
        scheduler._running_agents[task_id] = agent_id  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(scheduler, "_next_task", fake_next_task)
    monkeypatch.setattr(scheduler, "_schedule_action", fake_schedule)
    monkeypatch.setattr(scheduler, "_recover_expired_leases", AsyncMock())
    monkeypatch.setattr(scheduler, "_max_concurrency", lambda: 8)

    await scheduler._fill_slots()  # pyright: ignore[reportPrivateUsage]

    assert seen_busy[0] == set()      # No agent is busy initially.
    assert seen_busy[1] == {5}        # Agent 5 is now excluded.
    scheduler._running.clear()  # pyright: ignore[reportPrivateUsage]
    scheduler._running_agents.clear()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_on_action_done_frees_agent() -> None:
    """Completing an action releases the agent from ``_running_agents``."""
    scheduler._running.clear()  # pyright: ignore[reportPrivateUsage]
    scheduler._running_agents.clear()  # pyright: ignore[reportPrivateUsage]
    task_id = uuid4()

    async def _noop() -> None:
        return None

    done = asyncio.create_task(_noop())
    await done
    scheduler._running[task_id] = done  # pyright: ignore[reportPrivateUsage]
    scheduler._running_agents[task_id] = 9  # pyright: ignore[reportPrivateUsage]

    scheduler._on_action_done(task_id, done)  # pyright: ignore[reportPrivateUsage]

    assert task_id not in scheduler._running  # pyright: ignore[reportPrivateUsage]
    assert task_id not in scheduler._running_agents  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
@pytest.mark.parametrize("measured_admission", [False, True])
async def test_internal_harness_can_claim_two_tasks_for_the_same_agent(
    db,
    monkeypatch: pytest.MonkeyPatch,
    measured_admission: bool,
) -> None:
    """The embedded Harness has no per-agent concurrency ceiling."""

    import app.agent as agent_domain

    monkeypatch.setattr(
        agent_domain,
        "max_parallel_tasks_for_agent",
        AsyncMock(return_value=None),
    )

    suffix = uuid4().hex[:10]
    title = Title(label=f"Queue test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Queue",
        last_name="Owner",
        code=f"queue-owner-{suffix}",
    )
    db.add(agent)
    await db.flush()
    agent_id = agent.id
    title_id = title.id
    active_id = uuid4()
    queued_id = uuid4()
    active = Task(
        id=active_id,
        label="active-work",
        status=TaskStatus.EXEC,
        ai=True,
        agent_id=agent_id,
        lease_token=uuid4(),
        lease_owner="other-worker",
        lease_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    queued = Task(
        id=queued_id,
        label="new-conversation-work",
        status=TaskStatus.CREATE,
        ai=True,
        agent_id=agent_id,
        message_platform="matrix",
        message_group_id="room-1",
    )
    queue_measurements = []
    preparation_measurements = []
    admission_measurements = []
    for name, measurements in (("_queue_wait", queue_measurements),
                               ("_preparation_duration", preparation_measurements),
                               ("_admission_duration", admission_measurements)):
        monkeypatch.setattr(scheduler, name, SimpleNamespace(
            record=lambda value, attributes, measurements=measurements: measurements.append(value)))
    if measured_admission:
        queued.data = {"_startup_timing": {
            "preparation_started_at": "2026-01-01T00:00:00Z",
            "preparation_finished_at": "2026-01-01T00:00:15Z",
            "enqueued_at": "2026-01-01T00:00:15.200Z",
        }}
    db.add_all([active, queued])
    await db.commit()
    scheduler._fast_path.clear()  # pyright: ignore[reportPrivateUsage]
    scheduler._fast_path_ids.clear()  # pyright: ignore[reportPrivateUsage]

    claimed = await scheduler._next_task(set(), set())  # pyright: ignore[reportPrivateUsage]

    assert claimed is not None
    assert claimed[0] == queued_id
    db.expire_all()
    claimed_task = await db.get(Task, queued_id)
    assert claimed_task is not None
    assert claimed_task.status == TaskStatus.CREATE
    assert claimed_task.lease_token is not None
    attempt = await db.scalar(select(TaskAttempt).where(TaskAttempt.task_id == queued_id))
    assert attempt is not None
    assert datetime.fromisoformat(attempt.data["claimed_at"]).tzinfo is not None
    if measured_admission:
        assert preparation_measurements == [15]
        assert admission_measurements == [pytest.approx(.2)]
        assert len(queue_measurements) == 1
    else:
        assert preparation_measurements == admission_measurements == []
        assert len(queue_measurements) == 1
        assert queue_measurements[0] >= 0

    await db.execute(delete(Task).where(Task.id.in_([active_id, queued_id])))
    await db.execute(delete(Agent).where(Agent.id == agent_id))
    await db.execute(delete(Title).where(Title.id == title_id))
    await db.commit()


@pytest.mark.asyncio
async def test_external_harness_keeps_second_task_queued_for_the_same_agent(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The external Harness limit is enforced from durable active leases."""

    import app.agent as agent_domain

    monkeypatch.setattr(
        agent_domain,
        "max_parallel_tasks_for_agent",
        AsyncMock(return_value=1),
    )
    suffix = uuid4().hex[:10]
    title = Title(label=f"External queue test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="External",
        last_name="Owner",
        code=f"external-queue-owner-{suffix}",
    )
    db.add(agent)
    await db.flush()
    agent_id = agent.id
    title_id = title.id
    active_id = uuid4()
    queued_id = uuid4()
    db.add_all(
        [
            Task(
                id=active_id,
                label="active-external-work",
                status=TaskStatus.EXEC,
                ai=True,
                agent_id=agent_id,
                lease_token=uuid4(),
                lease_owner="other-worker",
                lease_expires_at=None,
            ),
            Task(
                id=queued_id,
                label="queued-external-work",
                status=TaskStatus.CREATE,
                ai=True,
                agent_id=agent_id,
            ),
        ]
    )
    await db.commit()
    scheduler._fast_path.clear()  # pyright: ignore[reportPrivateUsage]
    scheduler._fast_path_ids.clear()  # pyright: ignore[reportPrivateUsage]

    claimed = await scheduler._next_task(set(), set())  # pyright: ignore[reportPrivateUsage]

    assert claimed is None
    db.expire_all()
    queued = await db.get(Task, queued_id)
    assert queued is not None
    assert queued.lease_token is None

    await db.execute(delete(Task).where(Task.id.in_([active_id, queued_id])))
    await db.execute(delete(Agent).where(Agent.id == agent_id))
    await db.execute(delete(Title).where(Title.id == title_id))
    await db.commit()


@pytest.mark.asyncio
async def test_scheduler_does_not_execute_exec_status(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_execute(task_id):
        nonlocal called
        called = True

    monkeypatch.setattr(scheduler, "_execute", fake_execute)

    await scheduler._run_action(uuid4(), TaskStatus.EXEC)  # pyright: ignore[reportPrivateUsage]

    assert called is False


@pytest.mark.asyncio
async def test_claimed_action_persists_retry_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    token = uuid4()

    async def fail_action(_task_id, _status):
        raise RuntimeError("provider down")

    async def idle_heartbeat(_task_id, _token):
        await asyncio.Future()

    fail_claim = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_action", fail_action)
    monkeypatch.setattr(scheduler, "_heartbeat_lease", idle_heartbeat)
    monkeypatch.setattr(scheduler, "_fail_claim", fail_claim)
    monkeypatch.setattr(scheduler, "_complete_claim", AsyncMock())

    await scheduler._run_claimed_action(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, token
    )

    fail_claim.assert_awaited_once()
    assert fail_claim.await_args.args[:3] == (task_id, TaskStatus.DISPATCH, token)


@pytest.mark.asyncio
async def test_claimed_action_persists_an_actionable_deadline_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    token = uuid4()

    async def stalled_action(_task_id: object, _status: object) -> None:
        await asyncio.Future()

    async def idle_heartbeat(_task_id: object, _token: object) -> None:
        await asyncio.Future()

    fail_claim = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_action", stalled_action)
    monkeypatch.setattr(scheduler, "_heartbeat_lease", idle_heartbeat)
    monkeypatch.setattr(scheduler, "_fail_claim", fail_claim)
    monkeypatch.setattr(
        scheduler,
        "runtime_settings",
        SimpleNamespace(TASK_ACTION_TIMEOUT_SECONDS=0.01),
    )

    await scheduler._run_claimed_action(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, token
    )

    failure = fail_claim.await_args.args[3]
    assert isinstance(failure, TimeoutError)
    assert str(failure) == (
        "Task action made no durable progress for its configured deadline of 0.01 seconds."
    )


@pytest.mark.asyncio
async def test_durable_progress_rearms_action_stall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    token = uuid4()

    async def progressing_action(current_task_id: UUID, _status: object) -> None:
        for _ in range(4):
            await asyncio.sleep(0.04)
            scheduler.notify_task_activity(current_task_id)

    async def idle_heartbeat(_task_id: object, _token: object) -> None:
        await asyncio.Future()

    complete_claim = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_action", progressing_action)
    monkeypatch.setattr(scheduler, "_heartbeat_lease", idle_heartbeat)
    monkeypatch.setattr(scheduler, "_fail_claim", AsyncMock())
    monkeypatch.setattr(scheduler, "_complete_claim", complete_claim)
    monkeypatch.setattr(
        scheduler,
        "runtime_settings",
        SimpleNamespace(TASK_ACTION_TIMEOUT_SECONDS=0.1),
    )

    await scheduler._run_claimed_action(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, token
    )

    complete_claim.assert_awaited_once_with(task_id, TaskStatus.DISPATCH, token)


@pytest.mark.asyncio
async def test_claimed_action_releases_superseded_run_without_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    token = uuid4()

    async def superseded_action(_task_id: object, _status: object) -> None:
        raise StaleAgentRunError("objective changed")

    async def idle_heartbeat(_task_id: object, _token: object) -> None:
        await asyncio.Future()

    release = AsyncMock()
    fail_claim = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_action", superseded_action)
    monkeypatch.setattr(scheduler, "_heartbeat_lease", idle_heartbeat)
    monkeypatch.setattr(scheduler, "_release_cancelled_claim", release)
    monkeypatch.setattr(scheduler, "_fail_claim", fail_claim)

    await scheduler._run_claimed_action(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, token
    )

    release.assert_awaited_once_with(task_id, token)
    fail_claim.assert_not_awaited()


def test_network_retry_policy_spans_long_provider_outage() -> None:
    error = "HTTP 502: Temporary failure in name resolution"
    policies = [scheduler._retry_policy(error, attempt) for attempt in range(1, 8)]  # pyright: ignore[reportPrivateUsage]

    assert all(network for _max_attempts, _delay, network in policies)
    assert policies[0][0] == 8
    assert [delay for _max_attempts, delay, _network in policies] == [
        30.0,
        60.0,
        120.0,
        240.0,
        300.0,
        300.0,
        300.0,
    ]
    assert sum(delay for _max_attempts, delay, _network in policies) > 20 * 60


def test_incomplete_chunked_response_uses_network_retry_policy() -> None:
    max_attempts, delay, network = scheduler._retry_policy(  # pyright: ignore[reportPrivateUsage]
        "RuntimeError: peer closed connection without sending complete message body "
        "(incomplete chunked read)",
        1,
    )

    assert network is True
    assert max_attempts == 8
    assert delay == 30.0


def test_non_network_failure_keeps_short_retry_policy() -> None:
    max_attempts, delay, network = scheduler._retry_policy(  # pyright: ignore[reportPrivateUsage]
        "ValidationError: malformed output", 1
    )

    assert network is False
    assert max_attempts == 3
    assert delay == 2.0


def test_finalized_plan_failure_is_not_retryable() -> None:
    finalized = Task(
        label="plan-finalized",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "objective",
            "result": "one step failed",
            "success": False,
        },
    )
    build_failure = Task(label="plan-build-failure", status=TaskStatus.ERROR)

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        finalized,
        TaskStatus.PLAN,
    ) is False
    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        build_failure,
        TaskStatus.PLAN,
    ) is True


@pytest.mark.parametrize("recoverable", [False, True])
def test_write_ahead_effect_controls_retry_before_any_visible_result(recoverable):
    task = Task(label="No acknowledgement", status=TaskStatus.ERROR, data={
        "_agent_run_checkpoint": {
            "driver_code": "internal", "runtime_run_id": "run", "status": "interrupted",
            "data": {"version": 3, "resume_safe": False, "resume_reconcilable": recoverable,
                     "effects": [{"status": "started", "tool_name": "console_exec",
                                  "operation_id": str(uuid4()), "recovery_scope": "same-server"}]},
        },
    })
    assert task.get_execution_result() is None
    assert scheduler._retry_is_safe(task, TaskStatus.DISPATCH) is recoverable


def test_dispatch_failure_with_only_thinking_trace_is_retryable() -> None:
    task = Task(
        label="thinking-only",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "discover tools",
            "result": "database transaction failed",
            "success": False,
            "tools_used": ["thinking"],
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is True


def test_dispatch_failure_with_legacy_artifact_guard_still_requires_checkpoint() -> None:
    task = Task(
        label="artifact-guard-verdict",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "produce and deliver the file",
            "result": "",
            "success": False,
            "tools_used": ["file_write", "file_list"],
            "metadata": {"artifact_guard_retried": True},
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is False


def test_dispatch_failure_with_legacy_action_guard_still_requires_checkpoint() -> None:
    task = Task(
        label="action-guard-verdict",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "perform the action",
            "result": "",
            "success": False,
            "tools_used": ["file_list"],
            "metadata": {"action_guard_retried": True},
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is False


def test_dispatch_failure_without_guard_verdict_still_requires_checkpoint() -> None:
    task = Task(
        label="plain-failure",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "produce the file",
            "result": "crashed",
            "success": False,
            "tools_used": ["file_write"],
            "metadata": {},
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is False


def test_dispatch_network_failure_after_tool_effect_uses_safe_checkpoint() -> None:
    task = Task(
        label="interrupted-provider-stream",
        status=TaskStatus.ERROR,
        data={
            "_agent_run_checkpoint": {
                "request_run_id": str(uuid4()),
                "driver_code": "internal",
                "runtime_run_id": "run-interrupted",
                "status": "running",
                "data": {"version": 2, "resume_safe": True},
            }
        },
        execution_result={
            "prompt": "produce the file",
            "result": (
                "RemoteProtocolError: peer closed connection without sending complete "
                "message body (incomplete chunked read)"
            ),
            "success": False,
            "tools_used": ["console_exec"],
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is True


def test_dispatch_failure_after_delivery_still_requires_safe_checkpoint() -> None:
    task = Task(
        label="delivered",
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "reply",
            "result": "delivered",
            "success": False,
            "tools_used": ["messenger_reply"],
        },
    )

    assert scheduler._retry_is_safe(  # pyright: ignore[reportPrivateUsage]
        task,
        TaskStatus.DISPATCH,
    ) is False


@pytest.mark.asyncio
async def test_failed_planner_retry_stays_in_plan_phase(db) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="planner-output-error",
        objective="Break down this objective",
        status=TaskStatus.ERROR,
        effort="high",
        ai=True,
        cost=0.0,
        lease_token=lease_token,
        feedback="Planning failed",
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.PLAN.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()

    await scheduler._fail_claim(  # pyright: ignore[reportPrivateUsage]
        task_id,
        TaskStatus.PLAN,
        lease_token,
        RuntimeError("invalid structured output"),
    )

    db.expire_all()
    retried = await db.scalar(select(Task).where(Task.id == task_id))
    retried_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    assert retried is not None
    assert retried.status == TaskStatus.PLAN
    assert retried.next_attempt_at is not None
    assert retried_attempt is not None
    assert retried_attempt.status == TaskAttemptStatus.RETRY.value

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_completed_claim_retries_network_decomposition_failure(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, lease_token = uuid4(), uuid4()
    error = (
        "Échec de la décomposition de l’objectif : peer closed connection without "
        "sending complete message body (incomplete chunked read)"
    )
    task = Task(
        id=task_id,
        label="network-planner-failure",
        objective="Build a professional PDF",
        status=TaskStatus.ERROR,
        effort="high",
        ai=True,
        cost=0.0,
        lease_token=lease_token,
        feedback=error,
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.PLAN.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()
    wake_calls: list[tuple[UUID, float]] = []
    monkeypatch.setattr(
        scheduler,
        "wake",
        lambda current_id, *, delay=0.0: wake_calls.append((current_id, delay)),
    )

    await scheduler._complete_claim(  # pyright: ignore[reportPrivateUsage]
        task_id,
        TaskStatus.PLAN,
        lease_token,
    )

    db.expire_all()
    retried = await db.scalar(select(Task).where(Task.id == task_id))
    retried_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    assert retried is not None
    assert retried.status == TaskStatus.PLAN
    assert retried.get_execution_result() is None
    assert retried.next_attempt_at is not None
    assert retried_attempt is not None
    assert retried_attempt.status == TaskAttemptStatus.RETRY.value
    assert retried_attempt.retryable is True
    assert retried_attempt.data is not None
    assert retried_attempt.data["network_failure"] is True
    assert wake_calls == [(task_id, 30.0)]

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_failure_recovery_finalizes_already_successful_claim(db) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="completed-before-claim-finalization",
        status=TaskStatus.SUCCESS,
        ai=True,
        cost=1.25,
        lease_token=lease_token,
        lease_owner="stopped-worker",
        lease_expires_at=datetime.now(timezone.utc),
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        worker_id="stopped-worker",
        lease_token=lease_token,
        data={"base_cost": 0.25},
    )
    db.add_all([task, attempt])
    await db.commit()

    await scheduler._fail_claim(  # pyright: ignore[reportPrivateUsage]
        task_id,
        TaskStatus.DISPATCH,
        lease_token,
        TimeoutError("Scheduler lease expired before finalization."),
    )

    db.expire_all()
    recovered = await db.scalar(select(Task).where(Task.id == task_id))
    recovered_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    assert recovered is not None
    assert recovered.status == TaskStatus.SUCCESS
    assert recovered.lease_token is None
    assert recovered.lease_owner is None
    assert recovered.lease_expires_at is None
    assert recovered.consecutive_failures == 0
    assert recovered.last_error is None
    assert recovered_attempt is not None
    assert recovered_attempt.status == TaskAttemptStatus.SUCCESS.value
    assert recovered_attempt.finished_at is not None
    assert recovered_attempt.cost == 1.0

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [True, False])
async def test_orphan_recovery_is_side_effect_and_history_safe(
    db, monkeypatch: pytest.MonkeyPatch, acknowledged: bool
) -> None:
    safe = Task(
        id=uuid4(), label="orphan-safe", status=TaskStatus.EXEC, ai=True, cost=0.0
    )
    unsafe = Task(
        id=uuid4(),
        label="orphan-with-tool",
        status=TaskStatus.EXEC,
        ai=True,
        cost=0.0,
        data={} if acknowledged else {"_agent_run_identity": {
            "request_run_id": str(uuid4()), "driver_code": "arbitrary-remote-driver",
        }},
        execution_result={
            "prompt": "test",
            "result": "partial",
            "success": False,
            "cost": 0.0,
            "tools_used": ["external_write"],
        } if acknowledged else None,
    )
    deleted = Task(
        id=uuid4(),
        label="orphan-deleted",
        status=TaskStatus.EXEC,
        ai=True,
        cost=0.0,
        deleted_at=datetime.now(timezone.utc),
    )
    db.add_all([safe, unsafe, deleted])
    await db.commit()
    safe_id, unsafe_id, deleted_id = safe.id, unsafe.id, deleted.id

    terminal_resume = AsyncMock()
    monkeypatch.setattr(scheduler, "_resume_after_terminal_failure", terminal_resume)
    scheduler._last_lease_recovery = 0.0  # pyright: ignore[reportPrivateUsage]

    await scheduler._recover_expired_leases()  # pyright: ignore[reportPrivateUsage]

    db.expire_all()
    rows = {
        task.id: task
        for task in (
            await db.scalars(
                select(Task)
                .where(Task.id.in_([safe_id, unsafe_id, deleted_id]))
                .execution_options(include_historized=True)
            )
        ).all()
    }
    assert rows[safe_id].status == TaskStatus.DISPATCH
    assert rows[unsafe_id].status == TaskStatus.ERROR
    assert rows[deleted_id].status == TaskStatus.EXEC
    terminal_resume.assert_awaited_once_with(unsafe_id)

    await db.execute(delete(Task).where(Task.id.in_([safe_id, unsafe_id, deleted_id])))
    await db.commit()


@pytest.mark.asyncio
async def test_terminal_failure_preserves_partial_tool_trace(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="partial-tool-failure",
        objective="write externally",
        status=TaskStatus.DISPATCH,
        ai=True,
        cost=1.25,
        lease_token=lease_token,
        execution_result={
            "prompt": "write externally",
            "result": "partial result",
            "success": True,
            "cost": 1.25,
            "tools_used": ["external_write"],
        },
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()

    terminal_resume = AsyncMock()
    monkeypatch.setattr(scheduler, "_resume_after_terminal_failure", terminal_resume)

    await scheduler._fail_claim(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, lease_token, RuntimeError("provider failed")
    )

    db.expire_all()
    failed = await db.scalar(select(Task).where(Task.id == task_id))
    assert failed is not None
    result = failed.get_execution_result()
    assert result is not None
    assert result.success is False
    assert result.result == "partial result"
    assert result.tools_used == ["external_write"]
    assert result.cost == 1.25
    terminal_resume.assert_awaited_once_with(task_id)

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_reasoning_degeneration_fails_without_retry(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="degenerate-reasoning",
        objective="Complete the work",
        status=TaskStatus.EXEC,
        ai=True,
        lease_token=lease_token,
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()

    terminal_resume = AsyncMock()
    monkeypatch.setattr(scheduler, "_resume_after_terminal_failure", terminal_resume)

    await scheduler._fail_claim(  # pyright: ignore[reportPrivateUsage]
        task_id,
        TaskStatus.DISPATCH,
        lease_token,
        ReasoningDegenerationError("same reasoning pattern repeated more than 30 times"),
    )

    db.expire_all()
    failed = await db.scalar(select(Task).where(Task.id == task_id))
    failed_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    assert failed is not None
    assert failed.status == TaskStatus.ERROR
    assert failed.next_attempt_at is None
    assert failed_attempt is not None
    assert failed_attempt.status == TaskAttemptStatus.ERROR.value
    assert failed_attempt.retryable is False
    assert failed_attempt.data["reasoning_degeneration"] is True
    terminal_resume.assert_awaited_once_with(task_id)

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_complete_claim_surfaces_failed_execution_result_error(db) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="provider-failed",
        objective="Build the PDF report.",
        status=TaskStatus.ERROR,
        ai=True,
        cost=1.25,
        lease_token=lease_token,
        execution_result={
            "prompt": "Build the PDF report.",
            "result": (
                "RuntimeError: model provider is unavailable"
            ),
            "success": False,
            "cost": 0.0,
            "tools_used": ["console_exec"],
        },
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()

    await scheduler._complete_claim(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, lease_token
    )

    db.expire_all()
    failed_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    failed_task = await db.scalar(select(Task).where(Task.id == task_id))
    assert failed_attempt is not None
    assert failed_attempt.status == TaskAttemptStatus.ERROR.value
    assert failed_attempt.error is not None
    assert "RuntimeError" in failed_attempt.error
    assert failed_task is not None
    assert failed_task.last_error is not None
    assert "RuntimeError" in failed_task.last_error

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_complete_claim_records_waiting_children_after_partial_failure(db) -> None:
    task_id, lease_token = uuid4(), uuid4()
    task = Task(
        id=task_id,
        label="partial-coordination",
        objective="Ask two colleagues, then summarize.",
        status=TaskStatus.DISPATCH,
        paused=True,
        ai=True,
        cost=1.25,
        lease_token=lease_token,
        data={"pause_reasons": ["await", "child"]},
        execution_result={
            "prompt": "Ask two colleagues, then summarize.",
            "result": "Client disconnected during streaming",
            "success": False,
            "cost": 1.25,
            "tools_used": ["messenger_send_message_to_user", "task_run"],
        },
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase=TaskStatus.DISPATCH.value,
        worker_id="test-worker",
        lease_token=lease_token,
        data={"base_cost": 0.0},
    )
    db.add_all([task, attempt])
    await db.commit()

    await scheduler._complete_claim(  # pyright: ignore[reportPrivateUsage]
        task_id, TaskStatus.DISPATCH, lease_token
    )

    db.expire_all()
    completed_attempt = await db.scalar(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id)
    )
    completed_task = await db.scalar(select(Task).where(Task.id == task_id))
    assert completed_attempt is not None
    assert completed_attempt.status == TaskAttemptStatus.WAITING_CHILDREN.value
    assert completed_attempt.error == "Client disconnected during streaming"
    assert (completed_attempt.data or {}).get("partial_execution_failure") is True
    assert (completed_attempt.data or {}).get("pause_reasons") == ["await", "child"]
    assert completed_task is not None
    assert completed_task.status == TaskStatus.DISPATCH
    assert completed_task.paused is True
    assert completed_task.lease_token is None

    await db.execute(delete(TaskAttempt).where(TaskAttempt.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()
