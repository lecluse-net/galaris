"""Task-owned read projections for other domains; no ORM object crosses the boundary."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from sqlalchemy import Select, any_, bindparam, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID

from core.database import get_db
from .amendment_service import amendment_basis
from .models import Task, TaskStatus
from .operational_state import operational_snapshot
from .working_set import parse_working_set


@dataclass(frozen=True, slots=True)
class TaskWorkSnapshot:
    task_id: UUID
    state: str
    created_at: datetime
    activity_at: datetime
    fields: Mapping[str, object]


async def list_work_snapshots(
    *,
    task_ids: Sequence[UUID] | Select[tuple[UUID]] = (),
    message_group_id: str = "",
    paused_since: datetime | None = None,
    terminal_since: datetime | None = None,
    terminal_limit: int = 0,
    active_agent_id: int | None = None,
) -> tuple[TaskWorkSnapshot, ...]:
    """Read explicitly linked work and work admitted directly in a canonical room.

    This internal projection does not grant access: the caller must already own
    the room scope. ``active_agent_id`` selects only that agent's unfinished work,
    including automatic waits of any age and excluding manual holds/cancellation.
    It deliberately excludes historized Tasks.
    """
    terminal = (TaskStatus.SUCCESS, TaskStatus.ERROR)
    if active_agent_id is not None:
        query = select(Task).where(
            Task.agent_id == active_agent_id,
            Task.status.in_((TaskStatus.CREATE, TaskStatus.DISPATCH, TaskStatus.PLAN, TaskStatus.EXEC)),
            Task.cancel_requested.is_(False),
        )
    else:
        linked = Task.id.in_(task_ids) if isinstance(task_ids, Select) else Task.id == any_(
            bindparam("linked_task_ids", list(task_ids), type_=ARRAY(PGUUID(as_uuid=True)))
        )
        scope = or_(linked, Task.message_group_id == message_group_id)
        eligible = Task.status.not_in(terminal)
        if terminal_limit > 0:
            activity = func.coalesce(Task.updated_at, Task.created_at)
            recent = select(Task.id).where(scope, Task.status.in_(terminal), Task.deleted_at.is_(None))
            if terminal_since is not None:
                recent = recent.where(activity > terminal_since)
            eligible = or_(eligible, Task.id.in_(
                recent.order_by(activity.desc(), Task.id.asc()).limit(terminal_limit).correlate(None)
            ))
        query = select(Task).where(scope, eligible)
    db = get_db()
    rows = (await db.scalars(Task.histo_filter(query.order_by(Task.created_at.desc(), Task.id.desc())))).all()
    if not rows:
        return ()
    parent_ids = bindparam("parent_ids", [row.id for row in rows], type_=ARRAY(PGUUID(as_uuid=True)))
    children = await db.scalars(Task.histo_filter(select(Task).where(
        Task.parent_id == any_(parent_ids), Task.status.not_in(terminal),
    ).order_by(Task.created_at.asc(), Task.id.asc())))
    by_parent: dict[UUID, list[Task]] = {}
    for child in children:
        if child.parent_id is not None:
            by_parent.setdefault(child.parent_id, []).append(child)
    snapshots: list[TaskWorkSnapshot] = []
    for task in rows:
        operational = operational_snapshot(task, by_parent.get(task.id, ()))
        state = operational["operational_state"]
        if active_agent_id is not None and (state == "PAUSED" or "user" in operational["pause_reasons"]):
            continue
        activity_at = task.updated_at or task.created_at
        activity_at = (
            activity_at.replace(tzinfo=timezone.utc)
            if activity_at.tzinfo is None
            else activity_at.astimezone(timezone.utc)
        )
        # Apply the caller's context window before interpreting historical results
        # or working sets. Old work must not poison an otherwise current context.
        if state == "PAUSED" and paused_since is not None and activity_at < paused_since:
            continue
        snapshots.append(
            TaskWorkSnapshot(
                task_id=task.id,
                state=state,
                created_at=task.created_at,
                activity_at=activity_at,
                fields={
                    "task_id": str(task.id),
                    "resource_uri": f"galaris://task/{task.id}",
                    "label": task.label,
                    "status": task.status.value,
                    "paused": task.paused,
                    "cancel_requested": task.cancel_requested,
                    "revision": task.revision,
                    "amendment_basis": amendment_basis(task),
                    "objective": str(task.objective or ""),
                    "result_available": task.get_execution_result() is not None,
                    "working_set": [
                        entry.model_dump(mode="json")
                        for entry in parse_working_set(task).active()[:25]
                    ],
                    **cast(Mapping[str, object], operational),
                },
            )
        )
    return tuple(snapshots)
