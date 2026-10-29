"""Document actions load only the payload and history they actually consume."""

import gc
import json
from pathlib import Path
import time
import tracemalloc
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, literal, select, update

from app.agent import AgentManagementScope
from app.document import resource_service as service
from app.document import document_attachment_service as attachments, document_service, item_sharing
from app.document import DocumentRevision
from app.document import Document
from app.document.schemas import DocumentItemCreate, DocumentPayload
from core.storage import get_storage
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["attachments", "download", "path", "sharing", "grant", "read", "edit", "append"])
async def test_document_actions_do_not_materialize_the_revision_corpus(db, agents, memory_storage, monkeypatch, operation):
    owner_id = agents[0].id
    reader_id = agents[1].id
    user = UserModel(email="document-performance@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner_id}))
    content = "<p>Original passage.</p>" + "<p>Synthetic content.</p>" * 500
    item, _ = await service.create_item(DocumentItemCreate(
        owner_agent_id=owner_id, title="Synthetic history", node_kind="document",
        payload=DocumentPayload(text=content), media_type="text/html",
    ))
    identity = item.id
    attachment = await attachments.add_document_attachment_bytes(
        identity, actor_agent_id=owner_id, name="synthetic.txt", media_type="text/plain", content=b"Attachment bytes",
    )
    table = DocumentRevision.__table__
    series = func.generate_series(2, 1001).table_valued("number").render_derived()
    expressions = [func.gen_random_uuid() if column.name == "id" else series.c.number if column.name == "revision" else column
                   for column in table.columns]
    await db.execute(table.insert().from_select([column.name for column in table.columns],
        select(*expressions).select_from(table.join(series, literal(True)))
        .where(table.c.document_id == identity, table.c.revision == 1)))
    await db.execute(update(Document).where(Document.id == identity).values(revision=1001))
    await db.commit()
    db.expunge_all()
    gc.collect()
    storage = get_storage("native")
    read = AsyncMock(wraps=storage.read)
    monkeypatch.setattr(storage, "read", read)
    loaded_revisions = []

    def loaded(entry, _context):
        loaded_revisions.append(entry.id)

    event.listen(DocumentRevision, "load", loaded)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        if operation == "attachments":
            result = await attachments.list_document_attachments(identity, actor_agent_id=owner_id)
            assert [entry.id for entry in result] == [attachment.id]
        elif operation == "download":
            entry, raw = await attachments.read_document_attachment(identity, attachment.id, actor_agent_id=owner_id)
            assert entry.id == attachment.id and raw == b"Attachment bytes"
        elif operation == "path":
            entry, path = await attachments.document_attachment_path(identity, attachment.id, actor_agent_id=owner_id)
            assert entry.id == attachment.id and path.is_file()
        elif operation == "sharing":
            result = await item_sharing.sharing(identity, scope)
            assert result.can_manage
        elif operation == "grant":
            result = await document_service.share_document(identity, owner_agent_id=owner_id, target_agent_id=reader_id,
                access="read", task_id=None)
            assert result["shared_with"] == [{"agent_id": reader_id, "access": "read"}]
        elif operation == "read":
            result = await document_service.read_document(identity, actor_agent_id=owner_id, task_id=None)
            assert "Original passage" in result["content"]
        elif operation == "edit":
            result = await document_service.edit_document(identity, actor_agent_id=owner_id, task_id=None,
                old_text="Original passage.", new_text="Updated passage.")
            assert result["state"] == "edited" and result["revision"] == 1002
        else:
            result = await document_service.append_document(identity, actor_agent_id=owner_id, task_id=None,
                content="<p>Appended passage.</p>", expected_revision=1001)
            assert result["state"] == "appended" and result["revision"] == 1002
        _, peak = tracemalloc.get_traced_memory()
    finally:
        elapsed = time.perf_counter() - started
        tracemalloc.stop()
        event.remove(DocumentRevision, "load", loaded)

    measurements = {"operation": operation, "revisions": 1001, "loaded_revisions": len(loaded_revisions),
        "parent_payload_reads": read.await_count, "python_peak_bytes": peak, "seconds": elapsed}
    destination = Path(__file__).resolve().parents[4] / f"artifacts/document-actions-{operation}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert len(loaded_revisions) <= 1, measurements
    if operation in {"attachments", "download", "path", "sharing", "grant"}:
        read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["title", "keywords", "metadata"])
async def test_metadata_edits_preserve_search_and_links_without_reparsing_content(db, agents, memory_storage, monkeypatch, field):
    from app.memory.models import MemoryLink
    from app.document.schemas import DocumentUpdate

    owner_id = agents[0].id
    target, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner_id, title="Appendix",
        node_kind="document", media_type="text/html", payload=DocumentPayload(text="<p>Appendix</p>")))
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner_id, title="Original report",
        node_kind="document", media_type="text/html", payload=DocumentPayload(text=f'<p>Searchable text.</p><a href="document://{target.id}">Appendix</a>')))
    from app.memory.document_projection import refresh
    await refresh(target.id)
    await refresh(item.id)
    await db.commit()
    identity, revision, search_text = item.id, item.revision, item.search_text
    link_id = await db.scalar(select(MemoryLink.id).where(MemoryLink.source_item_id == identity))
    assert link_id is not None
    updates = {"title": "Renamed report", "keywords": ["synthetic"], "metadata": {"document_path": "Synthetic folder"}}
    read = AsyncMock(wraps=get_storage().read)
    monkeypatch.setattr(get_storage(), "read", read)
    changed = await service.update_item(identity, DocumentUpdate(expected_revision=revision, **{field: updates[field]}),
        actor_agent_id=owner_id, include_revisions=False)
    assert changed.revision == revision and changed.search_text == search_text
    if field == "metadata":
        assert changed.metadata_["document_path"] == updates[field]["document_path"]
    else:
        assert getattr(changed, field) == updates[field]
    assert await db.scalar(select(MemoryLink.id).where(MemoryLink.source_item_id == identity)) == link_id
    read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('source,empty,archived,external', [
    (0, False, False, False), (1, False, False, False),     (3, False, False, False), (4, False, False, False), (0, True, False, False),
    (3, True, False, False), (3, False, True, False), (1, False, False, True),
], ids=['body', 'revision', 'summary', 'missing', 'empty-body',
        'empty-summary', 'archived-summary', 'external-body'])
async def test_native_pointer_sources_preserve_precedence_in_one_read(db, agents, source, empty, archived, external):
    from datetime import datetime, timezone
    from hashlib import sha256
    from uuid import uuid4
    from sqlalchemy import null
    from app.document.inline_content import read_inline_content
    from tests.sql_reads import measured_reads

    pointer = str(uuid4())
    values = [None if index < source else ('' if index == source and empty else f'Synthetic café 🧪 source {index}')
              for index in range(4)]
    if external:
        values[0] = 'Synthetic external body must be ignored'
    item = Document(owner_agent_id=agents[0].id, title='Synthetic pointer owner',
        provider_code='external' if external else 'native', resource_id=pointer, content=values[0],
        content_hash=sha256(b'synthetic').hexdigest(), summary_resource_id=pointer,
        summary_content=values[3] if values[3] is not None else null(),
        deleted_at=datetime.now(timezone.utc) if archived else None)
    db.add(item)
    await db.flush()
    db.add(DocumentRevision(document_id=item.id, revision=1, provider_code='native', resource_id=pointer,
        content=values[1], content_hash=sha256(b'synthetic').hexdigest(), title=item.title,
        content_type='text', media_type='text/html'))
    await db.flush()
    # The lookup must not publish an unrelated pending owner through autoflush.
    pending = Document(owner_agent_id=agents[0].id, title='Synthetic pending owner', provider_code='native',
        resource_id=str(uuid4()), content='Unpublished', content_hash=sha256(b'Unpublished').hexdigest())
    db.add(pending)
    expected = values[source].encode() if source < 4 else None
    async with measured_reads(db, 'document-native-pointer') as reads:
        assert await read_inline_content(pointer) == expected
    assert pending in db.new
    assert len(reads) <= 1


@pytest.mark.asyncio
async def test_native_pointer_keeps_unflushed_text_and_independent_commits(committed_database):
    from hashlib import sha256
    from uuid import uuid4
    from app.document.inline_content import read_inline_content
    from core.database.database import db_session_ctx
    from tests.sql_reads import measured_reads

    async with committed_database() as reader:
        token = db_session_ctx.set(reader)
        try:
            user = UserModel(email='synthetic-inline-reader@example.invalid', hashed_password='unused', is_active=True)
            reader.add(user)
            await reader.flush()
            user_id = user.id
            pointer = str(uuid4())
            item = Document(owner_user_id=user_id, title='Synthetic committed owner', provider_code='native',
                resource_id=pointer, content='Original café 🧪', content_hash=sha256(b'synthetic').hexdigest())
            reader.add(item)
            async with measured_reads(reader, 'pending-inline-owner') as reads:
                assert await read_inline_content(pointer) == 'Original café 🧪'.encode()
            assert not reads and item in reader.new
            await reader.commit()
            identity = item.id
            assert await read_inline_content(pointer) == 'Original café 🧪'.encode()
            async with committed_database() as writer:
                await writer.execute(update(Document).where(Document.id == identity).values(content='Independent update'))
                await writer.commit()
            assert item.content == 'Original café 🧪'  # The reader's ORM value is intentionally stale.
            assert await read_inline_content(pointer) == b'Independent update'
            item.content = 'Unflushed local text'
            async with measured_reads(reader, 'dirty-inline-owner') as reads:
                assert await read_inline_content(pointer) == b'Unflushed local text'
            assert not reads
            await reader.rollback()
            assert await read_inline_content(pointer) == b'Independent update'
            other_pointer = str(uuid4())
            async with committed_database() as writer:
                writer.add(Document(owner_user_id=user_id, title='Synthetic other owner', provider_code='native',
                    resource_id=other_pointer, content='Other pointer', content_hash=sha256(b'synthetic').hexdigest()))
                await writer.commit()

            async def read_in_own_session(target, expected):
                async with committed_database() as session:
                    context = db_session_ctx.set(session)
                    try:
                        for _ in range(3):
                            assert await read_inline_content(target) == expected
                    finally:
                        db_session_ctx.reset(context)

            import asyncio
            await asyncio.gather(read_in_own_session(pointer, b'Independent update'),
                                 read_in_own_session(other_pointer, b'Other pointer'))
        finally:
            db_session_ctx.reset(token)
