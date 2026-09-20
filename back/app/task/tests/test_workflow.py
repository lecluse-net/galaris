from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.task import task_service
from app.task.models import Task, TaskStatus
from app.task.schemas import TaskUpdate
from app.task.workflow import (
    InvalidTaskTransition,
    TaskAction,
    TaskEvent,
    scheduler_action,
    transition,
)
from app.topic import Topic


@pytest.mark.parametrize("seed", [20260906, 0, 1, 7, 42, 65537, 104729, 2147483647])
def test_generated_event_sequences_preserve_terminal_and_rejection_invariants(seed):
    """Deterministic property corpus independent of the transition table's source sets."""
    import random

    explicit_retries = {TaskEvent.RETRY, TaskEvent.RETRY_PLAN,
                        TaskEvent.RETRY_DELIVERY, TaskEvent.RETRY_ROUTING}
    random_source = random.Random(seed)
    for _ in range(100):
        task = _task(random_source.choice(list(TaskStatus)))
        task.feedback = "Previously verified result"
        task.execution_result = {"result": "Durable evidence", "success": True}
        history = []
        for _ in range(100):
            previous = task.status
            event = random_source.choice(list(TaskEvent))
            history.append((previous, event))
            try:
                transition(task, event)
            except InvalidTaskTransition:
                assert task.status == previous, (seed, history)
            else:
                if previous in {TaskStatus.SUCCESS, TaskStatus.ERROR} and event not in explicit_retries:
                    assert task.status == previous, (seed, history)
            assert task.feedback == "Previously verified result", (seed, history)
            assert task.execution_result == {"result": "Durable evidence", "success": True}, (seed, history)
            if task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
                assert scheduler_action(task.status) is None


def _task(status: TaskStatus = TaskStatus.CREATE) -> Task:
    return Task(
        id=uuid4(),
        revision=1,
        label="Workflow",
        status=status,
        paused=False,
        ai=False,
        cost=0.0,
    )


def test_typed_workflow_covers_execution_and_plan_paths() -> None:
    execution = _task()
    assert scheduler_action(execution.status) == TaskAction.DISPATCH
    transition(execution, TaskEvent.ROUTE_TO_EXECUTION)
    assert scheduler_action(execution.status) == TaskAction.EXECUTE
    transition(execution, TaskEvent.START_EXECUTION)
    transition(execution, TaskEvent.EXECUTION_SUCCEEDED)
    assert execution.status == TaskStatus.SUCCESS
    assert scheduler_action(execution.status) is None

    planned = _task()
    transition(planned, TaskEvent.ROUTE_TO_PLAN)
    assert scheduler_action(planned.status) == TaskAction.ADVANCE_PLAN
    transition(planned, TaskEvent.PLAN_SUCCEEDED)
    assert planned.status == TaskStatus.SUCCESS


def test_task_state_machine_accepts_an_explicit_briefing_route() -> None:
    task = _task()
    task.effort = "high"

    transition(task, TaskEvent.ROUTE_TO_BRIEFING)
    assert task.status == TaskStatus.BRIEFING
    assert scheduler_action(task.status) == TaskAction.BRIEF

    transition(task, TaskEvent.BRIEFING_SUCCEEDED)
    assert task.status == TaskStatus.DISPATCH
    assert scheduler_action(task.status) == TaskAction.EXECUTE


def test_terminal_task_cannot_restart_without_explicit_retry_path() -> None:
    task = _task(TaskStatus.SUCCESS)
    with pytest.raises(InvalidTaskTransition):
        transition(task, TaskEvent.START_EXECUTION)

    failed = _task(TaskStatus.ERROR)
    transition(failed, TaskEvent.RETRY)
    assert failed.status == TaskStatus.DISPATCH

    failed_plan = _task(TaskStatus.ERROR)
    transition(failed_plan, TaskEvent.RETRY_PLAN)
    assert failed_plan.status == TaskStatus.PLAN

    delivered_missing = _task(TaskStatus.SUCCESS)
    transition(delivered_missing, TaskEvent.RETRY_DELIVERY)
    assert delivered_missing.status == TaskStatus.DISPATCH

    routing_failed = _task(TaskStatus.ERROR)
    transition(routing_failed, TaskEvent.RETRY_ROUTING)
    assert routing_failed.status == TaskStatus.CREATE


@pytest.mark.parametrize("status", [TaskStatus.DISPATCH, TaskStatus.BRIEFING])
def test_revision_returns_unstarted_work_to_dispatcher(status: TaskStatus) -> None:
    task = _task(status)

    transition(task, TaskEvent.REVISE)

    assert task.status == TaskStatus.CREATE
    assert scheduler_action(task.status) == TaskAction.DISPATCH


def test_running_revision_interrupts_before_returning_to_dispatcher() -> None:
    task = _task(TaskStatus.EXEC)

    transition(task, TaskEvent.INTERRUPT_EXECUTION)
    transition(task, TaskEvent.REVISE)

    assert task.status == TaskStatus.CREATE


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.CREATE,
        TaskStatus.PAUSE,
        TaskStatus.DISPATCH,
        TaskStatus.BRIEFING,
        TaskStatus.EXEC,
        TaskStatus.PLAN,
    ],
)
def test_force_terminate_is_terminal_from_every_active_phase(
    status: TaskStatus,
) -> None:
    task = _task(status)

    transition(task, TaskEvent.FORCE_TERMINATE)

    assert task.status == TaskStatus.ERROR
    assert scheduler_action(task.status) is None


@pytest.mark.parametrize("status", [TaskStatus.SUCCESS, TaskStatus.ERROR])
def test_terminal_task_cannot_be_reopened_by_collaboration(status: TaskStatus) -> None:
    with pytest.raises(InvalidTaskTransition):
        transition(_task(status), TaskEvent.RESUME_COLLABORATION)


def test_collaboration_resumes_only_from_non_terminal_dispatch() -> None:
    task = _task(TaskStatus.DISPATCH)
    transition(task, TaskEvent.RESUME_COLLABORATION)
    assert task.status == TaskStatus.DISPATCH


def test_public_update_schema_rejects_engine_owned_fields() -> None:
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate(
            {"expected_revision": 1, "label": "Tentative", "status": "SUCCESS"}
        )


@pytest.mark.asyncio
async def test_public_update_uses_optimistic_revision(db: AsyncSession) -> None:
    task = _task()
    db.add(task)
    await db.commit()
    await db.refresh(task)
    task_id = task.id
    initial_revision = task.revision

    updated = await task_service.update(
        task_id,
        TaskUpdate(expected_revision=initial_revision, label="Revised"),
    )
    assert updated is not None
    assert updated.label == "Revised"
    assert updated.revision == initial_revision + 1

    with pytest.raises(task_service.TaskRevisionConflict):
        await task_service.update(
            task_id,
            TaskUpdate(expected_revision=initial_revision, label="Stale write"),
        )

    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()


@pytest.mark.asyncio
async def test_public_update_allows_only_topic_during_an_active_lease(
    db: AsyncSession,
) -> None:
    topic = Topic(title="Manual active topic")
    task = _task(TaskStatus.EXEC)
    task.lease_token = uuid4()
    task.lease_owner = "test-worker"
    task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.add_all([topic, task])
    await db.commit()
    await db.refresh(task)
    initial_revision = task.revision

    updated = await task_service.update(
        task.id,
        TaskUpdate(expected_revision=task.revision, topic_id=topic.id),
    )
    assert updated is not None
    assert updated.topic_id == topic.id
    assert updated.revision == initial_revision

    with pytest.raises(task_service.TaskEditConflict):
        await task_service.update(
            task.id,
            TaskUpdate(expected_revision=updated.revision, label="Forbidden while running"),
        )
