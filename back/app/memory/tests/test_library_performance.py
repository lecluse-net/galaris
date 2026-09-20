"""Library-page query and memory budgets across a growing revision corpus."""

import gc
import hashlib
import json
from pathlib import Path
import time
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, literal, select, text

from app.memory import service
from app.memory.models import MemoryItem, MemoryRevision
from app.memory.schemas import DocumentLibraryRequest
from app.memory.storage import get_storage


@pytest.mark.asyncio
async def test_library_page_cost_does_not_materialize_the_revision_corpus(db, agents, memory_storage):
    owner, peer = agents
    owner_id, peer_id = owner.id, peer.id
    resource = await get_storage("native").create(b"library benchmark")
    measurements = []
    revisions_per_document = 100
    for start, stop in ((0, 100), (100, 1000)):
        rows = [{"id": uuid4(), "owner_agent_id": owner_id if index % 2 == 0 else peer_id,
                 "resource_id": resource, "title": f"Document {index:04d}", "memory_type": "working",
                 "node_kind": "document", "search_text": "body " * 4000,
                 "keywords": ["visible" if index % 2 == 0 else "private"],
                 "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
                 "visibility": "private", "global_access": 0} for index in range(start, stop)]
        await db.execute(insert(MemoryItem), rows)
        series = func.generate_series(1, revisions_per_document).table_valued("number").render_derived()
        columns = ["id", "item_id", "revision", "provider_code", "resource_id", "content_hash", "content_type", "media_type", "title"]
        expressions = [func.gen_random_uuid(), MemoryItem.id, series.c.number,
                      MemoryItem.provider_code, MemoryItem.resource_id, MemoryItem.content_hash,
                      MemoryItem.content_type, MemoryItem.media_type, MemoryItem.title]
        await db.execute(MemoryRevision.__table__.insert().from_select(columns,
            select(*expressions).select_from(MemoryItem.__table__.join(series, literal(True))).where(MemoryItem.id.in_([row["id"] for row in rows]))))
        await db.commit()
        db.expunge_all()
        gc.collect()
        connection = await db.connection()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            page = await service.browse_document_library(DocumentLibraryRequest(limit=50), managed_agent_ids={owner_id})
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            elapsed = time.perf_counter() - started
            tracemalloc.stop()
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
        assert page.total == stop // 2 and len(page.entries) == 50
        assert page.keywords == ["visible"]
        assert all(entry.item.owner_agent_id == owner_id for entry in page.entries)
        assert len(statements) <= 5, "Page, count, grants and facets must stay batched"
        assert not any("memory_revisions" in statement for statement in statements)
        assert not any(isinstance(value, MemoryRevision) for value in db.identity_map.values())
        assert peak < 16 * 1024 * 1024, "A library page must not allocate its corpus history"
        assert elapsed < 5
        measurements.append({"documents": stop, "revisions": stop * revisions_per_document,
                             "page_size": 50, "queries": len(statements), "python_peak_bytes": peak,
                             "seconds": elapsed, "loaded_revisions": 0})
    assert measurements[0]["queries"] == measurements[1]["queries"]
    assert measurements[1]["python_peak_bytes"] <= measurements[0]["python_peak_bytes"] + 2 * 1024 * 1024
    assert await db.scalar(select(func.count()).select_from(MemoryRevision)) == 100000
    table_bytes = await db.scalar(text("SELECT pg_total_relation_size('memory_revisions')"))
    destination = Path(__file__).resolve().parents[4] / "artifacts/memory-library-benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"measurements": measurements, "revision_table_bytes": table_bytes,
        "memory_scope": "Peak Python allocations during one page, not total process RSS or database memory."}, indent=2) + "\n")
