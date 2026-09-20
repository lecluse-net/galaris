from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.task import task_service
from app.task.models import Task, TaskStatus


def _task(
    label: str,
    status: TaskStatus,
    *,
    paused: bool = False,
    updated_at: datetime,
) -> Task:
    return Task(
        id=uuid4(),
        label=label,
        status=status,
        paused=paused,
        ai=True,
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_get_active_returns_only_executing_unpaused_tasks(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    older = _task("older", TaskStatus.DISPATCH, updated_at=now - timedelta(minutes=2))
    newer = _task("newer", TaskStatus.EXEC, updated_at=now)
    db.add_all([
        older,
        newer,
        _task("waiting", TaskStatus.PLAN, paused=True, updated_at=now),
        _task("created", TaskStatus.CREATE, updated_at=now),
        _task("done", TaskStatus.SUCCESS, updated_at=now),
    ])
    await db.commit()

    tasks = await task_service.get_active(limit=10)

    assert [task.id for task in tasks] == [newer.id, older.id]
