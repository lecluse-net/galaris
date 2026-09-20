"""Public, bounded observations for post-terminal Task analysis."""

from __future__ import annotations

from datetime import datetime

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_db

from .conversation import ConversationFollowup, get_conversation_followup
from .models import Task, TaskAttempt


class TaskAttemptObservation(BaseModel):
    reference: str
    attempt_number: int = Field(ge=1)
    phase: str
    status: str
    retryable: bool = False
    error: str = ""
    duration_seconds: float | None = Field(default=None, ge=0.0)


class TaskToolObservation(BaseModel):
    reference: str
    name: str
    success: bool
    result: str = ""
    duration_seconds: float = Field(default=0.0, ge=0.0)


class TaskChildObservation(BaseModel):
    reference: str
    task_id: UUID
    label: str
    status: str
    result: str = ""
    error: str = ""


class TaskOutcomeObservation(BaseModel):
    task_id: UUID
    owner_agent_id: int | None
    label: str
    objective: str = ""
    status: str
    result: str = ""
    error: str = ""
    effort: str
    driver_code: str = ""
    model_code: str = ""
    route: str = ""
    created_at: datetime
    task_data: dict[str, object] = Field(default_factory=dict)
    attempts: list[TaskAttemptObservation] = Field(
        default_factory=lambda: list[TaskAttemptObservation]()
    )
    tools: list[TaskToolObservation] = Field(
        default_factory=lambda: list[TaskToolObservation]()
    )
    children: list[TaskChildObservation] = Field(
        default_factory=lambda: list[TaskChildObservation]()
    )
    followup: ConversationFollowup | None = None


def _duration(attempt: TaskAttempt) -> float | None:
    if attempt.finished_at is None:
        return None
    return max(0.0, (attempt.finished_at - attempt.started_at).total_seconds())


async def get_task_outcome_observation(task_id: UUID) -> TaskOutcomeObservation | None:
    """Return only observable Task data; prompts and private reasoning are excluded."""

    task = await get_db().scalar(
        select(Task)
        .options(selectinload(Task.attempts), selectinload(Task.children))
        .where(Task.id == task_id)
    )
    if task is None:
        return None
    execution = task.get_execution_result()
    dispatch = task.get_dispatch_result()
    tools: list[TaskToolObservation] = []
    if execution is not None:
        for index, message in enumerate(execution.messages):
            name = str(message.tool_name or "").strip()
            if message.type != "tool" or not name or name in {
                "approval",
                "budget_guard",
                "load_capability",
                "messenger_reply",
                "thinking",
                "reply",
                "final_result",
            }:
                continue
            tools.append(
                TaskToolObservation(
                    reference=f"tool:{index}:{name}",
                    name=name,
                    success=message.success,
                    result=message.content,
                    duration_seconds=max(0.0, message.execution_time),
                )
            )
    attempts = [
        TaskAttemptObservation(
            reference=f"attempt:{attempt.id}",
            attempt_number=attempt.attempt_number,
            phase=attempt.phase,
            status=attempt.status,
            retryable=attempt.retryable,
            error=attempt.error or "",
            duration_seconds=_duration(attempt),
        )
        for attempt in sorted(task.attempts, key=lambda item: item.attempt_number)
    ]
    children: list[TaskChildObservation] = []
    for child in sorted(task.children, key=lambda item: (item.created_at, item.id)):
        child_execution = child.get_execution_result()
        children.append(
            TaskChildObservation(
                reference=f"galaris://task/{child.id}",
                task_id=child.id,
                label=child.label,
                status=child.status.value,
                result=child_execution.result if child_execution is not None else "",
                error=child.last_error or "",
            )
        )
    route = dispatch.decision.route if dispatch is not None else ""
    driver_code = dispatch.driver_code if dispatch is not None else ""
    model_code = (
        str(execution.metadata.get("model_code") or "")
        if execution is not None
        else ""
    )
    data = task.data if isinstance(task.data, dict) else {}
    allowed_data: dict[str, object] = {
        key: value
        for key, value in data.items()
        if key in {"action_guard_retried", "language", "plan_step"}
        and isinstance(value, (str, int, float, bool))
    }
    return TaskOutcomeObservation(
        task_id=task.id,
        owner_agent_id=task.agent_id,
        label=task.label,
        objective=task.objective or "",
        status=task.status.value,
        result=execution.result if execution is not None else "",
        error=task.last_error or "",
        effort=task.effort,
        driver_code=driver_code,
        model_code=model_code,
        route=str(route),
        created_at=task.created_at,
        task_data=allowed_data,
        attempts=attempts,
        tools=tools,
        children=children,
        followup=await get_conversation_followup(task),
    )


__all__ = [
    "TaskAttemptObservation",
    "TaskChildObservation",
    "TaskOutcomeObservation",
    "TaskToolObservation",
    "get_task_outcome_observation",
]
