"""Library-page query and memory budgets across a growing revision corpus."""

import gc
import hashlib
import json
from pathlib import Path
import time
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import event, func, literal, select, text

from app.document import resource_service as service
from app.document import Document, DocumentNesting, DocumentRevision, DocumentTag, DocumentTagAssignment
from app.document.schemas import DocumentLibraryRequest
from core.storage import get_storage
from core.user import UserModel
from tests.sharing_fixtures import bind_private_shares


@pytest.mark.asyncio
@pytest.mark.parametrize("document_count", [120, 960])
async def test_personal_tree_does_not_repeat_whole_library_access_checks(db, agents, memory_storage, document_count):
    """Exercise the human ACL and classification path used when expanding a tree."""
    owner, peer = agents
    owner_id = owner.id
    user = UserModel(email="library-performance@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    user_id = user.id
    resource = await get_storage("native").create(b"personal tree benchmark")
    rows = [{
        "id": uuid4(), "owner_agent_id": owner.id if index % 3 == 0 else peer.id if index % 3 == 1 else None,
        "owner_user_id": user_id if index % 3 == 2 else None,
        "resource_id": resource, "provider_code": "native", "title": f"Synthetic tree document {index:04d}",
        "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
    } for index in range(document_count)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    folder = DocumentTag(user_id=user_id, name="Synthetic folder")
    db.add(folder)
    await db.flush()
    folder_id = folder.id
    parent_id = rows[0]["id"]
    halfway = document_count // 2
    nested_until = document_count * 3 // 4
    await db.execute(DocumentTagAssignment.__table__.insert(), [{
        "tag_id": folder_id, "document_id": row["id"], "position": index,
    } for index, row in enumerate(rows[:halfway])])
    await db.execute(DocumentNesting.__table__.insert(), [{
        "user_id": user_id, "parent_document_id": parent_id, "document_id": row["id"], "position": index,
    } for index, row in enumerate(rows[halfway:nested_until])])
    await db.commit()
    db.expunge_all()
    measurements = []
    for scope_name, agent_ids in (("managed", {owner_id}), ("all_agents", None)):
        for branch, request, expected in (
            ("initial", DocumentLibraryRequest(classification="unclassified", include_owners=True,
                sort_by="position", limit=50), rows[nested_until:]),
            ("all", DocumentLibraryRequest(include_owners=True, limit=50), rows),
            ("folder", DocumentLibraryRequest(tag_id=folder_id, classification="classified", include_descendants=False,
                sort_by="position", include_keywords=False, limit=500), rows[:halfway]),
            ("document", DocumentLibraryRequest(parent_document_id=parent_id, classification="classified", include_descendants=False,
                sort_by="position", include_keywords=False, limit=500), rows[halfway:nested_until]),
        ):
            if branch == "initial":
                # Make compilation reproducible even on a tiny fresh database.
                # Real installations reach the default threshold through ACL costs.
                await db.execute(text("SET LOCAL jit = on"))
                await db.execute(text("SET LOCAL jit_above_cost = 0"))
            connection = await db.connection()
            statements = []
            query_started = 0.0

            def before(_connection, _cursor, _statement, _parameters, _context, _many):
                nonlocal query_started
                query_started = time.perf_counter()

            def after(_connection, _cursor, statement, parameters, _context, _many):
                if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                    statements.append((statement, parameters, time.perf_counter() - query_started))

            event.listen(connection.sync_connection, "before_cursor_execute", before)
            event.listen(connection.sync_connection, "after_cursor_execute", after)
            started = time.perf_counter()
            try:
                page = await service.browse_document_library(request, managed_agent_ids=agent_ids, user_id=user_id)
            finally:
                elapsed = time.perf_counter() - started
                event.remove(connection.sync_connection, "before_cursor_execute", before)
                event.remove(connection.sync_connection, "after_cursor_execute", after)
            expected_ids = [row["id"] for index, row in enumerate(expected) if agent_ids is None or index % 3 != 1]
            assert [entry.item.id for entry in page.entries] == expected_ids[:request.limit]
            assert page.total == len(expected_ids) and page.has_more == (len(expected_ids) > request.limit)
            assert all(entry.user_access.can_write == (entry.item.owner_user_id == user_id) for entry in page.entries)
            if branch == "folder":
                nested_visible = [row for index, row in enumerate(rows[halfway:nested_until]) if agent_ids is None or index % 3 != 1]
                assert page.entries[0].children_count == len(nested_visible)
            elif branch == "document":
                assert all(entry.parent_document_id == parent_id and entry.children_count == 0 for entry in page.entries)
            plans = []
            for statement, parameters, seconds in statements:
                plan = (await connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)).scalar_one()[0]
                plans.append({"seconds": seconds, "planning_ms": plan["Planning Time"], "jit": plan.get("JIT"),
                    "execution_ms": plan["Execution Time"],
                    "buffer_accesses": plan["Plan"]["Shared Hit Blocks"] + plan["Plan"]["Shared Read Blocks"],
                    "plan": plan["Plan"]})
            measurements.append({"scope": scope_name, "branch": branch, "seconds": elapsed, "queries": plans})
            if branch == "initial":
                await db.execute(text("SET LOCAL jit_above_cost = DEFAULT"))
    filename = "memory-tree-benchmark.json" if document_count == 120 else f"memory-tree-benchmark-{document_count}.json"
    destination = Path(__file__).resolve().parents[4] / "artifacts" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(measurements, indent=2, default=str) + "\n")
    assert all(len(m["queries"]) <= (3 if m["branch"] in {"initial", "all"} else 4) for m in measurements), "Page, facets and personal access must share one live visibility scan"
    assert all(query["jit"] is None for m in measurements for query in m["queries"]), "Interactive library reads must not compile ACL plans"
    # Count logical reads as well as elapsed time: a fast runner must still catch
    # nested ACL rescans, even when all database pages are already cached.
    assert all(sum(query["buffer_accesses"] for query in m["queries"]) < 50000 * document_count // 120 for m in measurements), measurements
    assert all(m["seconds"] < 5 for m in measurements), measurements


@pytest.mark.asyncio
async def test_library_page_cost_does_not_materialize_the_revision_corpus(db, agents, memory_storage):
    owner, peer = agents
    owner_id, peer_id = owner.id, peer.id
    resource = await get_storage("native").create(b"library benchmark")
    measurements = []
    revisions_per_document = 100
    for start, stop in ((0, 100), (100, 1000)):
        rows = [{"id": uuid4(), "owner_agent_id": owner_id if index % 2 == 0 else peer_id,
                 "resource_id": resource, "provider_code": "native", "title": f"Document {index:04d}",
                 "search_text": "body " * 4000,
                 "keywords": ["visible" if index % 2 == 0 else "private"],
                 "content_hash": hashlib.sha256(b"").hexdigest()} for index in range(start, stop)]
        await bind_private_shares(db, rows, kind="document")
        await db.execute(Document.__table__.insert(), rows)
        series = func.generate_series(1, revisions_per_document).table_valued("number").render_derived()
        columns = ["id", "document_id", "revision", "provider_code", "resource_id", "content_hash", "content_type", "media_type", "title"]
        expressions = [func.gen_random_uuid(), Document.id, series.c.number,
                      Document.provider_code, Document.resource_id, Document.content_hash,
                      Document.content_type, Document.media_type, Document.title]
        await db.execute(DocumentRevision.__table__.insert().from_select(columns,
            select(*expressions).select_from(Document.__table__.join(series, literal(True))).where(Document.id.in_([row["id"] for row in rows]))))
        await db.commit()
        db.expunge_all()
        gc.collect()
        connection = await db.connection()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
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
        assert len(statements) <= 3, "Page, count, grants and facets must stay batched"
        assert not any("memory_revisions" in statement for statement in statements)
        assert not any(isinstance(value, DocumentRevision) for value in db.identity_map.values())
        assert peak < 16 * 1024 * 1024, "A library page must not allocate its corpus history"
        assert elapsed < 5
        baseline_reads = len(statements)
        statements.clear()
        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        try:
            with_facets = await service.browse_document_library(
                DocumentLibraryRequest(limit=50, include_owners=True), managed_agent_ids={owner_id},
            )
            full_reads = len(statements)
            statements.clear()
            without_facets = await service.browse_document_library(
                DocumentLibraryRequest(limit=50, include_keywords=False), managed_agent_ids={owner_id},
            )
            lean_reads = len(statements)
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
        assert without_facets.entries == with_facets.entries
        assert (without_facets.total, without_facets.has_more) == (with_facets.total, with_facets.has_more)
        assert without_facets.keywords == [] and without_facets.owners == []
        assert with_facets.keywords == ["visible"] and with_facets.owners
        assert lean_reads == full_reads <= 3, "Optional catalogues share the page read without additional round trips"
        assert not any("jsonb_array_elements_text" in statement for statement in statements)
        if stop == 1000:
            statements.clear()
            event.listen(connection.sync_connection, "before_cursor_execute", capture)
            try:
                maximum_page = await service.browse_document_library(
                    DocumentLibraryRequest(limit=500, include_keywords=False), managed_agent_ids={owner_id},
                )
            finally:
                event.remove(connection.sync_connection, "before_cursor_execute", capture)
            assert len(maximum_page.entries) == maximum_page.total == 500 and not maximum_page.has_more
            assert len(statements) <= 3, "The largest supported page must keep its bounded read count"
        measurements.append({"documents": stop, "revisions": stop * revisions_per_document,
                             "page_size": 50, "queries": baseline_reads,
                             "queries_with_facets": full_reads, "queries_without_facets": lean_reads, "python_peak_bytes": peak,
                             "seconds": elapsed, "loaded_revisions": 0})
    assert measurements[0]["queries"] == measurements[1]["queries"]
    assert measurements[1]["python_peak_bytes"] <= measurements[0]["python_peak_bytes"] + 2 * 1024 * 1024
    assert await db.scalar(select(func.count()).select_from(DocumentRevision)) == 100000
    table_bytes = await db.scalar(text("SELECT pg_total_relation_size('memory_revisions')"))
    destination = Path(__file__).resolve().parents[4] / "artifacts/memory-library-benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"measurements": measurements, "revision_table_bytes": table_bytes,
        "memory_scope": "Peak Python allocations during one page, not total process RSS or database memory."}, indent=2) + "\n")
