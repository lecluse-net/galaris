"""
Task management service.

Usage:
    >>> from app.task import task_service
    >>> tasks = await task_service.get_all()
"""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import (
    String,
    Select,
    cast,
    delete as sa_delete,
    func,
    or_,
    select,
    update as sa_update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError
from collections.abc import Collection
from typing import Any, Literal, Sequence, Optional, Union, cast as type_cast
from uuid import UUID, NAMESPACE_URL, uuid5
from loguru import logger
from core import websocket
from core.database import get_db
from core.i18n import current_language, is_supported, render_prompt, tr
from app.agent.contracts import ReasoningEffort
from .models import Task, TaskAttempt, TaskAttemptStatus, TaskStatus
from .schemas import TaskUpdate, TaskCreate, Task as TaskSchema, TaskOverview
from .workflow import TaskEvent, transition
from ..agent.models import Agent

_TERMINAL_STATUSES = (TaskStatus.SUCCESS, TaskStatus.ERROR)
_ACTIVE_STATUSES = (
    TaskStatus.DISPATCH,
    TaskStatus.BRIEFING,
    TaskStatus.EXEC,
    TaskStatus.PLAN,
)

# Unified suspension model
# A suspended task has ``paused=True`` regardless of the reason, while ``status`` remains the
# resume phase. The scheduler only checks ``paused``. Additive reasons in
# ``data['pause_reasons']`` identify who can resume the task: ``user`` requires a human action,
# while other reasons clear automatically when their dependency resolves. A task can combine a
# user hold with one or more automatic reasons.
PAUSE_USER = "user"        # Human hold cleared by resume_tree.
PAUSE_AWAIT = "await"      # Waiting for a peer response.
PAUSE_PLAN = "plan"        # Waiting for a plan child task.
PAUSE_CLARIFY = "clarify"  # Waiting for a clarification response.
PAUSE_CHILD = "child"      # Waiting for a delegated child in the call-stack model.
_AUTO_PAUSE_REASONS = (PAUSE_AWAIT, PAUSE_PLAN, PAUSE_CLARIFY, PAUSE_CHILD)

# Marker on a child created through ``task_run``. Its creator waits with the ``child`` pause
# reason and resumes when the child terminates.
DELEGATED_KEY = "delegated"
RETENTION_KEY = "retention_reasons"
_DELIVERY_RECOVERY_DATA_KEY = "delivery_recovery"
_AGENT_RUN_CHECKPOINT_DATA_KEY = "_agent_run_checkpoint"


class TaskConflictError(RuntimeError):
    """Domain or concurrency conflict while applying a task command."""


class TaskRevisionConflict(TaskConflictError):
    """The client edited a revision that is no longer current."""


class TaskEditConflict(TaskConflictError):
    """An immutable execution field was changed after the task started."""


def pause_reasons(task: Task) -> list[str]:
    data: dict[str, Any] = task.data if isinstance(task.data, dict) else {}
    raw: Any = data.get("pause_reasons")
    if not isinstance(raw, list):
        return []
    return [str(r) for r in type_cast(list[Any], raw)]


def is_paused_for(task: Task, reason: str) -> bool:
    return reason in pause_reasons(task)


def is_held_by_user(task: Task) -> bool:
    return PAUSE_USER in pause_reasons(task)


def _write_reasons(task: Task, reasons: list[str]) -> None:
    data = dict(task.data) if isinstance(task.data, dict) else {}
    if reasons:
        data["pause_reasons"] = reasons
    else:
        data.pop("pause_reasons", None)
    # Do not materialize an empty dictionary. Preserving ``data=None`` allows callers such as
    # ``_message_origin_room_id`` to fall back to ``message_group_id``.
    task.data = data or None
    task.paused = bool(reasons)


def suspend(task: Task, reason: str) -> None:
    """Add a pause reason; ``status`` must already identify the resume phase."""
    reasons = pause_reasons(task)
    if reason not in reasons:
        reasons.append(reason)
    _write_reasons(task, reasons)


def release(task: Task, reason: str) -> bool:
    """Remove a reason and return whether another reason still keeps the task paused."""
    _write_reasons(task, [r for r in pause_reasons(task) if r != reason])
    return task.paused


def clear_pauses(task: Task) -> None:
    """Clear every pause reason after completion, cancellation, or manual restart."""
    _write_reasons(task, [])


def retention_reasons(task: Task) -> list[str]:
    """Return durable reasons that temporarily forbid Task deletion or purging."""

    data: dict[str, Any] = task.data if isinstance(task.data, dict) else {}
    raw: Any = data.get(RETENTION_KEY)
    if not isinstance(raw, list):
        return []
    return [str(reason) for reason in type_cast(list[Any], raw)]


def retain(task: Task, reason: str) -> None:
    """Keep a Task available while another subsystem still needs its result."""

    reasons = retention_reasons(task)
    if reason not in reasons:
        reasons.append(reason)
    data = dict(task.data) if isinstance(task.data, dict) else {}
    data[RETENTION_KEY] = reasons
    task.data = data


def release_retention(task: Task, reason: str) -> None:
    """Release one retention reason without disturbing unrelated Task metadata."""

    reasons = [value for value in retention_reasons(task) if value != reason]
    data = dict(task.data) if isinstance(task.data, dict) else {}
    if reasons:
        data[RETENTION_KEY] = reasons
    else:
        data.pop(RETENTION_KEY, None)
    task.data = data or None


async def get_all(
    skip: int = 0,
    limit: int = 50,
    agent_id: Optional[int] = None,
    goal_id: UUID | None = None,
    agent_ids: Collection[int] | None = None,
) -> Sequence[Task]:
    """Return all tasks that have not been deleted."""
    db = get_db()
    query = (
        select(Task)
        .order_by(Task.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if agent_id is not None:
        query = query.where(Task.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    if goal_id is not None:
        query = query.where(Task.goal_id == goal_id)
    query = Task.histo_filter(query)
    result = await db.execute(query)
    return result.scalars().all()


async def get_active(
    limit: int = 10,
    *,
    agent_ids: Collection[int] | None = None,
) -> Sequence[Task]:
    """Return non-paused tasks that are actively being processed, newest first."""
    db = get_db()
    query = (
        select(Task)
        .where(Task.status.in_(_ACTIVE_STATUSES), Task.paused.is_(False))
        .order_by(Task.updated_at.desc(), Task.id.desc())
        .limit(limit)
    )
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    result = await db.execute(Task.histo_filter(query))
    return result.scalars().all()


async def get_by_id(task_id: UUID) -> Optional[Task]:
    """Return a task by ID."""
    db = get_db()
    query = (
        select(Task)
        .options(selectinload(Task.agent).selectinload(Agent.title))
        .options(selectinload(Task.requester_agent).selectinload(Agent.title))
        .where(Task.id == task_id)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _get_by_id_for_update(task_id: UUID) -> Optional[Task]:
    """Load and lock a task for a transactional HTTP command."""

    db = get_db()
    query = select(Task).where(Task.id == task_id).with_for_update()
    return await db.scalar(Task.histo_filter(query))


async def get_children(parent_id: UUID) -> Sequence[Task]:
    """Return a task's children in creation order."""
    db = get_db()
    query = (
        select(Task)
        .where(Task.parent_id == parent_id)
        .order_by(Task.created_at.asc(), Task.id.asc())
    )
    query = Task.histo_filter(query)
    result = await db.execute(query)
    return result.scalars().all()


def build(task_data: TaskCreate) -> Task:
    """Construct a Task with the same normalization used by every creation path."""

    messages = task_data.messages
    data = task_data.model_dump(exclude={"messages"})
    new_task = Task(**data)
    # Preserve the admitted demand when a later amendment replaces the objective.
    # This server-owned field cannot be supplied or patched through TaskUpdate.
    new_task.data = {**(new_task.data or {}), "_original_demand": new_task.objective or ""}
    if messages is not None:
        new_task.messages = messages
    # A task created as paused without an explicit reason is a human hold. Materialize the
    # ``user`` reason so it can be resumed safely. Explicit internal pause reasons are preserved.
    if new_task.paused and not pause_reasons(new_task):
        suspend(new_task, PAUSE_USER)
    return new_task


async def apply_requester_lineage(task: Task) -> None:
    """Freeze the human requester from trusted creation context or Task ancestry."""

    if task.requester_user_id is not None:
        return
    from core.user import get_current_user_id

    requester_user_id = get_current_user_id()
    for lineage_id in (task.parent_id, task.source_task_id):
        if requester_user_id is not None or lineage_id is None:
            continue
        parent = await get_db().get(Task, lineage_id)
        if parent is not None:
            requester_user_id = parent.requester_user_id or parent.created_by
    task.requester_user_id = requester_user_id


async def publish_created(task: Task) -> None:
    """Publish a Task after its surrounding transaction has committed."""

    await websocket.emit(
        "task",
        "create",
        TaskSchema.model_validate(task).model_dump(mode="json"),
        None,
    )


async def create(task_data: TaskCreate, *, idempotency_key: str | None = None) -> Task:
    """Create a task."""
    db = get_db()
    submission_id: UUID | None = None
    if idempotency_key is not None:
        submission_id = uuid5(NAMESPACE_URL, f"galaris:task:{task_data.agent_id}:{idempotency_key}")
        # Serialize competing submissions, including a replay after creation was
        # committed but its caller did not receive the receipt.
        lock_key = int.from_bytes(submission_id.bytes[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
        existing = await db.scalar(
            select(Task).where(Task.id == submission_id)
            .execution_options(include_historized=True)
        )
        if existing is not None:
            await db.commit()
            return existing
    await apply_goal_lineage(task_data)
    await apply_reasoning_effort_lineage(task_data)
    new_task = build(task_data)
    if submission_id is not None:
        new_task.id = submission_id
    await apply_requester_lineage(new_task)
    await apply_topic_lineage(new_task, db=db)
    new_task.data = {
        **(new_task.data or {}),
        "language": await current_language(
            (new_task.data or {}).get("language"), user_id=new_task.requester_user_id,
        ),
    }
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    await publish_created(new_task)

    return new_task


async def create_from_messenger(
    task_data: TaskCreate,
    messenger_message_id: UUID,
) -> tuple[Task, bool]:
    """Create the unique Task admitted from one canonical Messenger message.

    The caller serializes on the owning journal row. The database uniqueness constraint remains
    the final cross-process guard, while this lookup makes a crash redelivery an idempotent read.
    Soft-deleted Tasks still count as an applied effect and are deliberately returned.
    """

    db = get_db()
    existing = await db.scalar(
        select(Task)
        .where(Task.messenger_message_id == messenger_message_id)
        .execution_options(include_historized=True)
    )
    if existing is not None:
        return existing, False

    await apply_goal_lineage(task_data)
    new_task = build(task_data)
    new_task.messenger_message_id = messenger_message_id
    from app.messenger import Message

    message = await db.get(Message, messenger_message_id)
    new_task.requester_user_id = (
        message.requester_user_id if message is not None else None
    )
    await apply_topic_lineage(new_task, db=db)
    new_task.data = {
        **(new_task.data or {}),
        "language": await current_language(
            (new_task.data or {}).get("language"), user_id=new_task.requester_user_id,
        ),
    }
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    await publish_created(new_task)
    return new_task, True


async def save(task: Task) -> Task:
    """Persist an internal mutation already validated by the engine.

    This is not a generic patch endpoint. Phase transitions must be applied through
    :mod:`app.task.workflow` before calling it.
    """
    saved = await update(task.id, task)
    if saved is None:  # Impossible for an already loaded ORM object.
        raise RuntimeError(f"Task {task.id} could not be persisted.")
    return saved


async def _persist_internal(task: Task) -> Task:
    """Persistence implementation restricted to internal ORM objects."""

    db = get_db()
    task_id = task.id
    try:
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        raise TaskRevisionConflict(
            render_prompt(
                await tr("task_api.errors.modified_concurrently"),
                task_id=task_id,
            )
        ) from exc
    await publish_updated(task)
    return task


async def publish_updated(task: Task) -> None:
    """Publish a change already committed by a domain operation."""
    await get_db().refresh(task)
    await websocket.emit(
        "task", "update", TaskSchema.model_validate(task).model_dump(mode="json"), None
    )


async def update(
    task_id: UUID, task_update: Union[TaskUpdate, Task]
) -> Optional[Task]:
    """Persist an internal task or apply a restricted human-authored patch.

    FastAPI only builds ``TaskUpdate``. The ``Task`` path is reserved for services that have
    already validated transitions through the state machine.
    """

    if isinstance(task_update, Task):
        if task_update.id != task_id:
            raise ValueError(f"Task ID mismatch: expected {task_id}, got {task_update.id}")
        return await _persist_internal(task_update)

    task = await _get_by_id_for_update(task_id)
    if task is None:
        return None
    if task.revision != task_update.expected_revision:
        raise TaskRevisionConflict(
            render_prompt(
                await tr("task_api.errors.revision_conflict"),
                expected=task_update.expected_revision,
                current=task.revision,
            )
        )

    update_data = task_update.model_dump(
        exclude_unset=True, exclude={"expected_revision"}
    )
    immutable_after_start = {
        "objective",
        "agent_id",
        "forced_route",
        "forced_effort",
        "reasoning_effort_override",
    }
    changed_immutable = {
        key
        for key in immutable_after_start.intersection(update_data)
        if getattr(task, key) != update_data[key]
    }
    if task.status != TaskStatus.CREATE and changed_immutable:
        raise TaskEditConflict(
            render_prompt(
                await tr("task_api.errors.immutable_fields"),
                fields=", ".join(sorted(changed_immutable)),
            )
        )
    if task.lease_token is not None and update_data:
        if set(update_data) != {"topic_id"}:
            raise TaskEditConflict(await tr("task_api.errors.action_running"))
        # Topic classification is execution-orthogonal. A leased executor may hold an ORM
        # instance at the current revision, so bumping that version here would make its next
        # durable transition stale. Update only this column and leave the execution revision
        # unchanged; every other human-authored field remains forbidden while the lease lives.
        db = get_db()
        await db.execute(
            sa_update(Task)
            .where(Task.id == task.id)
            .values(topic_id=update_data["topic_id"])
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        await db.refresh(task)
        await websocket.emit(
            "task", "update", TaskSchema.model_validate(task).model_dump(mode="json"), None
        )
        return task

    for key, value in update_data.items():
        setattr(task, key, value)
    return await save(task)


async def retry(task_id: UUID, expected_revision: int) -> Optional[Task]:
    """Explicit command to retry a failed task."""

    task = await _get_by_id_for_update(task_id)
    if task is None:
        return None
    if task.revision != expected_revision:
        raise TaskRevisionConflict(
            render_prompt(
                await tr("task_api.errors.revision_conflict"),
                expected=expected_revision,
                current=task.revision,
            )
        )
    data = dict(task.data) if isinstance(task.data, dict) else {}
    raw_recovery = data.get(_DELIVERY_RECOVERY_DATA_KEY)
    recovery = (
        type_cast(dict[str, Any], raw_recovery)
        if isinstance(raw_recovery, dict)
        else None
    )
    if recovery is not None and str(recovery.get("status") or "") == "ready":
        try:
            child_id = UUID(str(recovery.get("child_task_id") or ""))
        except ValueError as exc:
            raise TaskEditConflict("Invalid delivery-recovery child reference.") from exc
        child = await _get_by_id_for_update(child_id)
        if (
            child is None
            or child.parent_id != task.id
            or child.status not in (TaskStatus.SUCCESS, TaskStatus.ERROR)
        ):
            raise TaskEditConflict(
                "The delivery-only retry is no longer applicable to this Task."
            )
        filename = str(recovery.get("filename") or "").strip()
        destination = str(recovery.get("destination") or "").strip()
        tool_name = str(recovery.get("tool") or "").strip()
        if not filename or not destination or tool_name != "messenger_room_send_file":
            raise TaskEditConflict("The delivery-only retry contract is incomplete.")

        transition(task, TaskEvent.RETRY_PLAN)
        clear_pauses(task)
        suspend(task, PAUSE_PLAN)
        transition(child, TaskEvent.RETRY_DELIVERY)
        clear_pauses(child)

        child_data = dict(child.data) if isinstance(child.data, dict) else {}
        # Keep the effect journal: the delivery path also checks uncertain sends.
        child_data.update(
            {
                "artifact_policy": "final",
                "delivery_policy": "required",
                "plan_tools": [tool_name],
                _DELIVERY_RECOVERY_DATA_KEY: {
                    **recovery,
                    "status": "running",
                },
            }
        )
        recovery_contract = (
            "<delivery_recovery>\n"
            "The server verified that the final file already exists. Do not recreate, "
            "edit, inspect, or rediscover it. Perform exactly one delivery call and then "
            "report its recorded result.\n"
            f"Tool: {tool_name}\n"
            f"Room: {destination}\n"
            f"Filename: {filename}\n"
            "</delivery_recovery>"
        )
        prior_context = str(child_data.get("plan_context") or "").strip()
        child_data["plan_context"] = "\n\n".join(
            part for part in (prior_context, recovery_contract) if part
        )
        child.data = child_data
        child.execution_result = None
        child.briefing_result = None
        child.feedback = None
        child.last_error = None
        child.next_attempt_at = None
        child.consecutive_failures = 0
        child.cancel_requested = False
        child.effort = "standard"

        data[_DELIVERY_RECOVERY_DATA_KEY] = {
            **recovery,
            "status": "running",
        }
        task.data = data
        task.execution_result = None
        task.feedback = None
        await save(child)
    else:
        # A retry may recover acknowledged work, but never erase proof of an
        # ambiguous effect. The driver reconciles its journal before resuming.
        checkpoint = data.get(_AGENT_RUN_CHECKPOINT_DATA_KEY)
        if isinstance(checkpoint, dict):
            data[_AGENT_RUN_CHECKPOINT_DATA_KEY] = {
                **checkpoint, "result": None, "status": "interrupted",
            }
        task.data = data
        transition(task, TaskEvent.RETRY)
        transition(task, TaskEvent.ROUTE_TO_EXECUTION)
        task.execution_result = None
        task.feedback = None
    clear_pauses(task)
    if recovery is not None and str(recovery.get("status") or "") == "ready":
        suspend(task, PAUSE_PLAN)
    task.last_error = None
    task.next_attempt_at = None
    task.consecutive_failures = 0
    task.cancel_requested = False
    return await save(task)


async def cancel(task_id: UUID, expected_revision: int) -> Optional[Task]:
    """Explicit terminal cancellation command, represented as a domain error."""

    task = await _get_by_id_for_update(task_id)
    if task is None:
        return None
    if task.revision != expected_revision:
        raise TaskRevisionConflict(
            render_prompt(
                await tr("task_api.errors.revision_conflict"),
                expected=expected_revision,
                current=task.revision,
            )
        )
    await request_cancellation(task)
    return await save(task)


async def request_cancellation(task: Task) -> None:
    """Stage the canonical stop in the current transaction."""
    from app.task import scheduler

    transition(task, TaskEvent.CANCEL)
    scheduler.cancel(task.id)
    task.cancel_requested = task.lease_token is not None
    task.last_error = await tr("task_api.errors.cancelled_by_user")
    task.feedback = task.last_error
    task.next_attempt_at = None
    clear_pauses(task)


async def force_terminate(
    task_id: UUID,
    expected_revision: int | None,
    *,
    notify_terminal: bool = True,
) -> Optional[Task]:
    """Make a Task durably terminal without waiting for its current worker.

    The command also closes an unfinished Goal cycle attached to the Task and then
    runs the normal terminal lifecycle so parents and coordination waits can resume.
    """

    from app.goal.facade import (
        close_cycle_for_forced_task,
        enqueue_children_for_forced_task,
        lock_cycle_for_forced_task,
    )
    from app.task import scheduler

    db = get_db()
    goal_context = await lock_cycle_for_forced_task(task_id)
    task = await _get_by_id_for_update(task_id)
    if task is None:
        return None
    if expected_revision is not None and task.revision != expected_revision:
        raise TaskRevisionConflict(
            render_prompt(
                await tr("task_api.errors.revision_conflict"),
                expected=expected_revision,
                current=task.revision,
            )
        )

    was_terminal = task.status in _TERMINAL_STATUSES
    reason = await tr("task_api.errors.force_terminated_by_user")
    now = datetime.now(timezone.utc)
    lease_token = task.lease_token

    if was_terminal and lease_token is None and goal_context is None:
        return task
    scheduler.cancel(task.id)
    if not was_terminal:
        transition(task, TaskEvent.FORCE_TERMINATE)
    if lease_token is not None:
        attempt = await db.scalar(
            select(TaskAttempt)
            .where(TaskAttempt.lease_token == lease_token)
            .with_for_update()
        )
        if attempt is not None and attempt.finished_at is None:
            attempt.status = TaskAttemptStatus.CANCELLED.value
            attempt.finished_at = now
            attempt.retryable = False
            attempt.error = reason
            attempt.data = {**(attempt.data or {}), "force_terminated": True}

    task.lease_token = None
    task.lease_owner = None
    task.lease_expires_at = None
    task.cancel_requested = False
    task.next_attempt_at = None
    if not was_terminal:
        task.last_error = reason
        task.feedback = reason
    clear_pauses(task)

    goal_id: UUID | None = None
    if goal_context is not None:
        goal_id = close_cycle_for_forced_task(
            goal_context,
            task_cost=task.cost,
            finished_at=now,
        )
        await enqueue_children_for_forced_task(goal_context)
        release_retention(task, "goal_judgement")

    saved = await _persist_internal(task)
    if goal_id is not None:
        from app.goal import goal_service

        await goal_service.emit_updated(goal_id)
        scheduler.wake()
    if not was_terminal and notify_terminal:
        from app.agent import handle_terminal_task
        from app.task.agent_adapter import as_agent_task

        await handle_terminal_task(as_agent_task(saved))
    return saved


async def is_auto_approved(task: Task) -> bool:
    """Return whether the task or a same-agent ancestor enables ``auto_approve``.

    Auto-approval covers only the subtree owned by the same agent. Walking ancestors makes a
    root change apply immediately to descendants, but traversal stops at every agent boundary.
    Work delegated to another agent remains subject to approval even below an auto-approved
    objective. Human consent for one agent never grants transitive privileges to another.
    """
    current: Task = task
    seen: set[UUID] = set()
    while current.id not in seen:  # Cycle guard; ``current`` is always a Task here.
        if current.auto_approve:
            return True
        seen.add(current.id)
        if current.parent_id is None:
            return False
        parent = await get_by_id(current.parent_id)
        # An auto-approval owned by another agent does not cross this boundary.
        if parent is None or parent.agent_id != current.agent_id:
            return False
        current = parent
    return False


ApprovalAction = Literal["auto", "deny_agent", "ask"]


async def approval_action(task: Task) -> ApprovalAction:
    """Choose how to handle an executor approval request for ``task``.

    ``auto`` approves through an inherited policy. ``deny_agent`` rejects a request whose
    conversation peer is another AI because only humans can approve. ``ask`` opens a question
    for a human peer. Explicit auto-approval takes precedence over the AI-peer rejection.
    """
    if await is_auto_approved(task):
        return "auto"
    if task.ai:
        return "deny_agent"
    return "ask"


async def apply_source_lineage(
    new_task: Union[TaskCreate, Task], source_task_id: Optional[UUID]
) -> None:
    """Attach ``new_task`` to the task that created it through ``task_run``.

    In the call-stack model, the delegated task becomes a true child of its creator.
    ``source_task_id`` records causality, ``parent_id`` places it directly below the source,
    and ``delegated`` marks it as an awaited child. The creator pauses until it terminates.

    The detected source language is inherited unless the new task already has one. Delegation
    must not fall back to English when it passes through the dispatcher. A missing source is a
    no-op, and an existing ``parent_id`` is never overwritten.
    """
    if source_task_id is None:
        return
    new_task.source_task_id = source_task_id
    data = dict(new_task.data) if isinstance(new_task.data, dict) else {}
    data[DELEGATED_KEY] = True
    source = await get_by_id(source_task_id)
    if source is not None:
        if new_task.goal_id is None:
            new_task.goal_id = source.goal_id
        if new_task.reasoning_effort_override is None:
            new_task.reasoning_effort_override = type_cast(
                ReasoningEffort | None,
                source.reasoning_effort_override,
            )
        source_data = source.data if isinstance(source.data, dict) else {}
        source_language = str(source_data.get("language") or "").strip().lower()
        if "language" not in data and is_supported(source_language):
            data["language"] = source_language
    new_task.data = data
    if getattr(new_task, "parent_id", None) is not None:
        return
    if source is not None:
        new_task.parent_id = source.id  # Direct child of the creator in the call stack.


async def apply_goal_lineage(new_task: Union[TaskCreate, Task]) -> None:
    """Inherit Goal audit lineage from a causal source or parent Task.

    This is deliberately a generic Task creation rule: Goal does not influence routing,
    planning, execution, or collaboration. Explicit lineage always wins.
    """

    if new_task.goal_id is not None:
        return
    related_task_id = new_task.source_task_id or new_task.parent_id
    if related_task_id is None:
        return
    query = select(Task.goal_id).where(Task.id == related_task_id)
    new_task.goal_id = await get_db().scalar(Task.histo_filter(query))


async def apply_reasoning_effort_lineage(
    new_task: Union[TaskCreate, Task],
) -> None:
    """Inherit a Task-scoped reasoning override from its causal lineage."""

    if new_task.reasoning_effort_override is not None:
        return
    related_task_id = new_task.source_task_id or new_task.parent_id
    if related_task_id is None:
        return
    query = select(Task.reasoning_effort_override).where(Task.id == related_task_id)
    new_task.reasoning_effort_override = type_cast(
        ReasoningEffort | None,
        await get_db().scalar(Task.histo_filter(query)),
    )


async def apply_topic_lineage(
    new_task: Task,
    *,
    db: AsyncSession | None = None,
) -> None:
    """Copy Topic/contact scope from a causal Task during child creation."""

    if new_task.topic_id is not None and new_task.contact_memory_item_id is not None:
        return
    session = db or get_db()
    seen: set[UUID] = set()
    for related_task_id in (new_task.parent_id, new_task.source_task_id):
        if related_task_id is None or related_task_id in seen:
            continue
        seen.add(related_task_id)
        related = await session.scalar(
            Task.histo_filter(select(Task).where(Task.id == related_task_id))
        )
        if related is None:
            continue
        if new_task.topic_id is None:
            new_task.topic_id = related.topic_id
        if new_task.contact_memory_item_id is None:
            new_task.contact_memory_item_id = related.contact_memory_item_id
        topic_id = type_cast(UUID | None, new_task.topic_id)
        contact_id = type_cast(UUID | None, new_task.contact_memory_item_id)
        if topic_id is not None and contact_id is not None:
            return


async def pause_tree(task_id: UUID) -> Optional[Task]:
    """Pause a task and all unfinished descendants."""
    return await _set_tree_paused(task_id, paused=True)


async def resume_tree(task_id: UUID) -> Optional[Task]:
    """Resume a task and all unfinished descendants without changing their phase."""
    return await _set_tree_paused(task_id, paused=False)


async def preempt_running_agent_tasks(
    agent_id: Optional[int],
    *,
    exclude_task_id: UUID | None = None,
) -> list[UUID]:
    """Interrupt an agent's in-flight actions to prioritize a manual RUN.

    Interrupted tasks remain active and restartable. EXEC returns to DISPATCH for a clean replay,
    while DISPATCH and PLAN remain at their current resume phase.
    """
    if agent_id is None:
        return []

    from app.task import scheduler

    db = get_db()
    preempted: list[UUID] = []
    changed: list[Task] = []
    running_ids = set(
        scheduler.running_task_ids_for_agent(agent_id, exclude_task_id=exclude_task_id)
    )
    now = datetime.now(timezone.utc)
    remote_query = select(Task.id).where(
        Task.agent_id == agent_id,
        Task.lease_token.is_not(None),
        Task.lease_expires_at > now,
    )
    if exclude_task_id is not None:
        remote_query = remote_query.where(Task.id != exclude_task_id)
    running_ids.update((await db.scalars(Task.histo_filter(remote_query))).all())

    for running_task_id in running_ids:
        task = await get_by_id(running_task_id)
        if task is None:
            continue
        before = (task.status, task.cancel_requested)
        cancelled_locally = scheduler.cancel(task.id)
        if not cancelled_locally:
            task.cancel_requested = True
        preempted.append(task.id)
        if task.status == TaskStatus.EXEC:
            transition(task, TaskEvent.INTERRUPT_EXECUTION)
            transition(task, TaskEvent.ROUTE_TO_EXECUTION)
        if (task.status, task.cancel_requested) != before:
            changed.append(task)

    if changed:
        await db.commit()
        for task in changed:
            await db.refresh(task)
            await websocket.emit(
                "task",
                "update",
                TaskSchema.model_validate(task).model_dump(mode="json"),
                None,
            )
    return preempted


async def _set_tree_paused(task_id: UUID, *, paused: bool) -> Optional[Task]:
    db = get_db()
    root = await get_by_id(task_id)
    if root is None:
        return None

    tasks = await _collect_tree(root, set())
    changed: list[Task] = []
    for task in tasks:
        if paused and task.status in _TERMINAL_STATUSES:
            continue
        before = (task.paused, tuple(pause_reasons(task)), task.status)
        if paused:
            suspend(task, PAUSE_USER)
            _interrupt_running_action(task)
        else:
            release(task, PAUSE_USER)
            # If a plan child completed during a human hold, also clear the plan reason. The
            # parent-resume callback was intentionally skipped during the hold.
            if _plan_current_child_is_terminal(task, tasks):
                release(task, PAUSE_PLAN)
        if (task.paused, tuple(pause_reasons(task)), task.status) != before:
            changed.append(task)

    if changed:
        await db.commit()
        for task in changed:
            await db.refresh(task)
            await websocket.emit(
                "task",
                "update",
                TaskSchema.model_validate(task).model_dump(mode="json"),
                None,
            )
    return root


async def _collect_tree(task: Task, seen: set[UUID]) -> list[Task]:
    if task.id in seen:
        return []
    seen.add(task.id)

    tasks = [task]
    for child in await get_children(task.id):
        tasks.extend(await _collect_tree(child, seen))
    return tasks


def _interrupt_running_action(task: Task) -> bool:
    """Interrupt the in-flight scheduler action of a task being paused.

    The scheduler checks ``paused`` only before starting a step. Without cancellation, an
    existing dispatch, execution, or plan action would continue. Interrupted execution returns
    from EXEC to DISPATCH, while CREATE, DISPATCH, and PLAN remain directly resumable. Return
    whether the task status changed.
    """
    from app.task import scheduler

    cancelled_locally = scheduler.cancel(task.id)
    if not cancelled_locally and task.lease_token is None:
        return False
    if not cancelled_locally:
        task.cancel_requested = True
    if task.status == TaskStatus.EXEC:
        transition(task, TaskEvent.INTERRUPT_EXECUTION)
        transition(task, TaskEvent.ROUTE_TO_EXECUTION)
        return True
    return False


def _plan_current_child_is_terminal(task: Task, tree: Sequence[Task]) -> bool:
    if not task.plan or not is_paused_for(task, PAUSE_PLAN):
        return False
    cursor = int(task.plan.get("cursor", 0) or 0)
    for child in tree:
        if child.parent_id != task.id:
            continue
        data = child.data if isinstance(child.data, dict) else {}
        try:
            step = int(data.get("plan_step", -1))
        except (TypeError, ValueError):
            step = -1
        if step != cursor:
            continue
        return child.status in _TERMINAL_STATUSES
    return False


async def delete(task_id: UUID) -> bool:
    """Stop and soft-delete a task and its eligible subtree.

    Explicit deletion is authoritative even for an active Task. Every selected Task is first
    force-terminated so its scheduler lease and claimed attempt become durably unusable; only
    then is the same-agent subtree hidden in child-before-parent order.
    """
    db = get_db()
    task = await get_by_id(task_id)
    if not task:
        return False

    deletion_order, terminalized = await _prepare_tree_for_deletion(task, set())
    deleted_ids: list[UUID] = []
    for prepared in deletion_order:
        # Explicit deletion also releases stale retention markers. Live Goal cycles were
        # already closed under their normal locks by ``force_terminate`` above.
        for reason in retention_reasons(prepared):
            release_retention(prepared, reason)
        prepared.soft_delete()
        deleted_ids.append(prepared.id)
    await db.commit()

    # Resume external parents and coordination waits only after every selected Task is safely
    # hidden. Observer failures must not turn a completed deletion back into an HTTP failure.
    await _notify_force_terminated_deletions(terminalized)

    # LLM traces are accounting records: retain every row and every token/cost counter, but do
    # not leave their live status attached to a Task that is no longer in the active view.
    try:
        from app.llm import llm_call_service

        await llm_call_service.cancel_running_calls_for_tasks(deleted_ids)
    except Exception:
        # Deletion is already durable. The periodic reconciler observes Task.deleted_at and is
        # the crash-safe fallback if this immediate projection update cannot be committed.
        logger.exception(
            "Task deletion could not immediately reconcile running LLM calls task={}",
            task_id,
        )

    # Emit events in actual deletion order: children before parent.
    for deleted in deletion_order:
        await websocket.emit("task", "delete", {"id": str(deleted.id), "agent_id": deleted.agent_id}, None)

    return True


async def _prepare_tree_for_deletion(
    task: Task,
    seen: set[UUID],
) -> tuple[list[Task], list[Task]]:
    """Force-terminate and collect a subtree in child-before-parent deletion order.

    Agent boundaries preserve work delegated to another agent, so traversal does not enter a
    subtree owned by someone else. That child can still be deleted explicitly.
    """
    if task.id in seen:
        return [], []
    seen.add(task.id)

    was_active = task.status not in _TERMINAL_STATUSES
    needs_termination = (
        was_active
        or task.lease_token is not None
        or bool(retention_reasons(task))
    )
    prepared = task
    terminalized: list[Task] = []
    if needs_termination:
        refreshed = await force_terminate(
            task.id,
            None,
            notify_terminal=False,
        )
        if refreshed is None:
            return [], []
        prepared = refreshed
        if was_active:
            terminalized.append(prepared)

    deletion_order: list[Task] = []
    for child in await get_children(prepared.id):
        if child.agent_id != prepared.agent_id:
            continue  # Preserve a subtree owned by another agent.
        child_order, child_terminalized = await _prepare_tree_for_deletion(child, seen)
        deletion_order.extend(child_order)
        terminalized.extend(child_terminalized)

    deletion_order.append(prepared)
    return deletion_order, terminalized


async def _notify_force_terminated_deletions(tasks: Sequence[Task]) -> None:
    """Apply terminal coordination effects after deletion without weakening durability."""

    if not tasks:
        return
    from app.agent import handle_terminal_task
    from app.task.agent_adapter import as_agent_task

    for task in tasks:
        try:
            await handle_terminal_task(as_agent_task(task))
        except Exception:
            logger.exception(
                "Terminal observers failed after active Task deletion task={}",
                task.id,
            )


async def restore(
    task_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> Optional[Task]:
    """Restore a deleted task."""
    db = get_db()
    query = select(Task).where(Task.id == task_id)
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    result = await db.execute(query)
    task = result.scalar_one_or_none()

    if not task:
        return None

    task.restore()
    await db.commit()
    await db.refresh(task)

    # Emit a global WebSocket event.
    await websocket.emit("task", "restore", TaskSchema.model_validate(task).model_dump(mode="json"), None)

    return task


async def cleanup_all(
    *,
    agent_ids: Collection[int] | None = None,
) -> None:
    """Permanently delete processed tasks without touching active tasks."""
    db = get_db()
    query = (
        select(Task)
        .where(Task.status == TaskStatus.SUCCESS)
        .execution_options(include_historized=True)
    )
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    processed = list(
        (
            await db.scalars(query)
        ).all()
    )
    purge_ids = [task.id for task in processed if not retention_reasons(task)]
    if purge_ids:
        await db.execute(sa_delete(Task).where(Task.id.in_(purge_ids)))
    await db.commit()

    # Notify clients so they refresh their task list.
    await websocket.emit("task", "cleanup", {}, None)


def _apply_search(query: Select[Any], search: Optional[str]) -> Select[Any]:
    terms = [term.strip() for term in (search or "").split() if term.strip()]
    if not terms:
        return query

    query = query.outerjoin(Agent, Task.agent_id == Agent.id)
    for term in terms:
        pattern = f"%{term}%"
        query = query.where(
            or_(
                Task.label.ilike(pattern),
                Task.objective.ilike(pattern),
                Task.feedback.ilike(pattern),
                Task.message_platform.ilike(pattern),
                Task.message_group_id.ilike(pattern),
                cast(Task.requester_agent_id, String).ilike(pattern),
                cast(Task.status, String).ilike(pattern),
                cast(Task.data, String).ilike(pattern),
                cast(Task.dispatch_result, String).ilike(pattern),
                cast(Task.execution_result, String).ilike(pattern),
                cast(Task.messages, String).ilike(pattern),
                Agent.first_name.ilike(pattern),
                Agent.last_name.ilike(pattern),
                Agent.code.ilike(pattern),
                Agent.job_title.ilike(pattern),
            )
        )
    return query


def _apply_recent_date_range(
    query: Select[Any],
    date_from: Optional[date],
    date_to: Optional[date],
) -> Select[Any]:
    if date_from is not None:
        query = query.where(
            Task.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        exclusive_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        query = query.where(Task.created_at < exclusive_end)
    return query


def _apply_active_filter(
    query: Select[Any],
    active: bool | None,
) -> Select[Any]:
    if active is None:
        return query
    is_active = Task.status.not_in(_TERMINAL_STATUSES) & Task.paused.is_(False)
    return query.where(is_active if active else ~is_active)


def _apply_monitoring_state_filter(
    query: Select[Any],
    *,
    errors_only: bool,
    paused_only: bool,
) -> Select[Any]:
    if errors_only:
        query = query.where(Task.status == TaskStatus.ERROR)
    if paused_only:
        query = query.where(
            Task.status.not_in(_TERMINAL_STATUSES),
            Task.paused.is_(True),
        )
    return query


async def get_recent(
    skip: int = 0,
    limit: int = 15,
    agent_id: Optional[int] = None,
    goal_id: UUID | None = None,
    topic_id: UUID | None = None,
    search: Optional[str] = None,
    errors_only: bool = False,
    paused_only: bool = False,
    active: bool | None = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    agent_ids: Collection[int] | None = None,
) -> Sequence[Task]:
    """Return tasks from newest to oldest by creation date."""
    db = get_db()
    query = (
        select(Task)
        .order_by(Task.created_at.desc(), Task.id.desc())
    )
    if agent_id is not None:
        query = query.where(Task.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    if goal_id is not None:
        query = query.where(Task.goal_id == goal_id)
    if topic_id is not None:
        query = query.where(Task.topic_id == topic_id)
    query = _apply_monitoring_state_filter(
        query,
        errors_only=errors_only,
        paused_only=paused_only,
    )
    query = _apply_active_filter(query, active)
    query = _apply_search(query, search)
    query = _apply_recent_date_range(query, date_from, date_to)
    query = query.offset(skip).limit(limit)
    query = Task.histo_filter(query)
    result = await db.execute(query)
    return result.scalars().all()


async def count_recent(
    agent_id: Optional[int] = None,
    goal_id: UUID | None = None,
    topic_id: UUID | None = None,
    search: Optional[str] = None,
    errors_only: bool = False,
    paused_only: bool = False,
    active: bool | None = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    agent_ids: Collection[int] | None = None,
) -> int:
    """Count tasks matching the paginated monitoring projection."""
    query = select(func.count(Task.id))
    if agent_id is not None:
        query = query.where(Task.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    if goal_id is not None:
        query = query.where(Task.goal_id == goal_id)
    if topic_id is not None:
        query = query.where(Task.topic_id == topic_id)
    query = _apply_monitoring_state_filter(
        query,
        errors_only=errors_only,
        paused_only=paused_only,
    )
    query = _apply_active_filter(query, active)
    query = _apply_search(query, search)
    query = _apply_recent_date_range(query, date_from, date_to)
    query = Task.histo_filter(query)
    return int(await get_db().scalar(query) or 0)


async def summarize_recent(
    agent_id: Optional[int] = None,
    goal_id: UUID | None = None,
    topic_id: UUID | None = None,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    agent_ids: Collection[int] | None = None,
) -> tuple[int, TaskOverview]:
    """Return global status totals after applying the task-list filters."""
    db = get_db()
    non_terminal = Task.status.not_in(_TERMINAL_STATUSES)
    query = select(
        func.count(Task.id),
        func.count(Task.id).filter(non_terminal, Task.paused.is_(False)),
        func.count(Task.id).filter(Task.status == TaskStatus.SUCCESS),
        func.count(Task.id).filter(non_terminal, Task.paused.is_(True)),
        func.count(Task.id).filter(Task.status == TaskStatus.ERROR),
    )
    if agent_id is not None:
        query = query.where(Task.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(Task.agent_id.in_(agent_ids))
    if goal_id is not None:
        query = query.where(Task.goal_id == goal_id)
    if topic_id is not None:
        query = query.where(Task.topic_id == topic_id)
    query = _apply_search(query, search)
    query = _apply_recent_date_range(query, date_from, date_to)
    query = Task.histo_filter(query)
    result = await db.execute(query)
    total, running, completed, paused, errors = result.one()
    return int(total), TaskOverview(
        running=int(running),
        completed=int(completed),
        paused=int(paused),
        errors=int(errors),
    )
