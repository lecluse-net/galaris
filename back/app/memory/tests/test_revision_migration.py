from __future__ import annotations
from app.document import resource_service as documents
import pytest
from sqlalchemy import select, text

from app.memory import service
from app.document import document_service
from app.memory.dbadmin import (
    backfill_document_appends,
    document_append_backfill_complete,
    needs_document_append_backfill,
)
from app.memory.models import MemoryRevision
from app.task.models import Task, TaskStatus
from core.dbadmin import SchemaTransitionSet


def test_append_backfill_only_runs_when_revision_reasons_are_removed():
    assert not needs_document_append_backfill(SchemaTransitionSet())
    assert not needs_document_append_backfill(SchemaTransitionSet(
        removed_columns=frozenset({"memory_candidates.reason"}),
    ))
    assert needs_document_append_backfill(SchemaTransitionSet(
        removed_columns=frozenset({"memory_revisions.reason"}),
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_reason", ["Document content appended", "Document passage edited", ""])
async def test_legacy_revisions_keep_append_retry_semantics_after_reason_removal(
    db, agents, memory_storage, legacy_reason,
):
    owner, _ = agents
    task = Task(label="Document update", status=TaskStatus.EXEC, agent_id=owner.id)
    db.add(task)
    await db.flush()
    owner_id, task_id = owner.id, task.id
    from app.memory.models import MemoryItem
    from hashlib import sha256
    from uuid import uuid4
    document_id = uuid4()
    payload = "<p>Historical append.</p>"
    db.add(MemoryItem(id=document_id, owner_agent_id=owner.id, node_kind="memory",
        title="Synthetic historical source", provider_code="native", resource_id="", content=payload,
        content_hash=sha256(payload.encode()).hexdigest(), content_type="text", media_type="text/html"))
    await db.flush()
    db.add(MemoryRevision(item_id=document_id, revision=2, task_id=task.id, provider_code="native",
        resource_id="", content=payload, content_hash=sha256(payload.encode()).hexdigest(),
        content_type="text", media_type="text/html", title="Synthetic historical source"))
    await db.commit()
    transitions = SchemaTransitionSet(removed_columns=frozenset({"memory_revisions.reason"}))
    # Reconstitute the old representation only in the isolated PostgreSQL test DB.
    await db.execute(text("ALTER TABLE memory_revisions ADD COLUMN reason text NOT NULL DEFAULT ''"))
    try:
        await db.execute(text(
            "UPDATE memory_revisions SET reason = :reason, document_append = false "
            "WHERE item_id = :item_id AND revision = :revision"
        ), {"reason": legacy_reason, "item_id": document_id, "revision": 2})
        await db.commit()
        before = list((await db.execute(select(
            MemoryRevision.id, MemoryRevision.content_hash, MemoryRevision.resource_id,
        ).where(MemoryRevision.item_id == document_id).order_by(MemoryRevision.revision))).all())
        assert await document_append_backfill_complete(db, transitions) is (legacy_reason != "Document content appended")
        await backfill_document_appends(db, transitions)
        await backfill_document_appends(db, transitions)
        assert await document_append_backfill_complete(db, transitions)
        after = list((await db.execute(select(
            MemoryRevision.id, MemoryRevision.content_hash, MemoryRevision.resource_id,
        ).where(MemoryRevision.item_id == document_id).order_by(MemoryRevision.revision))).all())
        assert after == before
    finally:
        await db.execute(text("ALTER TABLE memory_revisions DROP COLUMN reason"))
        await db.commit()
    assert await document_append_backfill_complete(db, transitions)
    marker = await db.scalar(select(MemoryRevision.document_append).where(
        MemoryRevision.item_id == document_id, MemoryRevision.revision == 2))
    assert marker is (legacy_reason == "Document content appended")
