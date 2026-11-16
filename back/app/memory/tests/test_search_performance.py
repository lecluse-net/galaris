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
from core.storage import get_storage
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
        from app.services import ServiceModel
        from sqlalchemy import select
        from uuid import uuid4

        tool = ServiceModel(code=f"synthetic-memory-{uuid4().hex[:10]}", label="Synthetic written source", description="", connection_schema={})
        db.add(tool)
        await db.flush()
        channel = Connection(service_id=tool.id, agent_id=owner.id, active=True)
        db.add(channel)
        await db.flush()
        room = Room(connection_id=channel.id, external_id="synthetic-room", label="Synthetic room", kind="direct", conversation_type="text")
        db.add(room)
        await db.flush()
        message = Message(connection_id=channel.id, service_id=tool.id, platform="synthetic",
            remote_message_id=str(uuid4()), direction="inbound", messenger_room_id=room.id,
            room_id=room.external_id, text="Synthetic multilingual budget evidence.")
        db.add(message)
        await db.flush()
        # The source is one message among a real history. A cast on the indexed
        # message key used to scan/hash that history again for every fact.
        await db.execute(Message.__table__.insert(), [{
            "connection_id": channel.id, "service_id": tool.id, "platform": "synthetic",
            "remote_message_id": f"unrelated-{index}", "direction": "inbound",
            "messenger_room_id": room.id, "room_id": room.external_id,
            "text": f"Synthetic unrelated history {index}",
        } for index in range(1000)])
        identities = list(await db.scalars(select(MemoryItem.id).where(MemoryItem.owner_agent_id == owner.id)))
        await db.execute(MemorySource.__table__.insert(), [{"item_id": identity, "source_kind": "synthetic",
            "source_ref": f"message:{message.id}", "metadata": {"evidence_validator": "conversation", "source_evidence": [{
                "ref": f"{message.id}:written", "kind": "written", "message_id": str(message.id),
                "version": {"text_sha256": hashlib.sha256(message.text.encode()).hexdigest()}}]}}
            for identity in identities])
        await db.flush()
        for table in ("memory_sources", "messenger_messages", "messenger_rooms", "connections"):
            await db.execute(text(f"ANALYZE {table}"))
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
        if derived:
            def nodes(plan):
                yield plan
                for child in plan.get("Plans", []):
                    yield from nodes(child)
            for explanation in plans:
                for root in explanation:
                    for node in nodes(root["Plan"]):
                        if node.get("Relation Name") == "messenger_messages":
                            examined = node["Actual Rows"] + node.get("Rows Removed by Filter", 0)
                            work = examined * node["Actual Loops"]
                            # PostgreSQL may choose indexed lookups or build a
                            # hash of the history once. Both are bounded by the
                            # input sizes; rescanning history per fact is not.
                            assert work <= 2 * (len(identities) + 1001), (
                                f"Evidence admission repeatedly scanned history: {examined} rows x {node['Actual Loops']} loops"
                            )
    if derived:
        # A bounded admission of one known fact must not read unrelated history.
        # Broad searches can legitimately hash a whole table once, which alone
        # would not detect a cast that prevents primary-key lookups.
        from app.memory.source_access import source_access_clause
        probe = []
        def capture_probe(_connection, _cursor, statement, parameters, _context, _many):
            probe.append((statement, parameters))
        event.listen(connection.sync_connection, "before_cursor_execute", capture_probe)
        try:
            assert await db.scalar(select(MemoryItem.id).where(
                MemoryItem.id == identities[0], source_access_clause())) == identities[0]
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", capture_probe)
        for statement, parameters in probe:
            explanation = (await connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
            )).scalar_one()
            for root in explanation:
                for node in nodes(root["Plan"]):
                    if node.get("Relation Name") == "messenger_messages":
                        examined = node["Actual Rows"] + node.get("Rows Removed by Filter", 0)
                        assert examined * node["Actual Loops"] <= 1, "One known fact must only look up its referenced message"
    size = await db.scalar(text("SELECT pg_total_relation_size('memory_items')"))
    suffix = "-derived" if derived else ""
    destination = Path(__file__).resolve().parents[4] / f"artifacts/memory-search-benchmark{suffix}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"rows": 6000, "table_and_indexes_bytes": size, "results": report}, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "library", "agenda", "filters", "graph"])
async def test_memory_reads_keep_connection_planner_defaults_after_commit_and_rollback(committed_database, operation):
    from core.database import get_db_session
    from app.document.library_queries import browse_document_library
    from app.document.schemas import DocumentLibraryRequest

    async with get_db_session() as session:
        original = await session.scalar(text("SHOW jit"))
        for finish in (session.commit, session.rollback):
            if operation == "search":
                result = await search_items(MemorySearchRequest(agent_id=1, query="Synthetic absent planner probe"))
                assert result.hits == []
            elif operation == "library":
                page = await browse_document_library(DocumentLibraryRequest(), managed_agent_ids=set())
                assert page.entries == []
            elif operation == "agenda":
                from datetime import datetime, timedelta, timezone
                from app.memory.agenda import memory_agenda
                start = datetime.now(timezone.utc)
                window = await memory_agenda(1, start, start + timedelta(days=1))
                assert window.items == []
            elif operation == "filters":
                from app.memory.service import list_filter_options
                options = await list_filter_options(1)
                assert options.topics == options.contacts == []
            else:
                from app.memory.service import list_graph_roots
                from app.memory.schemas import MemoryGraphRootsRequest
                page = await list_graph_roots(MemoryGraphRootsRequest(agent_id=1))
                assert page.nodes == []
            await finish()
            assert await session.scalar(text("SHOW jit")) == original


@pytest.mark.asyncio
async def test_interactive_memory_reads_do_not_fetch_bodies_and_can_reopen_details(db, agents, memory_storage):
    from app.document.schemas import DocumentItemCreate, DocumentPayload
    from app.memory.tests.document_fixtures import create_document_reference
    from app.memory import service
    from app.memory.schemas import MemoryGraphRootsRequest, MemoryGraphExpandRequest, MemoryItemCreate, MemoryLinkCreate, MemoryPayload

    owner, _peer = agents
    document, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic large document", payload=DocumentPayload(text="<p>" + "Synthetic body. " * 2000 + "</p>")))
    memory, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Synthetic memory", payload=MemoryPayload(text="<p>Synthetic private fact.</p>")))
    await service.create_link(MemoryLinkCreate(source_item_id=memory.id,
        target_item_id=document.id, relation_type="related_to"), actor_agent_id=owner.id)
    agent_id, document_id, memory_id = owner.id, document.id, memory.id
    await db.commit()
    db.expunge_all()
    connection = await db.connection()
    columns = set()

    def capture(_connection, cursor, _statement, _parameters, _context, _many):
        if cursor.description:
            columns.update(column[0] for column in cursor.description)

    event.listen(connection.sync_connection, "after_cursor_execute", capture)
    try:
        page = await service.search_items(MemorySearchRequest(agent_id=agent_id))
        assert {hit.item.id for hit in page.hits} == {memory_id, document_id}
        roots = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=agent_id))
        assert {node.id for node in roots.nodes} == {memory_id, document_id}
        expanded = await service.expand_graph_node(MemoryGraphExpandRequest(agent_id=agent_id, item_id=memory_id))
        assert [node.id for node in expanded.nodes] == [document_id]
        assert len(expanded.edges) == 1
        await service.list_filter_options(agent_id)
    finally:
        event.remove(connection.sync_connection, "after_cursor_execute", capture)
    assert not columns.intersection({"content", "summary_content", "summary_source_text", "search_vector", "search_vector_folded"})
    # A graph's metadata loader must not poison a later full detail read in
    # the same session, and the real body remains available on reopening.
    _item, content, access, _type, _media = await service.get_item(memory_id, agent_id=agent_id)
    assert access.can_read
    assert "Synthetic private fact" in content.decode()
    _item, content, access, _type, _media = await service.get_item(document_id, agent_id=agent_id)
    assert access.can_read
    assert "Synthetic body." in content.decode()
