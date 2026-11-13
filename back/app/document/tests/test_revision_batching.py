"""Immediate durable saves, quiet-period history, and safe background discovery."""

import pytest
from sqlalchemy import select

from app.document import automation, document_service, resource_service
from app.document.data import service as data_service
from app.document.models import DocumentAutomationJob, DocumentRevision
from app.document.revision_batching import job_key, seal_revision
from app.document.schemas import DocumentPayload, DocumentUpdate

from .revision_helpers import revision_clock as revision_clock


async def snapshots(db, identity):
    return list(await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == identity)
        .order_by(DocumentRevision.revision)))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "data"])
async def test_saves_are_immediate_but_only_quiet_content_enters_history(db, agents, memory_storage, revision_clock, kind):
    owner = agents[0]
    body = (lambda value: f'<p>{value}</p>') if kind == "text" else (lambda value: f'{{"text":"{value}"}}')
    item = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic draft",
        content=body("initial"), task_id=None, document_type=kind)
    for value in ("first edit", "second edit", "final edit"):
        revision_clock.advance(200)
        if kind == "text":
            item = await resource_service.update_item(item.id,
                DocumentUpdate(payload=DocumentPayload(text=body(value)), expected_revision=item.revision),
                actor_agent_id=owner.id, document_revision_author_agent_id=owner.id)
        else:
            item = await data_service.replace(item.id, owner.id, content=body(value), expected_revision=item.revision)
            await db.commit()
        assert item.content == body(value)
        _, content, _, _, _ = await resource_service.get_item(item.id, agent_id=owner.id, revision=item.revision)
        assert content.decode() == body(value)
        assert len(await snapshots(db, item.id)) == 1
        assert not await automation.process_next()
    stale_revision = item.revision - 1
    revision_clock.advance(299)
    assert not await automation.process_next()
    # Process/session-local timers are not needed; all intent is in PostgreSQL.
    db.expunge_all()
    revision_clock.advance(1)
    assert not await seal_revision(item.id, stale_revision)
    assert await automation.process_next()
    rows = await snapshots(db, item.id)
    assert [row.content for row in rows] == [body("initial"), body("final edit")]
    assert rows[-1].author_agent_id == owner.id
    assert not await automation.process_next()
    assert len(await snapshots(db, item.id)) == 2
    # Optimistic content tokens still reject readers from before the last save.
    with pytest.raises((resource_service.DocumentConflictError, data_service.DatasetConflictError)):
        if kind == "text":
            await resource_service.update_item(item.id,
                DocumentUpdate(payload=DocumentPayload(text=body("stale")), expected_revision=stale_revision),
                actor_agent_id=owner.id)
        else:
            await data_service.replace(item.id, owner.id, content=body("stale"), expected_revision=stale_revision)


@pytest.mark.asyncio
async def test_reverting_content_and_metadata_do_not_create_redundant_checkpoints(db, agents, memory_storage, revision_clock):
    owner = agents[0]
    item = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic source",
        content="<p>Original</p>", task_id=None)
    for text in ("Temporary", "Original"):
        item = await resource_service.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text=f"<p>{text}</p>")),
            actor_agent_id=owner.id)
    job = await db.scalar(select(DocumentAutomationJob).where(DocumentAutomationJob.idempotency_key == job_key(item.id)))
    deadline = job.available_at
    revision_clock.advance(100)
    item = await resource_service.update_item(item.id, DocumentUpdate(title="Synthetic renamed"), actor_agent_id=owner.id)
    await db.refresh(job)
    assert job.available_at == deadline
    await revision_clock.settle()
    assert len(await snapshots(db, item.id)) == 1


@pytest.mark.asyncio
async def test_new_edit_supersedes_an_already_claimed_checkpoint(db, agents, memory_storage, revision_clock):
    item = await document_service.create_document(owner_agent_id=agents[0].id, title="Synthetic source",
        content="<p>Original</p>", task_id=None)
    item = await resource_service.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>First</p>")), actor_agent_id=agents[0].id)
    stale_revision = item.revision
    revision_clock.advance()
    item = await resource_service.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Latest</p>")), actor_agent_id=agents[0].id)
    assert not await seal_revision(item.id, stale_revision)
    assert not await automation.process_next()
    await revision_clock.settle()
    assert [row.content for row in await snapshots(db, item.id)] == ["<p>Original</p>", "<p>Latest</p>"]


@pytest.mark.asyncio
async def test_checkpoint_failure_retries_without_losing_saved_content(db, agents, memory_storage, revision_clock, monkeypatch):
    from app.document import revision_batching

    item = await document_service.create_document(owner_agent_id=agents[0].id, title="Synthetic source",
        content="<p>Original</p>", task_id=None)
    item = await resource_service.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Latest</p>")), actor_agent_id=agents[0].id)
    revision_clock.advance()
    with monkeypatch.context() as failure:
        async def unavailable(*args):
            raise OSError("Synthetic checkpoint failure")
        failure.setattr(revision_batching, "seal_revision", unavailable)
        assert await automation.process_next()
    assert (await resource_service.item_record(item.id)).content == "<p>Latest</p>"
    job = await db.scalar(select(DocumentAutomationJob).where(DocumentAutomationJob.idempotency_key == job_key(item.id)))
    assert job.status == "pending" and "Synthetic checkpoint failure" in job.last_error
    revision_clock.advance(10)
    assert await automation.process_next()
    assert [row.content for row in await snapshots(db, item.id)] == ["<p>Original</p>", "<p>Latest</p>"]
