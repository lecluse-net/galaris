from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.task.activity import has_active_task_work
from app.task.models import Task, TaskStatus


@pytest.mark.asyncio
async def test_deleted_task_does_not_block_background_work(
    db: AsyncSession,
) -> None:
    task = Task(
        label="Deleted active task",
        objective="Must not block opportunistic background work.",
        status=TaskStatus.CREATE,
        deleted_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.commit()

    assert await has_active_task_work() is False

    task.deleted_at = None
    await db.commit()

    assert await has_active_task_work() is True
