from time import perf_counter
import gc
import hashlib
import json
from pathlib import Path
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from app.agent import AgentManagementScope
from app.document import bulk_moves, document_tags, resource_service
from app.document.models import Document, DocumentTagAssignment, DocumentNesting
from app.document.schemas import DocumentItemCreate, DocumentPayload, DocumentTagWrite, DocumentOrderBatch, DocumentOrderNode, DocumentOwnerBatch, DocumentOwnerBatchEntry
from core.database import engine
from core.user import UserModel
from app.topic import Topic
from app.topic.service import move_library_documents
from app.document.schemas import DocumentTopicBatch, DocumentTopicBatchEntry


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["keywords", "owners"])
async def test_bulk_metadata_cost_and_content_preservation(db, agents, memory_storage, operation):
    from app.document.keyword_actions import replace_keywords
    from app.document.schemas import DocumentKeywordChange
    from core.storage import get_storage
    from tests.sharing_fixtures import bind_private_shares

    owner, peer = agents
    owner_id, peer_id = owner.id, peer.id
    human = UserModel(email="synthetic-metadata-batch@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner_id, peer_id}))
    resource = await get_storage("native").create(b"Synthetic metadata batch")
    rows = [{"id": uuid4(), "owner_agent_id": owner_id, "title": f"Synthetic metadata {index:02d}",
        "resource_id": resource, "provider_code": "native", "content_hash": "0" * 64,
        "keywords": ["source", "retained"]} for index in range(40)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    await db.commit()
    ids = [row["id"] for row in rows]
    measurements = []
    for size in (32, 400_000):
        body = "x" * size
        digest = hashlib.sha256(body.encode()).hexdigest()
        await db.execute(Document.__table__.update().where(Document.id.in_(ids)).values(
            content=body, content_hash=digest, keywords=["source", "retained"]))
        await db.commit()
        versions = dict((await db.execute(select(Document.id, Document.lock_version).where(Document.id.in_(ids)))).tuples().all())
        target = peer_id if size == 32 else owner_id
        if operation == "keywords":
            data = DocumentKeywordChange(documents=[{"id": identity, "expected_lock_version": version} for identity, version in versions.items()],
                source_keywords=["source"], keyword="target")
        else:
            data = DocumentOwnerBatch(documents=[DocumentOwnerBatchEntry(document_id=identity, kind="agent", id=target,
                expected_revision=1, expected_lock_version=version, keywords=["retained", "target"]) for identity, version in versions.items()])
        db.expunge_all()
        gc.collect()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        tracemalloc.start()
        started = perf_counter()
        try:
            if operation == "keywords":
                await replace_keywords(data, scope)
            else:
                await bulk_moves.move_owners(data, scope)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            elapsed = perf_counter() - started
            tracemalloc.stop()
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
        measurements.append({"body_bytes_per_document": size, "documents": len(ids), "seconds": elapsed,
            "python_peak_bytes": peak, "statements": len(statements),
            "reads": sum(statement.lstrip().upper().startswith(("SELECT", "WITH")) for statement in statements)})
        saved = (await db.execute(select(Document.content_hash, func.octet_length(Document.content),
            Document.revision, Document.keywords, Document.owner_agent_id, Document.content).where(Document.id.in_(ids)))).all()
        assert len(saved) == len(ids)
        assert all((row[0], row[1], row[2], row[3]) == (digest, size, 1, ["retained", "target"]) and row[5] == body for row in saved)
        if operation == "owners":
            assert {row[4] for row in saved} == {target}
    destination = Path(__file__).resolve().parents[4] / "artifacts" / "document-optimization"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"bulk-{operation}.json").write_text(json.dumps(measurements, indent=2) + "\n")
    if operation == "keywords":
        assert all(sample["reads"] <= 5 * len(ids) + 5 for sample in measurements), "Keyword metadata must use one bounded locked read"
        assert measurements[1]["python_peak_bytes"] <= measurements[0]["python_peak_bytes"] + 2 * 1024 * 1024, "Keyword memory cost must not grow with document bodies"
    else:
        assert all(sample["reads"] <= 23 * len(ids) for sample in measurements), "Ownership preflight must not reload every document's auxiliary collections"


async def setup(db, owner, count):
    user = UserModel(email=f"synthetic-bulk-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner.id}))
    folder = await document_tags.write_tag(user.id, DocumentTagWrite(name="Synthetic batch destination"))
    items = []
    for index in range(count):
        item, _ = await resource_service.create_item(DocumentItemCreate(owner_agent_id=owner.id,
            title=f"Synthetic batch {index:03}", keywords=["synthetic-batch"], payload=DocumentPayload(text="<p>Synthetic body</p>")))
        items.append(item)
    return scope, folder, items


@pytest.mark.asyncio
async def test_210_document_block_moves_preserve_every_row_order_and_personal_isolation(db, agents, memory_storage):
    scope, folder, items = await setup(db, agents[0], 211)
    ids = [item.id for item in items[:210]]
    other = UserModel(email=f"synthetic-other-bulk-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(other)
    await db.flush()
    other_scope = AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids)
    other_folder = await document_tags.write_tag(other.id, DocumentTagWrite(name="Synthetic other user's folder"))
    await document_tags.assign_tag(other_scope, ids[0], other_folder.id)
    other_folder_id = other_folder.id
    versions = [(item.revision, item.lock_version) for item in items]
    await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=ids[0]),
        document_ids=ids, parent_id=folder.id), scope)
    rows = list(await db.scalars(select(DocumentTagAssignment).where(DocumentTagAssignment.tag_id == folder.id).order_by(DocumentTagAssignment.position)))
    assert [row.document_id for row in rows] == ids
    assert [(item.revision, item.lock_version) for item in items] == versions
    parent = items[-1]
    parent_id = parent.id
    await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=ids[0]),
        document_ids=ids, parent_document_id=parent.id), scope)
    nested = list(await db.scalars(select(DocumentNesting).where(DocumentNesting.parent_document_id == parent.id).order_by(DocumentNesting.position)))
    assert [row.document_id for row in nested] == ids
    assert not list(await db.scalars(select(DocumentTagAssignment).where(DocumentTagAssignment.tag_id == folder.id)))
    assert await db.scalar(select(DocumentTagAssignment.document_id).where(DocumentTagAssignment.tag_id == other_folder_id)) == ids[0]
    # A cycle involving one selected ancestor rejects the entire operation.
    with pytest.raises(ValueError):
        await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=parent.id),
            document_ids=[parent.id, ids[1]], parent_document_id=ids[0]), scope)
    await db.rollback()
    assert await db.scalar(select(DocumentNesting.parent_document_id).where(DocumentNesting.document_id == ids[0])) == parent_id


@pytest.mark.asyncio
async def test_batch_avoids_per_document_directory_and_acl_rebuilds(db, agents, memory_storage):
    scope, folder, items = await setup(db, agents[0], 12)
    queries = []
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        started = perf_counter()
        for item in items:
            await document_tags.move_document(scope, item.id, folder.id)
        sequential = len(queries), perf_counter() - started
        for item in items:
            await document_tags.move_document(scope, item.id, None)
        queries.clear()
        started = perf_counter()
        await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=items[0].id),
            document_ids=[item.id for item in items], parent_id=folder.id), scope)
        batch = len(queries), perf_counter() - started
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    print({"documents": 12, "sequential_queries_seconds": sequential, "batch_queries_seconds": batch})
    assert batch[0] < sequential[0] / 2


@pytest.mark.asyncio
async def test_owner_batch_preserves_editor_grants_keywords_and_rejects_stale_batches(db, agents, memory_storage, monkeypatch):
    scope, _, items = await setup(db, agents[0], 3)
    target_id = agents[1].id
    versions = {item.id: item.lock_version for item in items}
    data = DocumentOwnerBatch(documents=[DocumentOwnerBatchEntry(document_id=item.id, id=agents[1].id,
        kind="agent", expected_revision=item.revision, expected_lock_version=versions[item.id], keywords=["synthetic-destination"]) for item in items])
    with pytest.raises(resource_service.DocumentNotFoundError):
        await bulk_moves.move_owners(data, scope)
    scope = AgentManagementScope(user_id=scope.user_id, agent_ids=frozenset({agents[0].id, target_id}))
    from core import websocket
    from app.document.lifecycle import register_document_observer, unregister_document_observer
    invalidations, observed = [], []
    async def emit(resource, action, *args, **kwargs):
        if resource == "document" and action == "invalidate":
            invalidations.append(action)
    def observer(identity, action):
        observed.append((identity, action))
    monkeypatch.setattr(websocket, "emit", emit)
    register_document_observer("synthetic_batch_observer", observer)
    try:
        await bulk_moves.move_owners(data, scope)
    finally:
        unregister_document_observer("synthetic_batch_observer")
    assert invalidations == ["invalidate"]
    assert set(observed) == {(identity, action) for identity in versions for action in ("sharing", "update", "index")}
    for item in items:
        await db.refresh(item)
        assert item.owner_agent_id == agents[1].id
        assert item.keywords == ["synthetic-destination"]
        assert (await resource_service.effective_access(item, agents[0].id)).can_write
    with pytest.raises(resource_service.DocumentPermissionError):
        await bulk_moves.move_owners(data, AgentManagementScope(user_id=scope.user_id, agent_ids=frozenset({agents[0].id})))
    with pytest.raises(resource_service.DocumentConflictError):
        await bulk_moves.move_owners(data, scope)
    await db.rollback()
    assert set(await db.scalars(select(Document.owner_agent_id).where(Document.id.in_(versions)))) == {target_id}


@pytest.mark.asyncio
async def test_folder_batch_denies_an_inaccessible_document_without_moving_the_others(db, agents, memory_storage):
    scope, folder, items = await setup(db, agents[0], 2)
    folder_id = folder.id
    inaccessible, _ = await resource_service.create_item(DocumentItemCreate(owner_agent_id=agents[1].id,
        title="Synthetic private batch document", payload=DocumentPayload(text="<p>Private synthetic content</p>")))
    with pytest.raises(resource_service.DocumentNotFoundError):
        await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=items[0].id),
            document_ids=[items[0].id, inaccessible.id], parent_id=folder.id), scope)
    await db.rollback()
    assert not list(await db.scalars(select(DocumentTagAssignment).where(DocumentTagAssignment.tag_id == folder_id)))


@pytest.mark.asyncio
async def test_topic_batch_rolls_back_a_late_conflict_then_moves_the_complete_selection(db, agents, memory_storage):
    scope, _, items = await setup(db, agents[0], 3)
    topic = Topic(title="Synthetic batch topic", description="", keywords=[])
    db.add(topic)
    await db.commit()
    topic_id, identities = topic.id, sorted(item.id for item in items)
    entries = [DocumentTopicBatchEntry(id=item.id, topic_id=topic_id, expected_topic_id=None,
        expected_lock_version=item.lock_version, source_keyword="synthetic-batch", keyword="synthetic-target") for item in items]
    next(entry for entry in entries if entry.id == identities[-1]).expected_lock_version += 10
    with pytest.raises(resource_service.DocumentConflictError):
        await move_library_documents(DocumentTopicBatch(documents=entries), scope)
    await db.rollback()
    rows = list(await db.scalars(select(Document).where(Document.id.in_(identities))))
    assert all(item.topic_id is None and item.keywords == ["synthetic-batch"] for item in rows)
    for entry in entries:
        entry.expected_lock_version = next(item.lock_version for item in rows if item.id == entry.id)
    await move_library_documents(DocumentTopicBatch(documents=entries), scope)
    assert all(item.topic_id == topic_id and item.keywords == ["synthetic-target"] for item in rows)


@pytest.mark.asyncio
async def test_batch_places_a_block_at_an_anchor_and_rejects_stale_anchors_without_partial_moves(db, agents, memory_storage):
    scope, folder, items = await setup(db, agents[0], 7)
    identities = [item.id for item in items]
    await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=identities[0]), document_ids=identities, parent_id=folder.id), scope)
    selected = [identities[5], identities[2]]
    await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=selected[0]), document_ids=selected,
        parent_id=folder.id, anchor=DocumentOrderNode(kind="document", id=identities[1]), after=True), scope)
    expected = [identities[0], identities[1], *selected, identities[3], identities[4], identities[6]]
    actual = list(await db.scalars(select(DocumentTagAssignment.document_id).where(DocumentTagAssignment.tag_id == folder.id).order_by(DocumentTagAssignment.position)))
    assert actual == expected
    folder_id = folder.id
    other = await document_tags.write_tag(scope.user_id, DocumentTagWrite(name="Synthetic other destination"))
    with pytest.raises(ValueError):
        await bulk_moves.move_folders(DocumentOrderBatch(node=DocumentOrderNode(kind="document", id=selected[0]), document_ids=selected,
            parent_id=other.id, anchor=DocumentOrderNode(kind="document", id=identities[6])), scope)
    await db.rollback()
    assert set(await db.scalars(select(DocumentTagAssignment.document_id).where(DocumentTagAssignment.tag_id == folder_id))) == set(identities)
