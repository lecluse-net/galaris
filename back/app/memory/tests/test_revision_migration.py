import pytest
from sqlalchemy import select, text

from app.memory import document_service, service
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
    created = await document_service.create_document(
        owner_agent_id=owner.id, title="Historical document",
        content="<p>Initial content.</p>", task_id=task.id,
    )
    document_id = created.id
    appended = await document_service.append_document(
        document_id, actor_agent_id=owner.id, task_id=task.id,
        content="<p>Added passage.</p>", expected_revision=1,
    )
    transitions = SchemaTransitionSet(removed_columns=frozenset({"memory_revisions.reason"}))
    # Reconstitute the old representation only in the isolated PostgreSQL test DB.
    await db.execute(text("ALTER TABLE memory_revisions ADD COLUMN reason text NOT NULL DEFAULT ''"))
    try:
        await db.execute(text(
            "UPDATE memory_revisions SET reason = :reason, document_append = false "
            "WHERE item_id = :item_id AND revision = :revision"
        ), {"reason": legacy_reason, "item_id": document_id, "revision": appended["revision"]})
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
    db.expire_all()
    result = await document_service.append_document(
        document_id, actor_agent_id=owner_id, task_id=task_id,
        content="<p>Added passage.</p>",
        expected_revision=1 if legacy_reason == "Document content appended" else 2,
    )
    is_retry = legacy_reason == "Document content appended"
    assert result["state"] == ("unchanged" if is_retry else "appended")
    assert result["revision"] == (2 if is_retry else 3)
    _, content, *_ = await service.get_item(document_id, agent_id=owner_id)
    assert content.count(b"Added passage.") == (1 if is_retry else 2)
    revisions = await service.list_document_content_revisions(document_id, actor_agent_id=owner_id)
    assert all("reason" not in revision.model_dump() for revision in revisions.items)
