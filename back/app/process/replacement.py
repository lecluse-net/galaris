"""Process-owned evidence that a Task replacement could overlap external work."""

from uuid import UUID
from collections.abc import Sequence

from sqlalchemy import Select, or_, select

from .models import ProcessRun
from .process_service import TERMINAL_STATUSES
from core.database import get_db


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


async def coordinate_replacement(task_ids: Sequence[UUID]) -> None:
    """Ask only this owner's live runs to stop; uncertain effects remain blockers."""
    from .process_service import cancel_run, refresh_run
    rows = list(await get_db().scalars(select(ProcessRun.id).where(
        or_(ProcessRun.task_id.in_(task_ids), ProcessRun.await_task_id.in_(task_ids)),
        or_(ProcessRun.status.not_in(TERMINAL_STATUSES),
            ProcessRun.engine_metadata["remote_may_continue"].as_boolean().is_(True)),
    ).execution_options(include_historized=True)))
    await get_db().commit()
    failed = False
    for run_id in rows:
        try:
            run = await get_db().get(ProcessRun, run_id, populate_existing=True)
            if run is not None and run.status in TERMINAL_STATUSES:
                await refresh_run(run_id, confirm_terminal_stop=True)
            elif run is not None and run.status == "cancelling":
                await refresh_run(run_id)
            else:
                await cancel_run(run_id)
            await get_db().commit()
        except Exception:
            failed = True
            await get_db().rollback()
    if failed:
        raise RuntimeError("At least one process owner could not confirm replacement stop.")
