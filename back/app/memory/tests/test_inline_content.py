from __future__ import annotations
from app.memory.tests.document_fixtures import finish_document_deletion
from app.document import resource_service as documents
from app.document.schemas import DocumentPayload, DocumentUpdate
from app.document.schemas import DocumentItemCreate
from app.memory.tests.document_fixtures import create_document_reference, edit_document_reference, edit_document_summary
"""Preserve native text bytes, history and transactions when moving into SQL."""

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.dbadmin import SchemaTransitionSet
from app.memory import service
from app.memory.content_migration import inline_content_complete, migrate_inline_content, needs_inline_content
from app.memory.models import MemoryItem, MemoryRevision
from app.document import Document, DocumentRevision, DocumentSummaryRevision
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload
from core.storage import get_storage


def test_inline_migration_follows_content_columns_only():
    assert needs_inline_content(SchemaTransitionSet(added_columns=frozenset({"documents.content"})))
    assert needs_inline_content(SchemaTransitionSet(added_tables=frozenset({"memory_items"})))
    assert not needs_inline_content(SchemaTransitionSet())
    assert not needs_inline_content(SchemaTransitionSet(added_columns=frozenset({"documents.title"})))


@pytest.mark.asyncio
async def test_current_text_and_history_commit_restore_and_forget_without_native_files(db, agents, memory_storage):
    owner, _reader = agents
    owner_id = owner.id
    item, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner_id,
        title="Synthetic inline document", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>First synthetic version.</p>")))
    identity = item.id
    assert await db.scalar(select(Document.content).where(Document.id == identity)) == "<p>First synthetic version.</p>"
    assert not [p for p in memory_storage.rglob("*") if p.is_file()]
    await edit_document_reference(identity, MemoryItemUpdate(expected_revision=1,
        payload=MemoryPayload(text="<p>Second synthetic version.</p>")), actor_agent_id=owner_id)
    await edit_document_summary(identity, MemoryItemUpdate(expected_revision=1,
        payload=MemoryPayload(text="<p>Synthetic summary.</p>")), actor_agent_id=owner_id)
    db.expire_all()
    assert (await service.get_item(identity, agent_id=owner_id, revision=1))[1] == b"<p>First synthetic version.</p>"
    assert (await service.get_item(identity, agent_id=owner_id, memory_content=True))[1] == b"<p>Synthetic summary.</p>"
    assert (await service.get_item(identity, agent_id=owner_id, revision=2))[1] == b"<p>Second synthetic version.</p>"
    assert not [p for p in memory_storage.rglob("*") if p.is_file()]
    await documents.restore_document_content_revision(identity, 1, expected_revision=2, actor_agent_id=owner_id)
    assert (await service.get_item(identity, agent_id=owner_id))[1] == b"<p>First synthetic version.</p>"
    await finish_document_deletion(identity, actor_agent_id=owner_id)
    assert await db.scalar(text("SELECT content FROM documents WHERE id=:id"), {"id": identity}) == ""
    assert await db.scalar(text("SELECT content FROM memory_items WHERE id=:id"), {"id": identity}) == ""


@pytest.mark.asyncio
async def test_standalone_json_memory_keeps_its_exact_text_in_sql(db, agents, memory_storage):
    source = '{"approved":false, "note":null}\n'
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agents[0].id,
        title="Synthetic native JSON", content_type="json", media_type="application/json",
        payload=MemoryPayload(text=source)))
    assert await db.scalar(select(MemoryItem.memory_content).where(MemoryItem.id == item.id)) == source
    assert (await service.get_item(item.id, agent_id=agents[0].id))[1] == source.encode()
    assert not [path for path in memory_storage.rglob("*") if path.is_file()]


@pytest.mark.asyncio
async def test_migration_copies_all_owners_exactly_and_retains_sources_on_replay(db, agents, memory_storage, monkeypatch):
    from core import settings
    monkeypatch.setattr(type(settings), "GALARIS_MEMORY_ROOT", str(memory_storage))
    await db.execute(text("DROP TABLE IF EXISTS galaris_migration.memory_text_contents"))
    owner, _reader = agents
    payload = "<p>Invented café 🧪</p>\r\n".encode()
    storage = get_storage()
    ref = await storage.create(payload)
    item = MemoryItem(id=uuid4(), node_kind="memory", owner_agent_id=owner.id,
        title="Synthetic legacy document", provider_code="native", resource_id=ref,
        content_type="text", media_type="text/html", content_hash=sha256(payload).hexdigest(),
        size_bytes=len(payload), search_text="Invented", keywords=[], metadata_={})
    db.add(item)
    await db.flush()
    item.memory_resource_id = ref
    item.memory_content = None
    item.memory_content_hash = sha256(payload).hexdigest()
    db.add(MemoryRevision(item_id=item.id, revision=1, provider_code="native", resource_id=ref,
        content_hash=sha256(payload).hexdigest(), content_type="text", media_type="text/html",
        title=item.title, keywords=[], metadata_={}))
    db.add(Document(id=item.id, owner_agent_id=owner.id, title=item.title, provider_code="native", resource_id=ref,
        content=None, content_hash=sha256(payload).hexdigest(), summary_provider_code="native", summary_resource_id=ref,
        summary_content=None, summary_content_hash=sha256(payload).hexdigest()))
    await db.flush()
    db.add(DocumentRevision(document_id=item.id, revision=1, provider_code="native", resource_id=ref,
        content=None, content_hash=sha256(payload).hexdigest(), title=item.title, content_type="text", media_type="text/html"))
    db.add(DocumentSummaryRevision(document_id=item.id, revision=1, provider_code="native", resource_id=ref,
        content=None, content_hash=sha256(payload).hexdigest(), source_document_revision=1, keywords=[]))
    identity, owner_id = item.id, owner.id
    await db.commit()
    delta = SchemaTransitionSet(added_columns=frozenset({"documents.content"}))
    assert not await inline_content_complete(db, delta)
    await migrate_inline_content(db, delta)
    await db.commit()
    assert await inline_content_complete(db, delta)
    await migrate_inline_content(db, delta)
    await db.commit()
    assert await db.scalar(text("SELECT count(*) FROM galaris_migration.memory_text_contents")) == 5
    assert (memory_storage / ref[:2] / ref).read_bytes() == payload
    for table in ("memory_items", "documents", "memory_revisions", "document_revisions", "document_summary_revisions"):
        assert await db.scalar(text(f"SELECT convert_to(content, 'UTF8') FROM {table} WHERE resource_id=:ref"), {"ref": ref}) == payload
    await db.execute(text("UPDATE documents SET content='synthetic corruption' WHERE resource_id=:ref"), {"ref": ref})
    assert not await inline_content_complete(db, delta)
    await db.rollback()
    # A later legitimate revision must not make the immutable migration backup
    # overwrite new text or block a replay on another schema transition.
    await documents.update_item(identity, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(text="<p>New synthetic working version.</p>")), actor_agent_id=owner_id)
    assert await inline_content_complete(db, delta)
    await migrate_inline_content(db, delta)
    await db.commit()
    assert (await documents.get_item(identity, agent_id=owner_id))[1] == b"<p>New synthetic working version.</p>"


@pytest.mark.asyncio
async def test_failed_inline_write_rolls_back_content_and_history_together(db, agents, memory_storage, monkeypatch):
    owner_id = agents[0].id
    item, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner_id,
        title="Synthetic atomic document", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Retained synthetic version.</p>")))
    identity = item.id

    async def reject_commit():
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(db, "commit", reject_commit)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await edit_document_reference(identity, MemoryItemUpdate(expected_revision=1,
            payload=MemoryPayload(text="<p>Unpublished synthetic version.</p>")), actor_agent_id=owner_id)
    db.expire_all()
    current, payload, *_ = await service.get_item(identity, agent_id=owner_id)
    assert current.revision == 1
    assert payload == b"<p>Retained synthetic version.</p>"
    assert len((await documents.item_record(identity)).revisions) == 1
    assert not [path for path in memory_storage.rglob("*") if path.is_file()]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "checksum", "nul", "encoding"])
async def test_bad_source_aborts_without_overwriting_or_deleting_it(db, agents, memory_storage, monkeypatch, failure):
    from core import settings
    monkeypatch.setattr(type(settings), "GALARIS_MEMORY_ROOT", str(memory_storage))
    await db.execute(text("DROP TABLE IF EXISTS galaris_migration.memory_text_contents"))
    payload = {"nul": b"kept\x00payload", "encoding": b"\xff\xfe"}.get(failure, b"original synthetic payload")
    ref = await get_storage().create(payload)
    source = memory_storage / ref[:2] / ref
    item = MemoryItem(owner_agent_id=agents[0].id, node_kind="memory", provider_code="native",
        resource_id=ref, content_type="text", media_type="text/plain", title="Synthetic protected source",
        content_hash=sha256(payload).hexdigest(), size_bytes=len(payload), search_text="", keywords=[], metadata_={})
    db.add(item)
    await db.commit()
    if failure == "missing":
        source.unlink()
    elif failure == "checksum":
        source.write_bytes(b"changed synthetic source")
    before = source.read_bytes() if source.exists() else None
    with pytest.raises((ValueError, FileNotFoundError)):
        await migrate_inline_content(db, SchemaTransitionSet())
    await db.rollback()
    assert (source.read_bytes() if source.exists() else None) == before
    assert await db.scalar(text("SELECT content FROM memory_items WHERE resource_id=:ref"), {"ref": ref}) is None
