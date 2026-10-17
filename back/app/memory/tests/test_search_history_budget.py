from app.share import ShareGrant
from app.memory.models import MemoryItem
"""Shared search results must not hydrate their revision corpus or query per hit."""

import pytest

from app.memory import document_service, service
from app.memory.models import MemoryRevision
from app.memory.schemas import MemorySearchRequest
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_shared_document_search_bounds_permissions_and_does_not_load_history(db, agents, memory_storage):
    owner, reader = agents
    documents = [await document_service.create_document(owner_agent_id=owner.id,
        title=f"Synthetic searchable corpus {index}", content="<p>Synthetic searchable evidence.</p>", task_id=None)
        for index in range(12)]
    db.add_all([ShareGrant(share_id=MemoryItem.share_for(item.id), agent_id=reader.id, can_write=index % 2 == 0)
                for index, item in enumerate(documents)])
    await db.flush()
    await db.execute(MemoryRevision.__table__.insert(), [{
        "item_id": item.id, "revision": number, "provider_code": "native", "resource_id": "synthetic-revision",
        "content_hash": str(number), "content_type": "text", "media_type": "text/html", "title": item.title,
    } for item in documents for number in range(2, 52)])
    expected = {item.id for item in documents}
    writable = {item.id for index, item in enumerate(documents) if index % 2 == 0}
    reader_id = reader.id
    db.expunge_all()
    async with measured_reads(db, "shared-memory-search-12-with-600-revisions") as reads:
        page = await service.search_items(MemorySearchRequest(agent_id=reader_id, query="searchable", limit=50))
    assert {hit.item.id for hit in page.hits} == expected
    assert {hit.item.id for hit in page.hits if hit.item.access.can_write} == writable
    assert len(reads) <= 12
    assert not any(MemoryRevision.__tablename__ in statement for statement in reads)
    assert not any(isinstance(item, MemoryRevision) for item in db.identity_map.values())
