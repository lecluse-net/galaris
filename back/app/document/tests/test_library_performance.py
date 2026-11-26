"""Library-page query and memory budgets across a growing revision corpus."""

import asyncio
import gc
import hashlib
import json
from math import ceil
from pathlib import Path
import time
import tracemalloc
from statistics import median
from uuid import uuid4

import pytest
from sqlalchemy import event, func, literal, select, text, update

from app.document import resource_service as service
from app.document import Document, DocumentNesting, DocumentRevision, DocumentTag, DocumentTagAssignment
from app.document.schemas import DocumentLibraryRequest
from core.storage import get_storage
from core.user import UserModel
from tests.sharing_fixtures import bind_private_shares


@pytest.mark.asyncio
@pytest.mark.parametrize("document_count", [1000, 10000])
@pytest.mark.parametrize("change", ["membership", "activation"])
async def test_team_membership_projection_matches_full_repair(db, agents, document_count, change):
    from app.agent import Agent, AgentTeamModel
    from app.document.effective_sharing import project_document_access, project_user_document_access
    from app.document.sharing_inheritance import refresh_team_document_access
    from app.share import ShareEffectiveAccess, ShareGrant
    from core.team import TeamModel, TeamUserModel

    owner, _ = agents
    team = TeamModel(name="Projection benchmark team")
    reader = UserModel(email="new-team-reader@example.test", hashed_password="unused", is_active=change == "membership")
    members = [Agent(code=f"projection-member-{i}", title_id=owner.title_id, first_name="Team", last_name=str(i),
                     agent_driver="internal") for i in range(50)]
    db.add_all([team, reader, *members])
    await db.flush()
    db.add_all(AgentTeamModel(team_id=team.id, agent_id=agent.id) for agent in members)
    if change == "activation":
        db.add(TeamUserModel(team_id=team.id, user_id=reader.id))
    rows = [{"id": uuid4(), "owner_agent_id": owner.id, "provider_code": "native", "resource_id": str(i),
             "title": f"Projection document {i}", "content_hash": "0" * 64} for i in range(document_count)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    expected = {row["share_id"]: bool(i % 2) for i, row in enumerate(rows[:50])}
    db.add_all(ShareGrant(share_id=share_id, team_id=team.id, can_write=write) for share_id, write in expected.items())
    await project_document_access(db)
    await db.execute(text("ANALYZE documents, share_configs, share_grants, share_effective_access, agent_teams, team_users"))
    team_id, user_id = team.id, reader.id
    projected = select(ShareEffectiveAccess.share_id, ShareEffectiveAccess.can_write).where(ShareEffectiveAccess.user_id == user_id)
    timings = {"full": [], "member": []}
    for wave in range(4):
        for mode in (("full", "member") if wave % 2 == 0 else ("member", "full")):
            savepoint = await db.begin_nested()
            if change == "activation":
                await db.execute(update(UserModel).where(UserModel.id == user_id).values(is_active=True))
            else:
                await db.execute(TeamUserModel.__table__.insert().values(team_id=team_id, user_id=user_id))
            started = time.perf_counter()
            if mode == "full":
                await project_document_access(db)
            elif change == "activation":
                await project_user_document_access(user_id, True)
            else:
                await refresh_team_document_access(team_id, ("user", user_id))
            timings[mode].append((time.perf_counter() - started) * 1000)
            assert dict((await db.execute(projected)).tuples().all()) == expected
            await savepoint.rollback()
            assert not (await db.execute(projected)).all()
    print(f"TEAM_PERF change={change} documents={document_count} shared=50 existing_members=50 waves=4 "
          f"full_median_ms={median(timings['full']):.1f} member_median_ms={median(timings['member']):.1f}")


@pytest.mark.asyncio
async def test_32_personal_libraries_remain_readable_during_agent_archival(committed_database):
    from app.agent import Agent, agent_service
    from app.agent.models import Title
    from app.document.effective_sharing import project_document_access
    from app.share import ShareConfig, ShareEffectiveAccess
    from core.database import get_db_session, lock_resource_sharing

    async with get_db_session() as db:
        readers = [UserModel(email=f"reader-{i}@example.test", hashed_password="unused", is_active=True)
                   for i in range(32)]
        title = Title(label="Synthetic load", gender="X")
        manager = UserModel(email="owner@example.test", hashed_password="unused", is_active=True)
        agent = Agent(title=title, user=manager, code="load-agent", first_name="Archive", last_name="Test")
        db.add_all([agent, *readers])
        await db.flush()
        agent_id = agent.id
        rows = [{"id": uuid4(), "owner_user_id": manager.id, "title": f"Library {i}", "provider_code": "native",
                 "resource_id": str(i), "content_hash": "0" * 64} for i in range(1000)]
        public = rows[:49]
        personal = {}
        for reader, row in zip(readers, rows[49:81], strict=True):
            row["owner_user_id"] = reader.id
            personal[reader.id] = row["id"]
        await bind_private_shares(db, rows, kind="document")
        await db.execute(Document.__table__.insert(), rows)
        await db.execute(update(ShareConfig).where(ShareConfig.id.in_(
            [row["share_id"] for row in public])).values(global_access=1))
        await project_document_access(db)
        agent_rows = select(func.count()).select_from(ShareEffectiveAccess).where(ShareEffectiveAccess.agent_id == agent_id)
        assert await db.scalar(agent_rows) == len(public)
        await db.execute(text("ANALYZE documents, share_configs, share_effective_access"))

    class InterruptedArchive(Exception):
        pass

    def interrupt_commit(session):
        if not session.in_nested_transaction():
            assert session.scalar(agent_rows) == 0
            raise InterruptedArchive

    with pytest.raises(InterruptedArchive):
        async with get_db_session() as writer:
            event.listen(writer.sync_session, "before_commit", interrupt_commit)
            assert await agent_service.delete(agent_id)
    async with get_db_session() as reopened:
        assert await reopened.scalar(select(Agent.code).where(Agent.id == agent_id)) == "load-agent"
        assert await reopened.scalar(agent_rows) == len(public)

    ready = asyncio.get_running_loop().create_future()
    async def archive():
        async with get_db_session() as writer:
            ready.set_result(await writer.scalar(text("SELECT pg_backend_pid()")))
            assert await agent_service.delete(agent_id)

    public_ids = {row["id"] for row in public}
    async def read(user_id, private_id):
        started = time.perf_counter()
        async with get_db_session():
            page = await service.browse_document_library(DocumentLibraryRequest(), managed_agent_ids=set(), user_id=user_id)
        elapsed = time.perf_counter() - started
        assert page.total == 50
        assert {entry.item.id for entry in page.entries} == public_ids | {private_id}
        assert {entry.item.id for entry in page.entries if entry.user_access.can_write} == {private_id}
        return elapsed

    async with asyncio.timeout(30), asyncio.TaskGroup() as group:
        async with get_db_session() as holder:
            await lock_resource_sharing()
            group.create_task(archive())
            pid = await ready
            while not await holder.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                await asyncio.sleep(0.01)
            for wave in range(3):
                times = await asyncio.gather(*(read(uid, doc) for uid, doc in personal.items()))
                p95 = sorted(times)[ceil(len(times) * 0.95) - 1]
                print(f"LIBRARY_PERF users={len(times)} documents={len(rows)} wave={wave + 1} "
                      f"median_ms={1000 * median(times):.1f} p95_ms={1000 * p95:.1f}")
    async with get_db_session() as db:
        assert await db.scalar(agent_rows) == 0


@pytest.mark.asyncio
async def test_library_page_in_a_large_team(db, agents):
    from app.agent import Agent, AgentTeamModel
    from app.share import ShareGrant
    from core.team import TeamModel, TeamUserModel

    owner, peer = agents
    others = [Agent(code=f"library-peer-{i}", first_name="Library", last_name=str(i),
                    title_id=owner.title_id, agent_driver="internal") for i in range(48)]
    reader = UserModel(email="library-team@example.test", hashed_password="unused", is_active=True)
    team = TeamModel(name="Library readers")
    db.add_all([reader, team, *others])
    await db.flush()
    members = [owner.id, peer.id, *(agent.id for agent in others)]
    db.add_all(AgentTeamModel(team_id=team.id, agent_id=aid) for aid in members)
    db.add(TeamUserModel(team_id=team.id, user_id=reader.id))
    documents = [Document(owner_agent_id=owner.id, title=f"Team item {i:02d}", provider_code="native",
                          resource_id=f"team-{i}", read_only=i == 0, content_hash="0" * 64) for i in range(50)]
    db.add_all(documents)
    await db.flush()
    for item in documents:
        db.add_all([ShareGrant(share_id=item.share_id, team_id=team.id, can_write=False),
                    ShareGrant(share_id=item.share_id, agent_id=peer.id, can_write=True)])
    await db.flush()

    connection = await db.connection()
    request = DocumentLibraryRequest(limit=50)
    for label, scope in (("human", set()), ("one_agent", {peer.id}), ("all_agents", None)):
        counts = []

        def count_rows(_conn, cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("WITH", "SELECT")):
                counts.append(cursor.rowcount)

        event.listen(connection.sync_connection, "after_cursor_execute", count_rows)
        started = time.perf_counter()
        try:
            page = await service.browse_document_library(request, managed_agent_ids=scope, user_id=reader.id)
        finally:
            event.remove(connection.sync_connection, "after_cursor_execute", count_rows)
        print(f"TEAM_PAGE scope={label} reads={len(counts)} rows={sum(counts)} "
              f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}")
        assert page.total == len(page.entries) == 50
        assert len(counts) == 1 and sum(counts) == len(page.entries), (
            "A shared page must return each document and its live beneficiary flags in one snapshot"
        )
        expected = sorted(members if scope is None else scope)
        for entry in page.entries:
            assert entry.user_access.can_read and not entry.user_access.can_write
            assert entry.agent_ids == expected
            assert entry.writable_agent_ids == ([] if entry.item.read_only else sorted({owner.id, peer.id}.intersection(expected)))
            assert [(g.agent_id, g.can_write) for g in entry.item.grants] == [(peer.id, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("document_count", [600, 6000])
async def test_grouped_navigation_cost_and_live_access(db, agents, memory_storage, document_count):
    """Measure recent navigation paths with repeated tags and a private peer corpus."""
    from app.agent import AgentManagementScope
    from app.document import agent_library, topic_library
    from app.document.topic_assignment import change_assignment
    from app.topic import Topic
    from app.document.models import DocumentListPosition

    owner, peer = agents
    human = UserModel(email="synthetic-navigation@example.test", hashed_password="unused", is_active=True)
    topics = [Topic(title=f"Synthetic group {index}", description="", keywords=[]) for index in range(3)]
    db.add_all([human, *topics])
    await db.flush()
    owner_id, peer_id, user_id = owner.id, peer.id, human.id
    topic_ids = [topic.id for topic in topics]
    scope = AgentManagementScope(user_id=user_id, agent_ids=frozenset({owner_id}))
    resource = await get_storage("native").create(b"Synthetic navigation")
    rows = [{"id": uuid4(), "owner_agent_id": owner_id if index % 3 != 2 else peer_id,
        "resource_id": resource, "provider_code": "native", "title": f"Synthetic document {index:05d}",
        "topic_id": topic_ids[index % 3], "keywords": ["Common", "common", f"tag-{index % 7}"] if index % 5 else [],
        "content_hash": "0" * 64} for index in range(document_count)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    # Position order deliberately differs from title order for range endpoints.
    await db.execute(DocumentListPosition.__table__.insert(), [{"user_id": user_id, "document_id": row["id"],
        "position": document_count - index} for index, row in enumerate(rows)])
    await db.commit()
    await db.execute(text("ANALYZE documents, share_configs, share_grants, document_list_positions"))
    visible = [row for index, row in enumerate(rows) if index % 3 != 2]
    measurements = {}

    async def measure(name, read):
        samples = []
        result = None
        for _ in range(3):
            db.expunge_all()
            connection = await db.connection()
            reads = []

            def capture(_connection, cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                    reads.append({"rows": cursor.rowcount})

            event.listen(connection.sync_connection, "after_cursor_execute", capture)
            gc.collect()
            tracemalloc.start()
            started = time.perf_counter()
            try:
                result = await read()
                _, peak = tracemalloc.get_traced_memory()
            finally:
                elapsed = time.perf_counter() - started
                tracemalloc.stop()
                event.remove(connection.sync_connection, "after_cursor_execute", capture)
            samples.append({"seconds": elapsed, "python_peak_bytes": peak, "queries": len(reads),
                "returned_rows": sum(max(0, read["rows"]) for read in reads)})
            await db.rollback()
        measurements[name] = {key: median(sample[key] for sample in samples) for key in samples[0]}
        return result

    groups = await measure("topics", lambda: topic_library.catalog(scope))
    for group in groups:
        expected = [row for row in visible if row["topic_id"] == group.id]
        assert group.document_count == len(expected)
        assert group.without_keywords_count == sum(not row["keywords"] for row in expected)
        assert set(group.keywords) == {keyword for row in expected for keyword in row["keywords"]}
    assert {group.id for group in groups} == set(topic_ids[:2])
    owners = await measure("agents", lambda: agent_library.catalog(scope))
    assert len(owners) == 1 and owners[0].id == owner_id and owners[0].document_count == len(visible)
    assert set(owners[0].keywords) == {keyword for row in visible for keyword in row["keywords"]}
    page = await measure("ranges", lambda: service.browse_document_library(DocumentLibraryRequest(
        include_tree_ranges=True, include_keywords=False, sort_by="position", limit=100,
    ), managed_agent_ids=scope.agent_ids, user_id=user_id))
    ordered = list(reversed(visible))
    assert [entry.item.id for entry in page.entries] == [row["id"] for row in ordered[:100]]
    assert [(group.first_title, group.last_title) for group in page.tree_ranges] == [
        (ordered[offset]["title"], ordered[min(offset + 100, len(ordered)) - 1]["title"])
        for offset in range(0, len(ordered), 100)
    ]

    async def move():
        for row in visible[:20]:
            await change_assignment(row["id"], scope, topic_id=topic_ids[1], expected_topic_id=row["topic_id"],
                expected_lock_version=1, keyword_move=(None, "target"))

    await measure("topic_changes", move)
    assert measurements["topics"]["returned_rows"] == 2, "Topic catalogs must transfer groups, not the document corpus"
    assert measurements["agents"]["returned_rows"] == 1, "Owner catalogs must transfer groups, not the document corpus"
    assert measurements["ranges"]["queries"] <= 3, "Named ranges must reuse the page's visibility snapshot"
    assert measurements["topic_changes"]["queries"] <= 120, "Classification must not reload content or auxiliary collections"
    destination = Path(__file__).resolve().parents[4] / "artifacts" / "document-optimization"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"navigation-{document_count}.json").write_text(json.dumps({
        "documents": document_count, "visible_documents": len(visible), "measurements": measurements,
    }, indent=2) + "\n")
    # Read-only groups must reflect a subsequent revocation without shared caching.
    await db.execute(Document.__table__.update().where(Document.id.in_([row["id"] for row in visible]))
        .values(owner_agent_id=peer_id))
    await db.commit()
    assert await topic_library.catalog(scope) == []
    assert await agent_library.catalog(scope) == []


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
    # Bulk fixture writes and rolled-back tests leave planner statistics
    # unrelated to this corpus. Measure the same dataset regardless of whether
    # autovacuum happens to analyze it during an isolated or complete run.
    await db.execute(text("ANALYZE documents, share_configs, share_grants, document_tags, "
                          "document_tag_assignments, document_nesting, document_list_positions"))
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
        payload_columns = {"content", "summary_content", "search_text", "search_vector", "summary_source_text"}
        returned_payloads = set()

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        def capture_payloads(_connection, cursor, _statement, _parameters, _context, _many):
            returned_payloads.update(column[0] for column in cursor.description or () if column[0] in payload_columns)

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        event.listen(connection.sync_connection, "after_cursor_execute", capture_payloads)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            page = await service.browse_document_library(DocumentLibraryRequest(limit=50), managed_agent_ids={owner_id})
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            elapsed = time.perf_counter() - started
            tracemalloc.stop()
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
            event.remove(connection.sync_connection, "after_cursor_execute", capture_payloads)
        assert page.total == stop // 2 and len(page.entries) == 50
        assert page.keywords == ["visible"]
        assert all(entry.item.owner_agent_id == owner_id for entry in page.entries)
        assert not returned_payloads, f"Navigation returned document bodies or search data: {returned_payloads}"
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
