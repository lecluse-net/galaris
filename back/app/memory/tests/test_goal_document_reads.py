"""Current Goal documents remain fresh while their metadata is read in bulk."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, update

from app.memory import service
from app.memory.goal_document_adapter import MemoryGoalDocumentStore
from app.memory.models import MemoryItem
from app.memory.storage import get_storage
from app.memory.contracts import ResourceNotFoundError


@pytest.mark.asyncio
async def test_goal_documents_bulk_read_reopens_current_content(db, agents, memory_storage):
    store = MemoryGoalDocumentStore()
    ids = tuple([
        await store.create(goal_id=uuid4(), owner_agent_id=agents[0].id,
                           kind="description", goal_title=f"Synthetic {index}",
                           content=f"<p>Content {index}</p>")
        for index in range(6)
    ])
    statements = []
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert await store.read_many(()) == {}
        assert statements == []
        contents = await store.read_many((*ids, ids[0]))
        assert contents == {identity: f"<p>Content {index}</p>" for index, identity in enumerate(ids)}
        assert len(statements) <= 1
    finally:
        event.remove(engine, "before_cursor_execute", count)
    await store.update(ids[0], content="<p>Updated content</p>")
    assert (await store.read_many(ids))[ids[0]] == "<p>Updated content</p>"
    assert await store.read(ids[0]) == "<p>Updated content</p>"
    await db.execute(update(MemoryItem).where(MemoryItem.id == ids[0]).values(deleted_at=datetime.now(timezone.utc)))
    await db.commit()
    with pytest.raises(service.MemoryNotFoundError):
        await store.read_many(ids)


@pytest.mark.asyncio
async def test_goal_document_reads_preserve_missing_and_invalid_content_errors(db, agents, memory_storage):
    store = MemoryGoalDocumentStore()
    with pytest.raises(service.MemoryNotFoundError):
        await store.read_many((uuid4(),))
    identity = await store.create(goal_id=uuid4(), owner_agent_id=agents[0].id,
                                  kind="tracking", goal_title="Synthetic errors", content="<p>Valid</p>")
    item = await db.get(MemoryItem, identity)
    storage = get_storage(item.provider_code)
    await db.execute(update(MemoryItem).where(MemoryItem.id == identity).values(node_kind="memory"))
    with pytest.raises(service.MemoryConflictError, match="not a document"):
        await store.read_many((identity,))
    await db.execute(update(MemoryItem).where(MemoryItem.id == identity).values(node_kind="document"))
    await storage.update(item.resource_id, b'\xff')
    with pytest.raises(UnicodeDecodeError):
        await store.read_many((identity,))
    await storage.delete(item.resource_id)
    with pytest.raises(ResourceNotFoundError):
        await store.read_many((identity,))
