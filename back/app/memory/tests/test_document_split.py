"""Data preservation and live ACLs across the document/Memory separation."""

from hashlib import sha256
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.memory import document_service, service
from app.memory.document_migration import document_split_complete, needs_document_split, split_documents
from app.memory.document_backup import backup_documents, document_backup_complete, needs_document_backup
from app.memory.models import Document, DocumentRevision, MemoryItem, MemoryItemGrant, MemoryRevision, MemorySummaryRevision
from app.memory.contracts import ResourceNotFoundError
from app.memory.schemas import MemoryGrantUpdate, MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemorySearchRequest
from app.memory.storage import get_storage
from core.dbadmin import SchemaTransitionSet


def test_document_split_is_triggered_by_its_schema_expansion():
    assert needs_document_split(SchemaTransitionSet(added_tables=frozenset({"documents"})))
    assert not needs_document_split(SchemaTransitionSet(added_tables=frozenset({"document_revisions"})))
    assert not needs_document_split(SchemaTransitionSet())
    assert not needs_document_split(SchemaTransitionSet(added_tables=frozenset({"other"})))
    assert needs_document_backup(SchemaTransitionSet(removed_columns=frozenset({"memory_items.filename"})))


@pytest_asyncio.fixture
async def legacy_items(db):
    """Historical SQL storage, with no canonical Document constructed by the ORM."""
    await db.execute(text("DROP TABLE IF EXISTS galaris_migration.memory_document_split_manifest, galaris_migration.memory_document_split_rows"))
    await db.execute(text("""
        ALTER TABLE memory_items
        ADD COLUMN document_type varchar(30) NOT NULL DEFAULT 'html',
        ADD COLUMN filename varchar(500),
        ADD COLUMN visibility varchar(20) NOT NULL DEFAULT 'private',
        ADD COLUMN global_access integer NOT NULL DEFAULT 0,
        ADD COLUMN group_access integer NOT NULL DEFAULT 0
    """))

    async def create(**kwargs):
        kind = kwargs.pop("node_kind", "memory")
        legacy = {key: kwargs.pop(key) for key in (
            "document_type", "filename", "visibility", "global_access", "group_access"
        ) if key in kwargs}
        item = MemoryItem(node_kind="memory", title_is_projection=False, **kwargs)
        item.node_kind = kind
        db.add(item)
        await db.flush()
        for column, value in legacy.items():
            await db.execute(text(f"UPDATE memory_items SET {column} = :value WHERE id = :identity"),
                {"value": value, "identity": item.id})
        return item

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset", [False, True])
@pytest.mark.parametrize("legacy_keywords", [[], ["budget", "forecast"]])
async def test_legacy_document_transfer_preserves_resources_history_grants_and_replay(db, agents, memory_storage, dataset, legacy_items, legacy_keywords):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    initial = b'{"budget": 100}' if dataset else b"<p>Initial synthetic budget: 100.</p>"
    current = b'{"budget": 42000}' if dataset else b"<p>Current synthetic budget: 42000.</p>"
    storage = get_storage()
    first_resource, current_resource = await storage.create(initial), await storage.create(current)
    identity = uuid4()
    item = await legacy_items(
        id=identity, node_kind="document", owner_agent_id=owner_id, title="Synthetic budget",
        provider_code="native", resource_id=current_resource, revision=2, content_type="text",
        document_type="dataset" if dataset else "html", media_type="application/json" if dataset else "text/html",
        content_profile_version=None if dataset else 1, content_hash=sha256(current).hexdigest(),
        size_bytes=len(current), search_text=current.decode(), visibility="shared", keywords=legacy_keywords,
    )
    db.add(item)
    await db.flush()
    db.add(MemoryItemGrant(item_id=identity, agent_id=reader_id, can_write=False))
    for revision, payload, resource in ((1, initial, first_resource), (2, current, current_resource)):
        db.add(MemoryRevision(
            id=uuid4(), item_id=identity, revision=revision, provider_code="native", resource_id=resource,
            content_hash=sha256(payload).hexdigest(), content_type="text", media_type=item.media_type,
            content_profile_version=item.content_profile_version, title=item.title,
            keywords=["initial-budget"] if revision == 1 else legacy_keywords,
            metadata_={}, document_content_version=True,
        ))
    await db.commit()
    delta = SchemaTransitionSet(added_tables=frozenset({"documents", "document_revisions"}))
    assert not await document_split_complete(db, delta)
    await backup_documents(db, delta)
    await db.commit()
    await split_documents(db, delta)
    await db.commit()
    db.expire_all()
    assert await document_split_complete(db, delta)
    migrated, content, *_ = await service.get_item(identity, agent_id=reader_id)
    assert content == current
    assert migrated.lock_version == 2  # In-flight pre-migration writers must reload.
    assert await db.scalar(select(MemoryItem.content_profile_version).where(
        MemoryItem.id == identity,
    )) == (None if dataset else 1)
    assert migrated.document.id == identity
    assert migrated.document.memory_item_id == identity
    assert migrated.document.resource_id == current_resource
    with pytest.raises(service.MemoryPermissionError):
        await service.forget_item(identity, actor_agent_id=owner_id)
    assert migrated.memory_resource_id == ""
    assert migrated.keywords == legacy_keywords
    historical, historical_content, historical_access, content_type, media_type = await service.get_item(
        identity, agent_id=reader_id, revision=1,
    )
    assert (await service.item_to_detail(historical, historical_content, historical_access,
        content_type=content_type, media_type=media_type, revision=1)).keywords == ["initial-budget"]
    assert migrated.revision == 2 and migrated.memory_revision == 1
    assert (await service.get_item(identity, agent_id=reader_id, memory_content=True))[1] == b""
    assert (await service.get_item(identity, agent_id=reader_id, revision=1))[1] == initial
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == identity)) == 2
    with pytest.raises(service.MemoryPermissionError):
        await service.update_memory_content(identity, MemoryItemUpdate(payload=MemoryPayload(text="<p>Denied</p>")), actor_agent_id=reader_id)
    await service.update_memory_content(identity, MemoryItemUpdate(
        expected_revision=1, payload=MemoryPayload(text="<p>Budget synthesis.</p>"),
    ), actor_agent_id=owner_id)
    await service.update_item(identity, MemoryItemUpdate(keywords=["reclassified"]), actor_agent_id=owner_id)
    await split_documents(db, delta)
    await db.commit()
    db.expire_all()
    assert await document_split_complete(db, delta)
    assert (await service.get_item(identity, agent_id=owner_id, memory_content=True))[1] == b"<p>Budget synthesis.</p>"
    assert (await service.get_item(identity, agent_id=reader_id))[1] == current
    assert (await service.document_record(identity)).keywords == ["reclassified"]
    assert await storage.read(first_resource) == initial
    assert await storage.read(current_resource) == current


@pytest.mark.asyncio
@pytest.mark.parametrize("memory_first", [False, True])
async def test_document_keywords_are_shared_metadata_without_content_revisions(db, agents, memory_storage, memory_first):
    owner_id, reader_id = (agent.id for agent in agents)
    document = await document_service.create_document(
        owner_agent_id=owner_id, title="Synthetic keyword classification",
        content="<p>Reference content.</p>", keywords=["initial"], task_id=None,
    )
    identity = document.id
    await service.update_memory_content(identity, MemoryItemUpdate(
        payload=MemoryPayload(text="<p>Independent synthesis.</p>"),
    ), actor_agent_id=owner_id)
    await service.set_item_grant(identity, reader_id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner_id)
    initial = await service.document_record(identity)
    document_revision, memory_revision = initial.revision, initial.memory_revision
    history_count = await db.scalar(select(func.count()).select_from(MemorySummaryRevision).where(
        MemorySummaryRevision.item_id == identity,
    ))
    writers = [service.update_memory_content, service.update_item]
    if not memory_first:
        writers.reverse()
    for write, keywords in zip(writers, ([" Budget ", "budget", "Forecast"], []), strict=True):
        before = await service.document_record(identity)
        old_lock = before.lock_version
        with pytest.raises(service.MemoryPermissionError):
            await write(identity, MemoryItemUpdate(keywords=keywords), actor_agent_id=reader_id)
        changed = await write(identity, MemoryItemUpdate(
            keywords=keywords, expected_lock_version=old_lock,
        ), actor_agent_id=owner_id)
        expected_keywords = ["Budget", "Forecast"] if keywords else []
        assert changed.keywords == expected_keywords
        assert changed.lock_version > old_lock
        changed_lock = changed.lock_version
        assert changed.revision == document_revision and changed.memory_revision == memory_revision
        access = await service.assert_item_access(changed, reader_id)
        assert service.item_to_public(changed, access).keywords == expected_keywords
        assert service.item_to_public(changed, access, memory_content=True).keywords == expected_keywords
        matches = await service.search_items(MemorySearchRequest(agent_id=reader_id, query="Forecast"))
        assert [hit.item.id for hit in matches.hits] == ([identity] if keywords else [])
        assert await db.scalar(select(func.count()).select_from(MemorySummaryRevision).where(
            MemorySummaryRevision.item_id == identity,
        )) == history_count
        assert await db.scalar(select(MemorySummaryRevision.keywords).where(
            MemorySummaryRevision.item_id == identity, MemorySummaryRevision.revision == memory_revision,
        )) == ["initial"]
        with pytest.raises(service.MemoryConflictError):
            await write(identity, MemoryItemUpdate(
                keywords=["stale"], expected_lock_version=old_lock,
            ), actor_agent_id=owner_id)
        same = await write(identity, MemoryItemUpdate(
            keywords=expected_keywords, expected_lock_version=changed_lock,
        ), actor_agent_id=owner_id)
        assert same.lock_version == changed_lock
    assert (await service.get_item(identity, agent_id=owner_id))[1] == b"<p>Reference content.</p>"
    assert (await service.get_item(identity, agent_id=owner_id, memory_content=True))[1] == b"<p>Independent synthesis.</p>"


@pytest.mark.asyncio
async def test_document_and_synthesis_are_searchable_once_and_revocation_hides_both(db, agents, memory_storage):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    document = await document_service.create_document(
        owner_agent_id=owner_id, title="Synthetic financial report",
        content="<p>The copper allocation is 42000 credits.</p>", task_id=None,
    )
    identity = document.id
    await service.set_item_grant(identity, reader_id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner_id)
    for query in ("copper allocation", "financial report"):
        results = await service.search_items(MemorySearchRequest(agent_id=reader_id, query=query))
        assert [hit.item.id for hit in results.hits] == [identity]
    await service.update_memory_content(identity, MemoryItemUpdate(
        payload=MemoryPayload(text="<p>Procurement synthesis.</p>"), expected_revision=1,
    ), actor_agent_id=owner_id)
    for query in ("copper allocation", "procurement synthesis"):
        results = await service.search_items(MemorySearchRequest(agent_id=reader_id, query=query))
        assert [hit.item.id for hit in results.hits] == [identity]
    before = await service.document_record(identity)
    assert before.revision == 1 and before.memory_revision == 2
    await service.update_item(identity, MemoryItemUpdate(
        expected_revision=1, payload=MemoryPayload(text="<p>The copper allocation is 43000 credits.</p>"),
    ), actor_agent_id=owner_id)
    after = await service.document_record(identity)
    assert after.revision == 2 and after.memory_revision == 2
    assert service.item_to_public(after, await service.assert_item_access(after, owner_id), memory_content=True).summary_outdated
    await service.remove_item_grant(identity, reader_id, actor_agent_id=owner_id)
    for query in ("copper allocation", "procurement synthesis"):
        assert not (await service.search_items(MemorySearchRequest(agent_id=reader_id, query=query))).hits
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(identity, agent_id=reader_id, memory_content=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,media_type,payload", [
    ("text", "text/html", b"<p>Shared synthetic procedure.</p>"),
    ("text", "application/json", b'{"synthetic": 42}'),
    ("binary", "application/octet-stream", b"\x00\x01synthetic\xff"),
])
async def test_legacy_shared_memory_becomes_document_without_losing_access(db, agents, memory_storage, content_type, media_type, payload, legacy_items):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    resource = await get_storage().create(payload)
    identity = uuid4()
    await legacy_items(
        id=identity, owner_agent_id=owner_id, node_kind="memory", title="Shared procedure",
        provider_code="native", resource_id=resource, revision=1, content_hash=sha256(payload).hexdigest(),
        content_type=content_type, media_type=media_type, content_profile_version=1 if media_type == "text/html" else None,
        size_bytes=len(payload), search_text="Shared synthetic procedure.", visibility="public", read_only=True,
        keywords=["shared-procedure"],
    )
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    await db.commit()
    await split_documents(db, SchemaTransitionSet())
    await db.commit()
    db.expire_all()
    item, content, access, *_ = await service.get_item(identity, agent_id=reader_id)
    assert item.node_kind == "document" and content == payload
    assert item.keywords == ["shared-procedure"]
    assert item.document.global_access == 1
    assert access.can_read and not access.can_write
    assert not (await service.assert_item_access(item, owner_id)).can_write


@pytest.mark.asyncio
async def test_standalone_memory_needs_no_title_and_cannot_be_shared(db, agents, memory_storage):
    owner, reader = agents
    owner_id, reader_id = owner.id, reader.id
    memory, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner_id, payload=MemoryPayload(text="<p>Private synthetic fact.</p>"), media_type="text/html",
    ))
    assert memory.document is None
    assert (await service.get_item(memory.id, agent_id=owner_id))[1] == b"<p>Private synthetic fact.</p>"
    with pytest.raises(service.MemoryPermissionError):
        await service.set_item_grant(memory.id, reader_id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner_id)
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(memory.id, agent_id=reader_id)


@pytest.mark.asyncio
async def test_failed_transfer_rolls_back_then_replays_without_losing_original_titles_or_content(db, agents, memory_storage, legacy_items, monkeypatch):
    owner_id = agents[0].id
    body = b"<p>Original synthetic document.</p>"
    resource = await get_storage().create(body)
    doc_id, memory_id = uuid4(), uuid4()
    for identity, kind, pointer in ((doc_id, "document", resource), (memory_id, "memory", resource)):
        await legacy_items(
            id=identity, node_kind=kind, owner_agent_id=owner_id, title="Preserved synthetic label",
            provider_code="native", resource_id=pointer,
            revision=1, content_type="text", media_type="text/html", content_profile_version=1,
            content_hash=sha256(body).hexdigest(), size_bytes=len(body), visibility="private",
            keywords=["preserved-keyword"],
        )
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    await db.commit()
    original_read = get_storage().read

    async def unavailable(_pointer):
        raise ResourceNotFoundError("Synthetic temporary storage outage")

    monkeypatch.setattr(get_storage(), "read", unavailable)
    with pytest.raises(ResourceNotFoundError):
        await split_documents(db, SchemaTransitionSet())
    await db.rollback()
    db.expire_all()
    monkeypatch.setattr(get_storage(), "read", original_read)
    assert await db.get(Document, doc_id) is None
    original = await db.get(MemoryItem, doc_id)
    assert original.memory_resource_id == resource
    assert original.keywords == ["preserved-keyword"]
    assert await get_storage().read(resource) == body
    memory = await db.get(MemoryItem, memory_id)
    original_memory_resource = memory.resource_id
    await split_documents(db, SchemaTransitionSet())
    await db.commit()
    db.expire_all()
    assert await document_split_complete(db, SchemaTransitionSet())
    assert (await service.get_item(doc_id, agent_id=owner_id))[1] == body
    assert (await service.document_record(doc_id)).keywords == ["preserved-keyword"]
    current = (await service.get_item(memory_id, agent_id=owner_id))[1]
    assert b"Preserved synthetic label" in current and b"Original synthetic document." in current
    assert (await service.get_item(memory_id, agent_id=owner_id, revision=1))[1] == body
    assert await get_storage().read(original_memory_resource) == body


@pytest.mark.asyncio
async def test_backup_is_immutable_and_detects_corruption_or_source_writes(db, agents, memory_storage, legacy_items):
    resource = await get_storage().create(b"<p>Archived synthetic fact.</p>")
    item = await legacy_items(owner_agent_id=agents[0].id, title="Archived title", resource_id=resource,
        content_hash=sha256(b"<p>Archived synthetic fact.</p>").hexdigest(), media_type="text/html")
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    await db.commit()
    archived = await db.scalar(text("SELECT snapshot FROM galaris_migration.memory_document_split_rows WHERE table_name='memory_items' AND row_key=:identity"), {"identity": str(item.id)})
    item.search_title = "A writer changed the source"
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    assert await db.scalar(text("SELECT snapshot FROM galaris_migration.memory_document_split_rows WHERE table_name='memory_items' AND row_key=:identity"), {"identity": str(item.id)}) == archived
    with pytest.raises(RuntimeError, match="changed after"):
        await split_documents(db, SchemaTransitionSet())
    await db.rollback()
    assert await db.scalar(text("SELECT count(*) FROM documents")) == 0
    await db.execute(text("UPDATE galaris_migration.memory_document_split_rows SET snapshot=snapshot || '{\"title\": \"damaged\"}'::jsonb WHERE table_name='memory_items'"))
    assert not await document_backup_complete(db, SchemaTransitionSet())
    with pytest.raises(RuntimeError, match="damaged"):
        await backup_documents(db, SchemaTransitionSet())


@pytest.mark.asyncio
async def test_archived_resources_survive_forget_and_orphan_cleanup(db, agents, memory_storage, legacy_items):
    from app.memory.storage_reconciliation import _referenced
    from app.memory.automation import _process_resource_cleanup
    from app.memory.document_backup import archived_resources

    storage = get_storage()
    payload = b"<p>Synthetic archive retention.</p>"
    resource = await storage.create(payload)
    attachment_resource = await storage.create(b"synthetic attachment bytes")
    identity = uuid4()
    owner_id = agents[0].id
    await legacy_items(id=identity, node_kind="document", owner_agent_id=owner_id,
        title="Retained synthetic source", resource_id=resource, content_hash=sha256(payload).hexdigest(),
        media_type="text/html", metadata_={"document_attachments": [{
            "id": attachment_resource, "name": "synthetic.txt", "media_type": "text/plain",
            "size_bytes": 26, "created_at": "2026-01-01T00:00:00Z",
        }]})
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    await db.commit()
    await split_documents(db, SchemaTransitionSet())
    await db.commit()
    assert await archived_resources(db, "native", [resource, attachment_resource]) == {resource, attachment_resource}
    await service.delete_document(identity, actor_agent_id=owner_id)
    assert await _referenced([resource, attachment_resource]) == {resource, attachment_resource}
    await _process_resource_cleanup({"provider_code": "native", "resource_id": resource})
    assert await storage.read(resource) == payload
    assert await storage.read(attachment_resource) == b"synthetic attachment bytes"
    assert await document_backup_complete(db, SchemaTransitionSet())


@pytest.mark.asyncio
async def test_interrupted_title_conversion_removes_only_new_replacement_resources(
    db, agents, memory_storage, legacy_items, monkeypatch,
):
    from uuid import UUID
    storage = get_storage()
    payload = b"<p>Original synthetic fact.</p>"
    originals = [await storage.create(payload) for _ in range(2)]
    for number, resource in enumerate(originals, start=1):
        await legacy_items(id=UUID(int=number), owner_agent_id=agents[0].id, title="Preserved title",
            resource_id=resource, content_hash=sha256(payload).hexdigest(), media_type="text/html")
    await db.commit()
    await backup_documents(db, SchemaTransitionSet())
    await db.commit()
    original_files = {path for path in memory_storage.rglob("*") if path.is_file()}
    read = storage.read

    async def fail_late(pointer):
        if pointer == originals[1]:
            raise ResourceNotFoundError("Synthetic failure after one replacement")
        return await read(pointer)

    monkeypatch.setattr(storage, "read", fail_late)
    with pytest.raises(ResourceNotFoundError):
        await split_documents(db, SchemaTransitionSet())
    await db.rollback()
    assert {path for path in memory_storage.rglob("*") if path.is_file()} == original_files
    assert await document_backup_complete(db, SchemaTransitionSet())
    monkeypatch.setattr(storage, "read", read)
    assert all([await read(resource) == payload for resource in originals])
    await split_documents(db, SchemaTransitionSet())
    await db.commit()
    assert await document_split_complete(db, SchemaTransitionSet())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "backup", "transfer", "deferred"])
@pytest.mark.parametrize("already_expanded", [False, True])
async def test_dbadmin_detects_new_documents_archives_then_contracts_and_resumes(
    committed_database, memory_storage, monkeypatch, failure, already_expanded,
):
    """Exercise real Atlas and phase transactions, including the durable journal."""
    from dataclasses import replace
    from app.agent.models import Agent, Title
    from app.memory.document_backup import OBSOLETE_COLUMNS
    from app.memory.document_migration import register_document_split
    from core import settings
    from core.user import UserModel
    from core.dbadmin import DbAdminRegistry, DbAdminVerdict
    from core.dbadmin import orchestrator
    from core.dbadmin._internal import atlas

    isolated_engine = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", isolated_engine)
    monkeypatch.setattr(atlas, "engine", isolated_engine)
    monkeypatch.setattr(settings, "POSTGRES_DB", isolated_engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    payload = b"<p>Durable synthetic source.</p>"
    resource = await get_storage().create(payload)
    identity = uuid4()
    async with committed_database() as session:
        manager = UserModel(email="migration-manager@example.test", hashed_password="unused",
            display_name="Synthetic migration manager", is_active=True)
        title = Title(label="Synthetic migration title", gender="X")
        owner = Agent(user=manager, title=title, first_name="Synthetic", last_name="Owner",
            code="synthetic-migration-owner", agent_driver="internal")
        session.add(owner)
        await session.flush()
        owner_id = owner.id
        await session.execute(text("DROP TABLE IF EXISTS galaris_migration.memory_document_split_manifest, galaris_migration.memory_document_split_rows"))
        if not already_expanded:
            await session.execute(text("DROP TABLE document_revisions, documents"))
        await session.execute(text("""
            ALTER TABLE memory_items
            ADD COLUMN document_type varchar(30) NOT NULL DEFAULT 'html',
            ADD COLUMN filename varchar(500),
            ADD COLUMN visibility varchar(20) NOT NULL DEFAULT 'private',
            ADD COLUMN global_access integer NOT NULL DEFAULT 0,
            ADD COLUMN group_access integer NOT NULL DEFAULT 0
        """))
        await session.execute(MemoryItem.__table__.insert().values(
            id=identity, owner_agent_id=owner_id, node_kind="document", title="Synthetic archive title",
            resource_id=resource, content_hash=sha256(payload).hexdigest(), size_bytes=len(payload),
            media_type="text/html", content_profile_version=1, title_is_projection=False,
        ))
        await session.execute(text("UPDATE memory_items SET filename='synthetic-source.html' WHERE id=:identity"), {"identity": identity})
        if already_expanded:
            await session.execute(Document.__table__.insert().values(
                id=identity, memory_item_id=identity, title="Synthetic archive title",
                provider_code="native", resource_id=resource, content_hash=sha256(payload).hexdigest(),
                size_bytes=len(payload), filename="synthetic-source.html", content_profile_version=1,
            ))
            await session.execute(text("UPDATE memory_items SET resource_id='', content_hash=:empty_hash, size_bytes=0, title_is_projection=true WHERE id=:identity"),
                {"identity": identity, "empty_hash": sha256(b"").hexdigest()})
        session.add(MemoryRevision(item_id=identity, revision=1, resource_id=resource, provider_code="native",
            content_hash=sha256(payload).hexdigest(), content_type="text", media_type="text/html",
            content_profile_version=1, title="Synthetic archive title", keywords=[], metadata_={},
            document_content_version=True))
        await session.commit()

    registry = DbAdminRegistry()
    register_document_split(registry)
    if failure:
        action = next(action for action in registry.actions if action.key == (
            "app.memory.document_split_backup" if failure == "backup" else "app.memory.document_split"
        ))

        async def fail(session, delta):
            await action.handler(session, delta)
            raise RuntimeError("Synthetic interruption after handler")

        async def incomplete(session, delta):
            return False

        failing_registry = DbAdminRegistry()
        for candidate in registry.actions:
            failing_registry.register_action((replace(candidate, postcondition=incomplete) if failure == "deferred"
                else replace(candidate, handler=fail)) if candidate is action else candidate)
        result = await orchestrator.synchronize_database(target_registry=failing_registry)
        assert result.verdict is (DbAdminVerdict.DEGRADED if failure == "deferred" else DbAdminVerdict.FATAL)
        async with committed_database() as session:
            columns = set(await session.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_items'")))
            assert OBSOLETE_COLUMNS <= columns
            assert await session.scalar(text("SELECT resource_id FROM memory_items WHERE id=:identity"), {"identity": identity}) == ("" if already_expanded or failure == "deferred" else resource)
            assert bool(await session.scalar(text("SELECT to_regclass('public.documents') IS NOT NULL"))) == (already_expanded or failure != "backup")
            if failure == "transfer":
                assert await document_backup_complete(session, SchemaTransitionSet())
                assert not await session.scalar(text("SELECT transferred FROM galaris_migration.memory_document_split_manifest"))
                assert await session.scalar(text("SELECT count(*) FROM documents")) == (1 if already_expanded else 0)

    result = await orchestrator.synchronize_database(target_registry=registry)
    assert result.verdict is DbAdminVerdict.CONVERGED
    async with committed_database() as session:
        columns = set(await session.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_items'")))
        assert not OBSOLETE_COLUMNS & columns
        assert await document_backup_complete(session, SchemaTransitionSet())
        assert await document_split_complete(session, SchemaTransitionSet())
        assert await session.scalar(text("SELECT snapshot->>'filename' FROM galaris_migration.memory_document_split_rows WHERE table_name='memory_items' AND row_key=:identity"), {"identity": str(identity)}) == "synthetic-source.html"
        assert await session.scalar(text("SELECT filename FROM documents WHERE id=:identity"), {"identity": identity}) == "synthetic-source.html"
        assert await session.scalar(text("SELECT resource_id FROM memory_items WHERE id=:identity"), {"identity": identity}) == ""
    second = await orchestrator.synchronize_database(target_registry=registry)
    assert second.verdict is DbAdminVerdict.CONVERGED and not second.action_results
    assert await get_storage().read(resource) == payload
