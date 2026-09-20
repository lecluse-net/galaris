"""Process-owned evidence that a Task replacement could overlap external work."""

from uuid import UUID

from sqlalchemy import Select, or_, select

from .models import ProcessRun
from .process_service import TERMINAL_STATUSES


def replacement_blocked_task_ids() -> Select[tuple[UUID]]:
    """Logical cancellation with a possibly live remote effect is still coordination."""
    runs = select(ProcessRun.task_id, ProcessRun.await_task_id).where(or_(
        ProcessRun.status.not_in(TERMINAL_STATUSES),
        ProcessRun.engine_metadata["remote_may_continue"].as_boolean().is_(True),
    )).subquery()
    owners = select(runs.c.task_id.label("id")).where(runs.c.task_id.is_not(None)).union(
        select(runs.c.await_task_id.label("id")).where(runs.c.await_task_id.is_not(None)),
    ).subquery()
    return select(owners.c.id)
