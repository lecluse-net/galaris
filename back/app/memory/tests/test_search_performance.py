"""A reproducible multilingual corpus; query plans are evidence, not index prescriptions."""

import hashlib
import json
from pathlib import Path
import time

import pytest
from sqlalchemy import event, text

from app.memory.models import MemoryItem, MemorySource
from app.memory.schemas import MemorySearchRequest
from app.memory.service import search_items
from app.memory.storage import get_storage
from tests.sharing_fixtures import bind_private_shares


@pytest.mark.asyncio
@pytest.mark.parametrize("derived", [False, True])
async def test_multilingual_search_has_bounded_queries_and_preserves_private_scope(db, agents, memory_storage, derived):
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
        "metadata": {"evidence_validator": "conversation"} if derived else {},
    } for index in range(6000)]
    await bind_private_shares(db, rows)
    await db.execute(MemoryItem.__table__.insert(), rows)
    await db.flush()
    await db.execute(text("ANALYZE memory_items"))
    if derived:
        from app.connection import Connection
        from app.messenger import Message, Room
        from app.tools import ToolModel
        from sqlalchemy import select
        from uuid import uuid4

        tool = ToolModel(code=f"synthetic-memory-{uuid4().hex[:10]}", label="Synthetic written source", description="", connection_schema={})
        db.add(tool)
        await db.flush()
        channel = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
        db.add(channel)
        await db.flush()
        room = Room(connection_id=channel.id, external_id="synthetic-room", label="Synthetic room", kind="direct", conversation_type="text")
        db.add(room)
        await db.flush()
        message = Message(connection_id=channel.id, tool_id=tool.id, platform="synthetic",
            remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id,
            room_id=room.external_id, text="Synthetic multilingual budget evidence.")
        db.add(message)
        await db.flush()
        identities = list(await db.scalars(select(MemoryItem.id).where(MemoryItem.owner_agent_id == owner.id)))
        await db.execute(MemorySource.__table__.insert(), [{"item_id": identity, "source_kind": "synthetic",
            "source_ref": f"message:{message.id}", "metadata": {"evidence_validator": "conversation", "source_evidence": [{
                "ref": f"{message.id}:written", "kind": "written", "message_id": str(message.id),
                "version": {"text_sha256": hashlib.sha256(message.text.encode()).hexdigest()}}]}}
            for identity in identities])
        await db.flush()
    connection = await db.connection()
    report = []
    for query in ("voyage", "travel", "预算"):
        statements = []

        def capture(_connection, _cursor, statement, parameters, _context, _many, captured=statements):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                captured.append((statement, parameters))

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
            if "memory_items" in statement:
                plans.append((await connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
                )).scalar_one())
        report.append({"query": query, "seconds": elapsed, "query_count": len(statements), "plans": plans})
    size = await db.scalar(text("SELECT pg_total_relation_size('memory_items')"))
    suffix = "-derived" if derived else ""
    destination = Path(__file__).resolve().parents[4] / f"artifacts/memory-search-benchmark{suffix}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"rows": 6000, "table_and_indexes_bytes": size, "results": report}, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "library"])
async def test_memory_reads_keep_connection_planner_defaults_after_commit_and_rollback(committed_database, operation):
    from core.database import get_db_session
    from app.memory.library_queries import browse_document_library
    from app.memory.schemas import DocumentLibraryRequest

    async with get_db_session() as session:
        original = await session.scalar(text("SHOW jit"))
        for finish in (session.commit, session.rollback):
            if operation == "search":
                result = await search_items(MemorySearchRequest(agent_id=1, query="Synthetic absent planner probe"))
                assert result.hits == []
            else:
                page = await browse_document_library(DocumentLibraryRequest(), managed_agent_ids=set())
                assert page.entries == []
            await finish()
            assert await session.scalar(text("SHOW jit")) == original
