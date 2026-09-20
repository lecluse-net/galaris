"""A reproducible multilingual corpus; query plans are evidence, not index prescriptions."""

import hashlib
import json
from pathlib import Path
import time

import pytest
from sqlalchemy import event, insert, text

from app.memory.models import MemoryItem
from app.memory.schemas import MemorySearchRequest
from app.memory.service import search_items
from app.memory.storage import get_storage


@pytest.mark.asyncio
async def test_multilingual_search_has_bounded_queries_and_preserves_private_scope(db, agents, memory_storage):
    owner, peer = agents
    languages = ["contrat voyage budget", "travel contract budget", "旅行 合同 预算"]
    resources = [await get_storage("native").create((language + " ").encode() * 25)
                 for language in languages]
    rows = [{
        "owner_agent_id": owner.id if index % 2 == 0 else peer.id,
        "resource_id": resources[index % 3],
        "title": f"{languages[index % 3]} {index}",
        "search_text": (languages[index % 3] + " ") * 25,
        "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
        "visibility": "private",
        "global_access": 0,
    } for index in range(6000)]
    await db.execute(insert(MemoryItem), rows)
    await db.flush()
    await db.execute(text("ANALYZE memory_items"))
    connection = await db.connection()
    report = []
    for query in ("voyage", "travel", "预算"):
        statements = []

        def capture(_connection, _cursor, statement, parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement, parameters))

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        started = time.perf_counter()
        try:
            page = await search_items(MemorySearchRequest(agent_id=owner.id, query=query, limit=50))
        finally:
            elapsed = time.perf_counter() - started
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
        assert page.total == 1000
        assert len(page.hits) == 50
        assert all(hit.item.owner_agent_id == owner.id for hit in page.hits)
        assert len(statements) <= 12, "Search must batch projections instead of querying each result"
        plans = []
        for statement, parameters in statements:
            if "memory_items" in statement and "LIMIT" in statement:
                plans.append((await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
                )).scalar_one())
        report.append({"query": query, "seconds": elapsed, "query_count": len(statements), "plans": plans})
    size = await db.scalar(text("SELECT pg_total_relation_size('memory_items')"))
    destination = Path(__file__).resolve().parents[4] / "artifacts/memory-search-benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"rows": 6000, "table_and_indexes_bytes": size, "results": report}, indent=2))
