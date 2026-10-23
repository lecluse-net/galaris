from __future__ import annotations
from app.memory.tests.document_fixtures import finish_document_deletion
from app.document import resource_service as documents
"""Memory locations have one durable relation, independent of file format."""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select, text, delete

from app.file_share import resource_service
from app.file_share.models import FileCatalogEntry
from app.memory.models import MemoryItem, MemorySource
from .test_file_catalogue import console_catalogue as console_catalogue, acquire_fingerprints


@pytest.mark.asyncio
@pytest.mark.parametrize("name,content", [("opaque.bin", b"\x00\xffopaque"), ("report.txt", b"Synthetic report")])
async def test_file_urls_have_one_relation_and_node_byte_hash(console_catalogue, db, name, content):
    ctx, transport, _connection, _peer = console_catalogue
    transport.resolve_path(name).write_bytes(content)
    await resource_service.resource_info(ctx, f"console://{name}")
    await acquire_fingerprints(db)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == f"console://{name}"))
    node = await db.get(MemoryItem, entry.memory_node_id)
    assert node.file_sha256 == hashlib.sha256(content).hexdigest()
    assert node.primary_url == f"console://{name}"
    assert "resource_uri" not in node.metadata_ and "resource_uris" not in node.metadata_
    assert not await db.scalar(select(MemorySource.id).where(MemorySource.item_id == node.id, MemorySource.source_kind == "resource"))
    from app.memory.models import MemoryURL
    locations = list(await db.scalars(select(MemoryURL).where(MemoryURL.memory_node_id == node.id)))
    assert [location.url for location in locations] == [f"console://{name}"]
    assert entry.memory_url_id == locations[0].id


@pytest.mark.asyncio
async def test_legacy_url_backfill_survives_contraction_and_replay(console_catalogue, db):
    from core.dbadmin import SchemaTransitionSet
    from app.memory.models import MemoryURL
    from app.memory.url_migration import backfill_memory_urls, memory_urls_backfill_complete, needs_url_backfill
    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://legacy.txt", "Synthetic legacy file")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == "console://legacy.txt"))
    node_id = entry.memory_node_id
    transition = SchemaTransitionSet(removed_columns=frozenset({"file_catalog_entries.memory_item_id"}))
    assert needs_url_backfill(transition)
    assert needs_url_backfill(SchemaTransitionSet(added_tables=frozenset({"memory_urls"})))
    assert not needs_url_backfill(SchemaTransitionSet())
    await db.execute(text("ALTER TABLE file_catalog_entries ADD COLUMN memory_item_id uuid"))
    try:
        await db.execute(text("UPDATE file_catalog_entries SET memory_item_id=:node, memory_url_id=NULL WHERE id=:entry"),
                         {"node": node_id, "entry": entry.id})
        await db.execute(delete(MemoryURL).where(MemoryURL.memory_node_id == node_id))
        await db.execute(text("UPDATE memory_items SET primary_url=NULL, metadata=metadata || jsonb_build_object('resource_uri', CAST(:uri AS text)) WHERE id=:node"),
                         {"uri": entry.uri, "node": node_id})
        db.add(MemorySource(item_id=node_id, source_kind="resource", source_ref=entry.uri))
        await db.flush()
        assert not await memory_urls_backfill_complete(db, transition)
        async with db.begin_nested() as savepoint:
            await backfill_memory_urls(db, transition)
            assert await memory_urls_backfill_complete(db, transition)
            await savepoint.rollback()
        assert not await memory_urls_backfill_complete(db, transition)
        for _ in range(2):
            await backfill_memory_urls(db, transition)
            assert await memory_urls_backfill_complete(db, transition)
        rows = list(await db.scalars(select(MemoryURL).where(MemoryURL.memory_node_id == node_id)))
        assert [row.url for row in rows] == ["console://legacy.txt"]
        await db.execute(text("ALTER TABLE file_catalog_entries DROP COLUMN memory_item_id"))
        await db.refresh(entry)
        assert entry.memory_node_id == node_id and entry.memory_url_id == rows[0].id
        assert await memory_urls_backfill_complete(db, transition)
    except BaseException:
        await db.rollback()
        raise
    finally:
        await db.execute(text("ALTER TABLE file_catalog_entries DROP COLUMN IF EXISTS memory_item_id"))


@pytest.mark.asyncio
async def test_primary_url_is_stable_and_tracks_move_and_deletion(console_catalogue, db):
    from app.file_share.catalogue_resources import resources
    from app.memory import memory_urls
    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://z.txt", "Synthetic identical bytes")
    await acquire_fingerprints(db)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == "console://z.txt"))
    node_id = entry.memory_node_id
    first = await db.get(MemoryItem, node_id)
    assert first is not None
    # Savepoint commits keep PostgreSQL's transaction timestamp unchanged.
    # Represent distinct creation times to exercise the older node's primary URL.
    first.created_at -= timedelta(seconds=1)
    await db.flush()
    await resource_service.resource_write_text(ctx, "console://a.txt", "Synthetic identical bytes")
    await acquire_fingerprints(db)
    node = await db.get(MemoryItem, node_id)
    await db.refresh(node)
    assert node.primary_url == "console://z.txt"
    assert await memory_urls(node_id) == ["console://a.txt", "console://z.txt"]
    assert (await resources(node_id, ctx.agent_id))[0].uri == node.primary_url
    await resource_service.resource_move(ctx, "console://z.txt", "console://y.txt")
    await db.refresh(node)
    assert node.primary_url == "console://y.txt"
    assert await memory_urls(node_id) == ["console://a.txt", "console://y.txt"]
    await resource_service.resource_delete(ctx, "console://y.txt")
    await db.refresh(node)
    from app.memory import service
    assert await service.item_record(node_id) is not None
    assert node.primary_url == "console://a.txt"
    assert await memory_urls(node_id) == ["console://a.txt"]
    await resource_service.resource_delete(ctx, "console://a.txt")
    await db.refresh(node)
    assert node.primary_url is None and await memory_urls(node_id) == []
    assert await service.item_record(node_id) is None
    assert node.content == "" and node.memory_content == "" and node.search_text == ""
    from app.memory.models import MemoryRevision
    assert not list(await db.scalars(select(MemoryRevision.id).where(MemoryRevision.item_id == node_id)))
    await resource_service.resource_write_text(ctx, "console://a.txt", "A new synthetic occupant")
    replacement = await db.scalar(select(FileCatalogEntry).where(
        FileCatalogEntry.uri == "console://a.txt", FileCatalogEntry.present.is_(True),
    ))
    assert replacement.memory_node_id != node_id


@pytest.mark.asyncio
async def test_external_file_disappearance_forgets_projection_and_replay_cannot_revive_it(console_catalogue, db):
    from app.file_share import catalogue
    from app.file_share.indexing import refresh_known_tick
    from app.memory import service
    from app.memory.models import MemoryRevision
    ctx, transport, _connection, _peer = console_catalogue
    uri = "console://external.txt"
    await resource_service.resource_write_text(ctx, uri, "Synthetic external source")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == uri))
    identity = entry.memory_node_id
    transport.resolve_path("external.txt").unlink()
    await refresh_known_tick()
    assert not entry.present
    assert await service.item_record(identity) is None
    assert not list(await db.scalars(select(MemoryRevision.id).where(MemoryRevision.item_id == identity)))
    scope = await catalogue.observation_scope(ctx, uri)
    await catalogue.observe_deletion(scope, uri)
    await db.commit()
    assert await service.item_record(identity) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [PermissionError, TimeoutError])
async def test_unavailable_resource_does_not_prove_deletion(console_catalogue, db, monkeypatch, failure):
    from unittest.mock import AsyncMock
    from app.file_share.indexing import refresh_known_tick
    from app.memory import service

    ctx, _transport, _connection, _peer = console_catalogue
    uri = "console://temporarily-unavailable.txt"
    await resource_service.resource_write_text(ctx, uri, "Synthetic preserved source")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == uri))
    identity = entry.memory_node_id
    monkeypatch.setattr(resource_service, "resource_info", AsyncMock(side_effect=failure("Synthetic unavailable source")))
    await refresh_known_tick()
    assert entry.present and await service.item_record(identity) is not None


@pytest.mark.asyncio
async def test_rolled_back_catalogue_deletion_preserves_memory(console_catalogue, db):
    from app.file_share import catalogue
    from app.memory import service, memory_urls

    ctx, _transport, _connection, _peer = console_catalogue
    uri = "console://rollback.txt"
    await resource_service.resource_write_text(ctx, uri, "Synthetic transactional source")
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == uri))
    identity = entry.memory_node_id
    scope = await catalogue.observation_scope(ctx, uri)
    async with db.begin_nested() as savepoint:
        await catalogue.observe_deletion(scope, uri)
        assert await service.item_record(identity) is None
        await savepoint.rollback()
    assert await service.item_record(identity) is not None
    assert await memory_urls(identity) == [uri]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset", "file"])
async def test_native_resource_deletion_removes_linked_memory_and_preserves_other_locations(db, agents, memory_storage, tmp_path, kind):
    from app.memory import service, associate_memory_url, memory_urls
    from app.memory.schemas import MemoryItemCreate, MemoryPayload
    from app.file_share import ResourceContext
    from app.file_share.managed_files import persist_managed_file

    owner, _peer = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    if kind == "file":
        source = tmp_path / "source.txt"
        source.write_text("Synthetic source")
        uri = (await persist_managed_file(ctx, source, name="source.txt", media_type="text/plain")).uri
    else:
        created = await resource_service.resource_create(ctx, "data://" if kind == "dataset" else "document://",
            b'{"synthetic":true}' if kind == "dataset" else b"<p>Synthetic source</p>", name="Synthetic source")
        uri = created.uri
    linked, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Synthetic resource memory", payload=MemoryPayload(text="<p>Source conclusion</p>")))
    from app.memory.models import MemoryEmbeddingChunk
    db.add(MemoryEmbeddingChunk(item_id=linked.id, source_fingerprint="synthetic", model_key="synthetic",
        model_code="synthetic", dimensions=2, chunk_index=0, text="Synthetic source conclusion", embedding=[0.1, 0.2]))
    shared, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Synthetic multiple locations", payload=MemoryPayload(text="<p>Shared conclusion</p>")))
    for item in (linked, shared):
        await associate_memory_url(item.id, uri)
    other_uri = "https://example.com/synthetic-source"
    await associate_memory_url(shared.id, other_uri)
    await db.commit()
    if kind == "document":
        from uuid import UUID
        await finish_document_deletion(UUID(uri.removeprefix("document://")), actor_agent_id=owner.id)
    else:
        await resource_service.resource_delete(ctx, uri)
    assert await service.item_record(linked.id) is None
    assert await db.scalar(select(MemoryEmbeddingChunk.id).where(MemoryEmbeddingChunk.item_id == linked.id)) is None
    assert await service.item_record(shared.id) is not None
    assert await memory_urls(shared.id) == [other_uri]
