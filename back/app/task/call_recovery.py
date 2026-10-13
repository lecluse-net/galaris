"""Run-scoped manual model interruption, delivered by the durable lease owner."""
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.agent import request_call_recovery
from core.database import get_db
from core.i18n import tr
from .models import Task, TaskAttempt, TaskStatus


class TaskCallRecoveryCommand(BaseModel):
    run_id: UUID
    request_id: UUID
    expected_control_version: int = Field(ge=0)


class TaskCallRecoveryState(BaseModel):
    run_id: UUID
    request_id: UUID
    version: int
    state: Literal["requested", "accepted", "refused"]


def _identity(task: Task) -> Mapping[str, object]:
    raw = (task.data or {}).get("_agent_run_identity")
    return cast(Mapping[str, object], raw) if isinstance(raw, Mapping) else {}


def supports_call_recovery(task: Task) -> bool:
    identity = _identity(task)
    return bool(
        task.status == TaskStatus.EXEC and task.lease_token is not None
        and task.lease_expires_at is not None and task.lease_expires_at > datetime.now(timezone.utc)
        and not task.paused and not task.cancel_requested and task.deleted_at is None
        and isinstance(identity.get("driver_code"), str) and identity.get("driver_code")
        and identity.get("call_recovery") is True and identity.get("local_interrupt") is True
        and identity.get("request_run_id")
    )


def recovery_state(task: Task, attempt: TaskAttempt | None) -> TaskCallRecoveryState | None:
    raw = (attempt.data or {}).get("call_recovery") if attempt else None
    run_id = _identity(task).get("request_run_id")
    if not isinstance(raw, Mapping) or cast(Mapping[str, object], raw).get("run_id") != run_id:
        return None
    try:
        return TaskCallRecoveryState.model_validate(raw)
    except ValidationError:
        return None


async def request_recovery(task_id: UUID, command: TaskCallRecoveryCommand) -> TaskCallRecoveryState:
    from .task_service import TaskConflictError

    db = get_db()
    task = await db.scalar(select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True))
    if task is None or not supports_call_recovery(task):
        raise TaskConflictError(await tr("task_api.errors.call_recovery_unavailable"))
    run_id = _identity(task).get("request_run_id")
    if str(command.run_id) != run_id:
        raise TaskConflictError(await tr("task_api.errors.call_recovery_stale"))
    attempt = await db.scalar(select(TaskAttempt).where(
        TaskAttempt.task_id == task.id, TaskAttempt.lease_token == task.lease_token,
        TaskAttempt.finished_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True))
    if attempt is None:
        raise TaskConflictError(await tr("task_api.errors.call_recovery_unavailable"))
    current = recovery_state(task, attempt)
    if current and current.request_id == command.request_id:
        return current
    if command.expected_control_version != (current.version if current else 0) or current and current.state == "requested":
        raise TaskConflictError(await tr("task_api.errors.call_recovery_stale"))
    state = TaskCallRecoveryState(run_id=command.run_id, request_id=command.request_id,
        version=command.expected_control_version + 1, state="requested")
    attempt.data = {**(attempt.data or {}), "call_recovery": state.model_dump(mode="json")}
    # HTTP request sessions close without an implicit commit. The lease owner
    # must observe this command from its own connection before we acknowledge it.
    await db.commit()
    return state


async def deliver_recovery(task_id: UUID, lease_token: UUID) -> None:
    """Only the current owner delivers a command; old runs and duplicate polls do nothing."""
    db = get_db()
    pending = await db.scalar(select(TaskAttempt.id).where(
        TaskAttempt.task_id == task_id, TaskAttempt.lease_token == lease_token,
        TaskAttempt.finished_at.is_(None),
        TaskAttempt.data["call_recovery"]["state"].as_string() == "requested",
    ))
    if pending is None:
        return
    task = await db.scalar(select(Task).where(
        Task.id == task_id, Task.lease_token == lease_token,
    ).with_for_update().execution_options(populate_existing=True))
    if task is None or not supports_call_recovery(task):
        return
    attempt = await db.scalar(select(TaskAttempt).where(
        TaskAttempt.task_id == task_id, TaskAttempt.lease_token == lease_token,
        TaskAttempt.finished_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True))
    state = recovery_state(task, attempt)
    if attempt is None or state is None or state.state != "requested":
        return
    driver_code = _identity(task).get("driver_code")
    if not isinstance(driver_code, str):
        return
    accepted = await request_call_recovery(driver_code, state.run_id)
    state.state = "accepted" if accepted else "refused"
    attempt.data = {**(attempt.data or {}), "call_recovery": state.model_dump(mode="json")}
    await db.flush()
