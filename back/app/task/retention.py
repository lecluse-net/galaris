"""Public causal scope whose execution evidence may still be consumed."""

from uuid import UUID

from sqlalchemy import Select, or_, select
from .models import Task, TaskStatus


def protected_task_ids() -> Select[tuple[UUID]]:
    """Include active tasks and their whole parent/source component, cycle safely."""
    live = (
        select(Task.id, Task.parent_id, Task.source_task_id)
        .where(
            Task.deleted_at.is_(None),
            Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR)),
        )
        .cte(recursive=True)
    )
    live = live.union(
        select(Task.id, Task.parent_id, Task.source_task_id).join(
            live,
            or_(
                Task.id == live.c.parent_id,
                Task.id == live.c.source_task_id,
                Task.parent_id == live.c.id,
                Task.source_task_id == live.c.id,
            ),
        )
    )
    return select(live.c.id)
