"""Retiring summaries preserves their current value and content-only history."""

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import null, text

from app.document import Document, DocumentRevision, document_service, resource_service
from app.document.schemas import DocumentUpdate, DocumentPayload
from app.document.summary_retirement import needed, preserve_current, complete
from core.dbadmin import SchemaTransitionSet


@pytest.mark.asyncio
async def test_summary_retirement_preserves_current_inline_content_and_replays(db, agents, memory_storage):
    pointer = str(uuid4())
    item = Document(owner_agent_id=agents[0].id, title="Synthetic history retirement",
        provider_code="native", resource_id=str(uuid4()), content="<p>Canonical source.</p>",
        content_hash=sha256(b"<p>Canonical source.</p>").hexdigest(),
        summary_provider_code="native", summary_resource_id=pointer,
        summary_content=null(), summary_size_bytes=29)
    db.add(item)
    await db.flush()
    await db.execute(text("CREATE TABLE document_summary_revisions (id uuid, provider_code text, resource_id text, content text)"))
    await db.execute(text("INSERT INTO document_summary_revisions VALUES (:id,'native',:pointer,'<p>Current description.</p>')"), {"id":uuid4(), "pointer":pointer})
    delta = SchemaTransitionSet(removed_tables=frozenset({"document_summary_revisions"}))
    assert needed(delta) and not needed(SchemaTransitionSet())
    assert not await complete(db, delta)
    await preserve_current(db, delta)
    await preserve_current(db, delta)
    assert await complete(db, delta)
    await db.refresh(item)
    assert item.summary_content == "<p>Current description.</p>"
    await db.execute(text("DROP TABLE document_summary_revisions"))
    assert await complete(db, delta)


@pytest.mark.asyncio
async def test_metadata_edits_and_content_restore_keep_current_summary_and_keywords(db, agents, memory_storage):
    item = await document_service.create_document(owner_agent_id=agents[0].id, title="Synthetic content history",
        content="<p>First content.</p>", task_id=None)
    item = await resource_service.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Second content.</p>"),
        expected_revision=1), actor_agent_id=agents[0].id)
    await resource_service.update_summary(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Current description.</p>"),
        keywords=["current"], expected_lock_version=item.lock_version), actor_agent_id=agents[0].id)
    from app.document.summary_service import read_summary
    await resource_service.restore_document_content_revision(item.id, 1, expected_revision=2, actor_agent_id=agents[0].id)
    current = await read_summary(item.id, actor=agents[0].id)
    assert current.payload.text == "<p>Current description.</p>" and current.keywords == ["current"]
    assert "summary_document_revision" not in current.model_dump()
    assert "keywords" not in DocumentRevision.__table__.columns
    assert not (await db.scalar(text("SELECT to_regclass('public.document_summary_revisions')")))
