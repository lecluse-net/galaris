"""A small recent page must not sort and read an entire task history."""

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.schema import DropIndex

from app.memory.tests.conftest import agents as agents
from app.task import task_service
from app.task.models import Task


@pytest.mark.asyncio
async def test_recent_task_page_preserves_order_and_bounds_history_reads(db, agents):
    owner, _ = agents
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    await db.execute(Task.__table__.insert(), [dict(id=uuid4(), label=f"Synthetic history {index}",
        agent_id=owner.id, status="SUCCESS", created_at=start + timedelta(seconds=index))
        for index in range(20000)])
    await db.execute(text("ANALYZE tasks"))
    connection = await db.connection()
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        captured.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        page = await task_service.get_recent(agent_id=owner.id, limit=50)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert len(page) == 50
    assert [item.created_at for item in page] == sorted([item.created_at for item in page], reverse=True)
    statement, parameters = captured[0]

    async def plan():
        result = await connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
        return result.scalar_one()[0]

    # DDL is confined to a savepoint in the ephemeral test database. Compare
    # exactly the same generated query and corpus, restoring all indexes afterward.
    savepoint = await db.begin_nested()
    try:
        for index in Task.__table__.indexes:
            if tuple(column.name for column in index.columns) in (("created_at", "id"), ("agent_id", "created_at", "id")):
                await db.execute(DropIndex(index))
        before = await plan()
    finally:
        await savepoint.rollback()
    after = await plan()
    before_blocks = before["Plan"].get("Shared Hit Blocks", 0) + before["Plan"].get("Shared Read Blocks", 0)
    after_blocks = after["Plan"].get("Shared Hit Blocks", 0) + after["Plan"].get("Shared Read Blocks", 0)
    print("SQL_PLAN task-page-20000 " + json.dumps({"before_blocks": before_blocks, "after_blocks": after_blocks,
        "before_ms": before["Execution Time"], "after_ms": after["Execution Time"]}))
    assert after_blocks < before_blocks / 4
