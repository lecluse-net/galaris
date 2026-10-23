"""Current Goal documents remain fresh while their metadata is read in bulk."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, update

from app.document import resource_service as service
from app.document.goal_document_adapter import DocumentGoalDocumentStore
from app.document import Document
from app.document import Document
from core.storage import get_storage
from app.memory.contracts import ResourceNotFoundError


@pytest.mark.asyncio
async def test_goal_documents_bulk_read_reopens_current_content(db, agents, memory_storage):
    store = DocumentGoalDocumentStore()
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
    await db.execute(update(Document).where(Document.id == ids[0]).values(deleted_at=datetime.now(timezone.utc)))
    await db.commit()
    with pytest.raises(service.DocumentNotFoundError):
        await store.read_many(ids)


@pytest.mark.asyncio
async def test_goal_document_reads_preserve_missing_and_invalid_content_errors(db, agents, memory_storage):
    store = DocumentGoalDocumentStore()
    with pytest.raises(service.DocumentNotFoundError):
        await store.read_many((uuid4(),))
    identity = await store.create(goal_id=uuid4(), owner_agent_id=agents[0].id,
                                  kind="tracking", goal_title="Synthetic errors", content="<p>Valid</p>")
    item = await db.get(Document, identity)
    storage = get_storage(item.provider_code)
    from app.memory import service as memories
    from app.memory.schemas import MemoryItemCreate, MemoryPayload
    memory, _ = await memories.create_item(MemoryItemCreate(owner_agent_id=agents[0].id,
        payload=MemoryPayload(text="<p>A private memory is not a Goal document.</p>")))
    with pytest.raises(service.DocumentNotFoundError):
        await store.read_many((memory.id,))
    # SQL TEXT cannot contain invalid UTF-8. Preserve the error contract for an
    # unconverted historical resource by exercising the retained file fallback.
    invalid_ref = await storage.create(b'\xff')
    await db.execute(update(Document).where(Document.id == identity).values(content=None, resource_id=invalid_ref))
    with pytest.raises(UnicodeDecodeError):
        await store.read_many((identity,))
    await storage.delete(invalid_ref)
    with pytest.raises(ResourceNotFoundError):
        await store.read_many((identity,))
