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
from app.memory import document_attachment_service as attachments, document_service, item_sharing, service
from app.memory.models import Document, MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.storage import get_storage
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
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner_id, title="Synthetic history", node_kind="document",
        payload=MemoryPayload(text=content), media_type="text/html",
    ))
    identity = item.id
    attachment = await attachments.add_document_attachment_bytes(
        identity, actor_agent_id=owner_id, name="synthetic.txt", media_type="text/plain", content=b"Attachment bytes",
    )
    table = MemoryRevision.__table__
    series = func.generate_series(2, 1001).table_valued("number").render_derived()
    expressions = [func.gen_random_uuid() if column.name == "id" else series.c.number if column.name == "revision" else column
                   for column in table.columns]
    await db.execute(table.insert().from_select([column.name for column in table.columns],
        select(*expressions).select_from(table.join(series, literal(True)))
        .where(table.c.item_id == identity, table.c.revision == 1)))
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

    event.listen(MemoryRevision, "load", loaded)
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
        event.remove(MemoryRevision, "load", loaded)

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
    from app.memory.schemas import MemoryItemUpdate

    owner_id = agents[0].id
    target, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner_id, title="Appendix",
        node_kind="document", media_type="text/html", payload=MemoryPayload(text="<p>Appendix</p>")))
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner_id, title="Original report",
        node_kind="document", media_type="text/html", payload=MemoryPayload(text=f'<p>Searchable text.</p><a href="document://{target.id}">Appendix</a>')))
    identity, revision, search_text = item.id, item.revision, item.search_text
    link_id = await db.scalar(select(MemoryLink.id).where(MemoryLink.source_item_id == identity))
    assert link_id is not None
    updates = {"title": "Renamed report", "keywords": ["synthetic"], "metadata": {"document_path": "Synthetic folder"}}
    read = AsyncMock(wraps=get_storage().read)
    monkeypatch.setattr(get_storage(), "read", read)
    changed = await service.update_item(identity, MemoryItemUpdate(expected_revision=revision, **{field: updates[field]}),
        actor_agent_id=owner_id, include_revisions=False)
    assert changed.revision == revision and changed.search_text == search_text
    if field == "metadata":
        assert changed.metadata_["document_path"] == updates[field]["document_path"]
    else:
        assert getattr(changed, field) == updates[field]
    assert await db.scalar(select(MemoryLink.id).where(MemoryLink.source_item_id == identity)) == link_id
    read.assert_not_awaited()
