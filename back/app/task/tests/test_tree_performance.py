"""Human tree controls preserve every node with bounded database reads."""

from unittest.mock import AsyncMock

import pytest

from app.task import task_service
from app.task.models import Task, TaskStatus
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_tree_pause_and_resume_keep_other_pause_reasons_with_bounded_reads(db, monkeypatch):
    root = Task(label="Synthetic root", status=TaskStatus.PLAN)
    db.add(root)
    await db.flush()
    nodes = [Task(label=f"Synthetic child {index}", parent_id=root.id, status=TaskStatus.DISPATCH,
                  paused=True, data={"pause_reasons": [task_service.PAUSE_AWAIT]}) for index in range(40)]
    db.add_all(nodes)
    await db.flush()
    terminal = Task(label="Synthetic completed child", parent_id=nodes[0].id, status=TaskStatus.SUCCESS)
    db.add(terminal)
    await db.flush()
    root_id, terminal_id = root.id, terminal.id
    identities = {item.id for item in nodes} | {root_id}
    db.expunge_all()
    monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
    async with measured_reads(db, "task-tree-pause-42") as reads:
        await task_service.pause_tree(root_id)
    assert len(reads) <= 5
    for identity in identities:
        item = await db.get(Task, identity)
        assert item.paused and task_service.PAUSE_USER in task_service.pause_reasons(item)
    assert not (await db.get(Task, terminal_id)).paused
    async with measured_reads(db, "task-tree-resume-42") as reads:
        await task_service.resume_tree(root_id)
    assert len(reads) <= 5
    for identity in identities - {root_id}:
        item = await db.get(Task, identity)
        assert item.paused and task_service.pause_reasons(item) == [task_service.PAUSE_AWAIT]
    assert not (await db.get(Task, root_id)).paused
