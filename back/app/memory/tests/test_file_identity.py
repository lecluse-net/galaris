"""File byte identity, Dream policies and durable references use real PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.file_share import resource_service
from app.file_share.models import FileCatalogEntry
from app.memory import maintenance, service, memory_urls
from app.memory.deduplication import preview_duplicate_pairs
from app.memory.embedding import MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryFinding, MemoryItem, MemoryURL, MemoryUsage, DocumentAttachment
from app.memory.schemas import MemoryItemUpdate, MemoryPayload
from core.params import runtime_settings
from .conftest import create_memory_task
from .test_file_catalogue import console_catalogue as console_catalogue, acquire_fingerprints, maintain_file_duplicates


@pytest.mark.asyncio
async def test_sha_is_exact_evidence_and_dream_owns_the_merge(console_catalogue, db, monkeypatch):
    from app.memory import deduplication

    ctx, _transport, _connection, peer = console_catalogue
    for uri in ("console://first.txt", "console://second.txt"):
        await resource_service.resource_write_text(ctx, uri, "Identical synthetic bytes")
    await acquire_fingerprints(db, maintain=False)
    entries = list(await db.scalars(select(FileCatalogEntry).order_by(FileCatalogEntry.uri)))
    first, second = [await db.get(MemoryItem, entry.memory_node_id) for entry in entries]
    assert first.id != second.id and first.file_sha256 == second.file_sha256
    assert first.file_media_type == "text/plain"
    assert first.file_size_bytes == len(b"Identical synthetic bytes")
    assert first.size_bytes == 0 and first.media_type == "text/html"
    await service.update_item(second.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Personal synthetic note</p>")), actor_agent_id=ctx.agent_id)
    task_id = await create_memory_task(db, ctx.agent_id)
    for node in (first, second):
        await service.get_item(node.id, agent_id=ctx.agent_id, task_id=task_id, record_llm_access=True)
    await db.commit()

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Synthetic missing provider")

    monkeypatch.setattr(deduplication, "resolve_embedding_model", unavailable)
    preview = await preview_duplicate_pairs(threshold=1.0, limit=50, agent_id=ctx.agent_id)
    assert preview.degraded and preview.total_pairs == 1
    assert len(preview.pairs) == 1 and preview.pairs[0].similarity == 1.0
    assert (await preview_duplicate_pairs(threshold=1.0, limit=50, agent_id=peer.id)).total_pairs == 0
    chosen = min((first, second), key=lambda node: str(node.id))
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "automatic")
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "off")
    assert await maintenance.detect_for_item(chosen.id) == []
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    finding_ids = await maintenance.detect_for_item(chosen.id)
    assert len(finding_ids) == 1
    finding = await db.get(MemoryFinding, finding_ids[0])
    assert finding.kind == "duplicate" and finding.score == 1.0 and finding.status == "pending"
    assert len(list(await db.scalars(select(MemoryItem).where(MemoryItem.node_kind == "file")))) == 2
    await maintain_file_duplicates(db)
    for entry in entries:
        await db.refresh(entry)
    assert entries[0].memory_node_id == entries[1].memory_node_id
    canonical = await db.get(MemoryItem, entries[0].memory_node_id)
    await db.refresh(canonical)
    assert set(await memory_urls(canonical.id)) == {entry.uri for entry in entries}
    assert b"Personal synthetic note" in (await service.get_item(canonical.id, agent_id=ctx.agent_id))[1]
    assert canonical.access_count == 2
    assert len(list(await db.scalars(select(MemoryUsage).where(MemoryUsage.item_id == canonical.id)))) == 1
    await db.refresh(finding)
    assert finding.status == "applied"


@pytest.mark.asyncio
async def test_url_uniqueness_primary_membership_and_task_history(console_catalogue, db):
    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://linked.txt", "Synthetic reference")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == "console://linked.txt"))
    node_id = entry.memory_node_id
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(MemoryURL(memory_node_id=node_id, url=entry.uri))
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(text("UPDATE memory_items SET primary_url='console://missing.txt' WHERE id=:node"), {"node": node_id})
            await db.execute(text("SET CONSTRAINTS fk_memory_items_primary_url IMMEDIATE"))
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(MemoryURL(memory_node_id=node_id, url="  "))
            await db.flush()
    task_id = await create_memory_task(db, ctx.agent_id)
    await service.get_item(node_id, agent_id=ctx.agent_id, task_id=task_id, record_llm_access=True)
    await db.flush()
    usage = await db.scalar(select(MemoryUsage).where(MemoryUsage.item_id == node_id))
    assert usage.task_id == task_id
    await db.execute(text("DELETE FROM tasks WHERE id=:task"), {"task": task_id})
    await db.refresh(usage)
    assert usage.task_id is None and usage.item_id == node_id
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(MemoryUsage(item_id=node_id, agent_id=ctx.agent_id, task_id=uuid4(), access_kind="read"))
            await db.flush()


@pytest.mark.asyncio
async def test_equal_attachments_merge_within_parent_and_preserve_live_access(db, agents, memory_storage, monkeypatch):
    from app.memory import document_attachment_service as attachments
    from .test_document_structure import document, png

    owner, peer = agents
    parent = await document(owner, "Synthetic attachment album")
    children = []
    for name in ("first.png", "second.png"):
        attachment = await attachments.add_document_attachment_bytes(
            parent.id, actor_agent_id=owner.id, name=name, media_type="image/png", content=png(),
        )
        children.append(await db.get(DocumentAttachment, attachment.id))
    node_ids = [row.memory_item_id for row in children]
    nodes = [await db.get(MemoryItem, identity) for identity in node_ids]
    from app.memory.attachment_description import write_attachment_description
    for node, description in zip(nodes, ("First synthetic description", "Second synthetic description")):
        await write_attachment_description(node, description, agent_id=owner.id)
    assert nodes[0].file_sha256 == nodes[1].file_sha256
    assert nodes[0].file_size_bytes == len(png()) and nodes[0].file_media_type == "image/png"
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "automatic")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    await maintenance.detect_for_item(min(node_ids, key=str))
    for row in children:
        await db.refresh(row)
    assert children[0].memory_item_id == children[1].memory_item_id
    canonical_id = children[0].memory_item_id
    assert len(await memory_urls(canonical_id)) == 2
    assert b"First synthetic description" in (await service.get_item(canonical_id, agent_id=owner.id))[1]
    assert b"Second synthetic description" in (await service.get_item(canonical_id, agent_id=owner.id))[1]
    await attachments.delete_document_attachment(parent.id, children[0].id, actor_agent_id=owner.id)
    await service.get_item(canonical_id, agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(canonical_id, agent_id=peer.id)
    await attachments.delete_document_attachment(parent.id, children[1].id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(canonical_id, agent_id=owner.id)
    payloads = [path for path in memory_storage.rglob("*") if path.is_file() and path.stat().st_size]
    await service.forget_item(parent.id, actor_agent_id=owner.id)
    assert payloads and all(not path.exists() for path in payloads)


@pytest.mark.asyncio
async def test_reference_upgrade_preserves_locations_and_orphan_audit(console_catalogue, db):
    from core.dbadmin import SchemaTransitionSet, SchemaObjectTransition
    from app.memory.file_attributes_migration import (
        needs_reference_preparation, prepare_references, references_prepared,
        needs_file_attributes, backfill_file_attributes, attributes_backfilled,
    )

    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://legacy-attributes.txt", "Synthetic file")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == "console://legacy-attributes.txt"))
    node_id, entry_id = entry.memory_node_id, entry.id
    transition = SchemaTransitionSet(
        added_columns=frozenset({"memory_items.file_media_type", "memory_items.file_size_bytes"}),
        definitions=(SchemaObjectTransition("memory_urls", "uq_memory_urls_node_url", "index", None, "unique"),),
    )
    assert needs_reference_preparation(transition) and needs_file_attributes(transition)
    assert not needs_reference_preparation(SchemaTransitionSet())
    assert not needs_file_attributes(SchemaTransitionSet())
    valid_task = await create_memory_task(db, ctx.agent_id)
    orphan_task, usage_id, duplicate_url_id = uuid4(), uuid4(), uuid4()
    async with db.begin_nested() as schema_savepoint:
        await db.execute(text("SET CONSTRAINTS fk_memory_items_primary_url IMMEDIATE"))
        await db.execute(text("ALTER TABLE memory_items DROP CONSTRAINT fk_memory_items_primary_url"))
        await db.execute(text("DROP INDEX uq_memory_urls_node_url"))
        await db.execute(text("ALTER TABLE memory_usages DROP CONSTRAINT memory_usages_task_id_fkey"))
        await db.execute(text("INSERT INTO memory_urls(id,memory_node_id,url) VALUES (:id,:node,:url)"),
                         {"id": duplicate_url_id, "node": node_id, "url": entry.uri})
        await db.execute(text("UPDATE file_catalog_entries SET memory_url_id=:url WHERE id=:entry"),
                         {"url": duplicate_url_id, "entry": entry_id})
        await db.execute(text("INSERT INTO memory_usages(id,item_id,agent_id,task_id,access_kind) VALUES (:id,:node,:agent,:task,'read')"),
                         {"id": usage_id, "node": node_id, "agent": ctx.agent_id, "task": orphan_task})
        db.add(MemoryUsage(item_id=node_id, agent_id=ctx.agent_id, task_id=valid_task, access_kind="search"))
        await db.flush()
        await db.execute(text("UPDATE memory_items SET file_media_type=NULL,file_size_bytes=NULL,metadata=metadata || jsonb_build_object('resource_media_type','text/plain','resource_size_bytes',14) WHERE id=:node"), {"node": node_id})
        assert not await references_prepared(db, transition)
        assert not await attributes_backfilled(db, transition)
        async with db.begin_nested() as rollback:
            await prepare_references(db, transition)
            await backfill_file_attributes(db, transition)
            assert await references_prepared(db, transition) and await attributes_backfilled(db, transition)
            await rollback.rollback()
        assert not await references_prepared(db, transition)
        for _ in range(2):
            await prepare_references(db, transition)
            await backfill_file_attributes(db, transition)
            assert await references_prepared(db, transition) and await attributes_backfilled(db, transition)
        assert await db.scalar(text("SELECT task_ref FROM galaris_migration.memory_usage_orphan_tasks WHERE id=:usage"), {"usage": usage_id}) == orphan_task
        await db.execute(text("ALTER TABLE galaris_migration.memory_usage_orphan_tasks RENAME COLUMN id TO usage_id"))
        assert not await references_prepared(db, transition)
        await prepare_references(db, transition)
        assert await references_prepared(db, transition)
        assert await db.scalar(text("SELECT task_ref FROM galaris_migration.memory_usage_orphan_tasks WHERE id=:usage"), {"usage": usage_id}) == orphan_task
        assert await db.scalar(text("SELECT task_id FROM memory_usages WHERE id=:usage"), {"usage": usage_id}) is None
        assert await db.scalar(select(MemoryUsage.task_id).where(MemoryUsage.access_kind == "search")) == valid_task
        assert len(await memory_urls(node_id)) == 1
        assert await db.scalar(text("SELECT location.memory_node_id FROM file_catalog_entries entry JOIN memory_urls location ON location.id=entry.memory_url_id WHERE entry.id=:entry"), {"entry": entry_id}) == node_id
        await schema_savepoint.rollback()


@pytest.mark.asyncio
async def test_failed_merge_commit_keeps_sources_and_cleans_new_payload(console_catalogue, db, memory_storage, monkeypatch):
    ctx, _transport, _connection, _peer = console_catalogue
    for uri in ("console://rollback-a.txt", "console://rollback-b.txt"):
        await resource_service.resource_write_text(ctx, uri, "Synthetic identical bytes")
    await acquire_fingerprints(db, maintain=False)
    entries = list(await db.scalars(select(FileCatalogEntry).order_by(FileCatalogEntry.uri)))
    identities = [entry.memory_node_id for entry in entries]
    for index, identity in enumerate(identities):
        await service.update_item(identity, MemoryItemUpdate(payload=MemoryPayload(text=f"<p>Synthetic note {index}</p>")), actor_agent_id=ctx.agent_id)
    monkeypatch.setattr(runtime_settings, "MEMORY_DUPLICATE_MODE", "manual")
    monkeypatch.setattr(runtime_settings, "MEMORY_CONTRADICTION_MODE", "off")
    monkeypatch.setattr(runtime_settings, "MEMORY_AGING_MODE", "off")
    finding_id, = await maintenance.detect_for_item(min(identities, key=str))
    before = {path for path in memory_storage.rglob("*") if path.is_file()}

    async def failed_commit():
        raise RuntimeError("Synthetic database commit failure")

    with monkeypatch.context() as failure:
        failure.setattr(db, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="Synthetic database commit failure"):
            await maintenance.apply_finding(finding_id, canonical_item_id=None)
    await db.rollback()
    assert {path for path in memory_storage.rglob("*") if path.is_file()} == before
    assert len(list(await db.scalars(select(MemoryItem).where(MemoryItem.id.in_(identities))))) == 2
    assert all([len(await memory_urls(identity)) == 1 for identity in identities])
    assert (await db.get(MemoryFinding, finding_id)).status == "pending"


@pytest.mark.asyncio
async def test_merging_equal_urls_preserves_both_catalogue_observations(console_catalogue, db):
    from app.memory import project_catalogue_entry, associate_memory_url, identify_catalogue_file

    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://same-url.txt", "Synthetic shared bytes")
    await acquire_fingerprints(db, maintain=False)
    first = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == "console://same-url.txt"))
    node_id, sha256 = first.memory_node_id, first.file_sha256
    # A previous binding may have observed the same URI before configuration changed.
    identity = uuid4()
    duplicate_id = await project_catalogue_entry(
        identity=identity, agent_id=ctx.agent_id, item_id=None, title="Synthetic retained location",
        uri=first.uri, directory=False, description="", notes="",
    )
    location = await associate_memory_url(duplicate_id, first.uri)
    second = FileCatalogEntry(
        id=identity, agent_id=ctx.agent_id, connection_id=first.connection_id,
        binding_stamp="synthetic-retained-binding", runtime=first.runtime,
        uri=first.uri, uri_key=first.uri_key, descriptor=dict(first.descriptor),
        memory_url=location, operation_started_at=first.operation_started_at,
        last_seen_at=first.last_seen_at, file_sha256=sha256,
    )
    db.add(second)
    await identify_catalogue_file(duplicate_id, ctx.agent_id, sha256)
    await db.commit()
    await maintain_file_duplicates(db)
    for entry in (first, second):
        await db.refresh(entry)
    assert first.memory_url_id == second.memory_url_id
    assert first.memory_node_id == second.memory_node_id == node_id
    assert await memory_urls(node_id) == [first.uri]
