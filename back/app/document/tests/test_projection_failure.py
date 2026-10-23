"""Committed Documents survive outages in optional downstream projections."""

import pytest
from sqlalchemy import select, text
from app.document import resource_service as documents
from app.document.lifecycle import register_document_observer, unregister_document_observer
from app.document.schemas import DocumentItemCreate, DocumentUpdate, DocumentPayload
from app.memory import MemoryItem
from core.database import get_db


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "database"])
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_committed_document_survives_a_downstream_projection_failure(db, agents, memory_storage, operation, failure):
    owner = agents[0]
    owner_id = owner.id
    initial = DocumentItemCreate(owner_agent_id=owner_id, title="Synthetic projection outage",
        media_type="text/html", payload=DocumentPayload(text="<p>Initial content</p>"))
    item = (await documents.create_item(initial))[0] if operation == "update" else None
    calls = []

    async def unavailable(identity, action):
        calls.append(identity)
        if failure == "database":
            await get_db().execute(text("SELECT 1 / 0"))
        raise RuntimeError("Synthetic downstream outage")

    register_document_observer("synthetic_projection_outage", unavailable)
    try:
        if operation == "create":
            saved, _ = await documents.create_item(initial)
            expected, revision = b"<p>Initial content</p>", 1
        else:
            saved = await documents.update_item(item.id, DocumentUpdate(expected_revision=item.revision,
                payload=DocumentPayload(text="<p>Updated content</p>")), actor_agent_id=owner_id)
            expected, revision = b"<p>Updated content</p>", 2
    finally:
        unregister_document_observer("synthetic_projection_outage")
    assert calls and set(calls) == {saved.id}
    assert owner.id == owner_id
    loaded, content, access, *_ = await documents.get_item(saved.id, agent_id=owner_id)
    assert (content, loaded.revision, access.can_write) == (expected, revision, True)
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == saved.id)) is None
