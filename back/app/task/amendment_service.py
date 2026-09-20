"""Durable, idempotent amendments to an existing root Task."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.database import get_db

from .models import Task, TaskAmendment, TaskStatus
from .operational_state import operational_snapshot
from .task_service import TaskEditConflict, TaskRevisionConflict
from .workflow import TaskEvent, transition


_MAX_INSTRUCTION_CHARS = 8_000
_MAX_REASON_CHARS = 1_000
_AMENDMENT_HEADING = "Additional instructions received after this Task was created:"
_AMEND_DISPOSITIONS = {"AMEND_CURRENT", "AMEND_QUEUED"}


def amendment_basis(task: Task) -> str:
    """Fingerprint the work definition, excluding runtime progress and resources."""

    definition = {
        "task_id": str(task.id),
        "objective": task.objective,
        "agent_id": task.agent_id,
        "parent_id": str(task.parent_id),
        "requester_user_id": task.requester_user_id,
        "connection_id": task.messenger_connection_id,
        "room_id": task.message_group_id,
        "plan": task.plan,
        "forced_route": task.forced_route,
        "forced_effort": task.forced_effort,
        "reasoning_effort_override": task.reasoning_effort_override,
        "auto_approve": task.auto_approve,
        "terminal_status": task.status.value if task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR} else None,
        "amendment_count": (task.data or {}).get("amendment_count", 0),
    }
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class TaskAmendmentResult:
    task: Task
    amendment: TaskAmendment
    created: bool
    interrupted: bool


def _merge_instruction(objective: str | None, instruction: str) -> str:
    current = str(objective or "").rstrip()
    if _AMENDMENT_HEADING in current:
        return f"{current}\n- {instruction}"
    if not current:
        return instruction
    return f"{current}\n\n{_AMENDMENT_HEADING}\n- {instruction}"


async def _existing_amendment(
    idempotency_key: str, *, task_id: UUID
) -> TaskAmendmentResult | None:
    db = get_db()
    existing = await db.scalar(
        select(TaskAmendment).where(
            TaskAmendment.idempotency_key == idempotency_key
        )
    )
    if existing is None:
        return None
    if existing.task_id != task_id:
        raise TaskEditConflict("The amendment idempotency key belongs to another Task.")
    existing_task = await db.scalar(
        Task.histo_filter(select(Task).where(Task.id == existing.task_id))
    )
    if existing_task is None:
        raise RuntimeError("The Task associated with this amendment no longer exists.")
    return TaskAmendmentResult(
        task=existing_task,
        amendment=existing,
        created=False,
        interrupted=False,
    )


async def amend_task(
    *,
    task_id: UUID,
    expected_revision: int,
    instruction: str,
    disposition: str,
    reason: str | None,
    source_kind: str,
    source_id: str,
    idempotency_key: str,
    expected_basis: str | None = None,
    normalize_disposition: bool = False,
) -> TaskAmendmentResult:
    """Merge an instruction and safely route the same Task through a fresh decision."""

    clean_instruction = instruction.strip()
    if disposition not in _AMEND_DISPOSITIONS:
        raise ValueError(f"Unsupported Task amendment disposition: {disposition}")
    if expected_revision < 1:
        raise ValueError("expected_revision must be positive.")
    if not source_kind.strip() or not source_id.strip():
        raise ValueError("An amendment source kind and identifier are required.")
    if not idempotency_key or len(idempotency_key) > 64:
        raise ValueError("The amendment idempotency key must contain 1 to 64 characters.")
    if not clean_instruction:
        raise ValueError("The amendment instruction cannot be empty.")
    if len(clean_instruction) > _MAX_INSTRUCTION_CHARS:
        raise ValueError(
            f"The amendment instruction cannot exceed {_MAX_INSTRUCTION_CHARS} characters."
        )
    clean_reason = str(reason or "").strip()[:_MAX_REASON_CHARS] or None
    db = get_db()
    existing = await _existing_amendment(idempotency_key, task_id=task_id)
    if existing is not None:
        return existing

    task = await db.scalar(
        Task.histo_filter(select(Task).where(Task.id == task_id).with_for_update()
                          .execution_options(populate_existing=True))
    )
    if task is None:
        raise ValueError("Task not found.")

    # The Task row serializes amendments for one root. Re-read the globally unique action key
    # after acquiring it so two concurrent retries cannot both append the same instruction.
    existing = await _existing_amendment(idempotency_key, task_id=task_id)
    if existing is not None:
        return existing
    if task.revision != expected_revision and not (
        expected_revision < task.revision
        and expected_basis is not None
        and expected_basis == amendment_basis(task)
    ):
        raise TaskRevisionConflict(
            f"Task revision conflict: expected {expected_revision}, current {task.revision}."
        )
    children = list(
        (
            await db.scalars(
                Task.histo_filter(
                    select(Task)
                    .where(Task.parent_id == task.id)
                    .order_by(Task.created_at.asc(), Task.id.asc())
                )
            )
        ).all()
    )
    snapshot = operational_snapshot(task, children)
    if not snapshot["amendable"]:
        raise TaskEditConflict(snapshot["amend_blocker"] or "Task cannot be amended.")
    if normalize_disposition:
        disposition = "AMEND_QUEUED" if snapshot["operational_state"] == "QUEUED" else "AMEND_CURRENT"
    if disposition == "AMEND_QUEUED" and snapshot["operational_state"] != "QUEUED":
        raise TaskEditConflict("AMEND_QUEUED requires a queued Task.")
    if disposition == "AMEND_CURRENT" and snapshot["operational_state"] == "QUEUED":
        raise TaskEditConflict("Use AMEND_QUEUED for a queued Task.")

    from . import scheduler, task_service

    interrupted = False
    if task.lease_token is not None:
        interrupted = scheduler.cancel(task.id)
        if not interrupted:
            task.cancel_requested = True
    if task.status == TaskStatus.EXEC:
        transition(task, TaskEvent.INTERRUPT_EXECUTION)

    task.objective = _merge_instruction(task.objective, clean_instruction)
    task.dispatch_result = None
    task.briefing_result = None
    # The previous visible trace belongs to the superseded objective. The durable driver
    # checkpoint remains available for effect-safe replay, but the revised run must publish
    # a fresh result before the Task can become terminal again.
    task.execution_result = None
    task.feedback = None
    task.last_error = None
    data: dict[str, Any] = task.data.copy() if task.data is not None else {}
    data["amendment_count"] = int(data.get("amendment_count", 0) or 0) + 1
    data["last_amended_at"] = datetime.now(timezone.utc).isoformat()
    task.data = data

    # An internal wait keeps its resume point and correlation. Every other non-planned task
    # returns to CREATE so the dispatcher sees the revised objective.
    internal_wait = bool(snapshot["waits"]) or any(
        task_service.is_paused_for(task, pause_reason)
        for pause_reason in (
            task_service.PAUSE_AWAIT,
            task_service.PAUSE_CHILD,
            task_service.PAUSE_CLARIFY,
            task_service.PAUSE_PLAN,
        )
    )
    if not internal_wait and task.status != TaskStatus.CREATE:
        transition(task, TaskEvent.REVISE)

    amendment = TaskAmendment(
        task_id=task.id,
        source_kind=source_kind[:40],
        source_id=source_id[:200],
        idempotency_key=idempotency_key,
        disposition=disposition[:30],
        instruction=clean_instruction,
        reason=clean_reason,
    )
    db.add(amendment)
    saved = await task_service.save(task)
    await db.refresh(amendment)
    if not saved.paused:
        scheduler.wake(saved.id)
    return TaskAmendmentResult(
        task=saved,
        amendment=amendment,
        created=True,
        interrupted=interrupted,
    )


__all__ = ["TaskAmendmentResult", "amend_task"]
