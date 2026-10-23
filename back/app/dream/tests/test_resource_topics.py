"""Synthetic end-to-end persistence contracts for resource Topic classification."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agent import AgentManagementScope
from app.dataset import service as datasets
from app.dream.mechanisms import resource_topic_classification as classification
from app.dream.models import DreamReceipt
from app.dream.service import mark_success, store_prepared
from app.dream import monitoring_service
from app.document import resource_service as memory
from app.memory.models import MemoryItem
from app.document import Document
from app.document.schemas import DocumentItemCreate as MemoryItemCreate, DocumentPayload as MemoryPayload
from core.storage import NativeFileStorage
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from app.topic import Topic, TopicClassification, service as topics
from app.topic.schemas import TopicCreate
from app.topic.schemas import TopicResourceAssignmentWrite
from core.params import runtime_settings
from core.user import UserModel


async def resource(db, owner, kind):
    if kind == "document":
        item, _ = await memory.create_item(
            MemoryItemCreate(
                owner_agent_id=owner.id,
                node_kind="document",
                title="Synthetic garden notes",
                payload=MemoryPayload(text="<p>Garden observations and seeds.</p>"),
            )
        )
        return await db.get(Document, item.id)
    return await datasets.create(
        owner.id, title="Synthetic garden inventory", content='[{"plant":"bean","quantity":3}]'
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
async def test_classification_checkpoint_preserves_content_and_lists_readable_resources(
    db,
    agents,
    memory_storage,
    monkeypatch,
    kind,
):
    owner, other = agents
    reader = UserModel(
        email=f"topic-reader-{uuid4().hex}@example.test", hashed_password="unused", is_active=True
    )
    db.add(reader)
    await db.flush()
    item = await resource(db, owner, kind)
    identity, content, revision = item.id, item.content, item.revision
    topic = await topics.create(TopicCreate(title="Gardening"))
    mechanism = getattr(classification, f"{kind}_topic_classification_mechanism")
    calls = []

    async def classify(**kwargs):
        calls.append(kwargs)
        assert kwargs["agent_id"] == owner.id
        assert "Garden" in kwargs["activity"] or "garden" in kwargs["activity"]
        assert ("seeds" if kind == "document" else '"quantity":3') in kwargs["activity"]
        return TopicClassification(action="reuse", topic_id=topic.id, confidence=0.95), 0.03

    monkeypatch.setattr(classification, "classify", classify)
    assert item.topic_id is None
    assert await mechanism.count_pending() == 1
    claim = await mechanism.claim_one()
    assert claim is not None
    assert await mechanism.claim_one() is None
    prepared = await mechanism.prepare(claim)
    await store_prepared(claim, prepared.payload, cost=prepared.cost)
    # Resume from the persisted decision; no second inference is necessary.
    receipt = await db.get(DreamReceipt, claim.receipt_id)
    await db.refresh(receipt)
    resumed = replace(claim, prepared_payload=receipt.prepared_payload)
    with monkeypatch.context() as unavailable_storage:
        unavailable_storage.setattr(
            NativeFileStorage, "read", AsyncMock(side_effect=OSError("temporary source outage"))
        )
        assert await mechanism.apply(resumed, resumed.prepared_payload) == 1
    await mark_success(claim, result_count=1)
    assert await mechanism.apply(resumed, resumed.prepared_payload) == 0
    assert len(calls) == 1
    await db.refresh(item)
    assert item.topic_id == topic.id
    assert (
        await db.execute(
            select(type(item).content, type(item).revision).where(type(item).id == identity)
        )
    ).one() == (content, revision)
    assert await mechanism.count_pending() == 0
    scope = AgentManagementScope(user_id=reader.id, agent_ids=frozenset({owner.id}))
    audit = await monitoring_service.get_topic_assignment_audit(
        topic_id=topic.id, subject_kind=kind, subject_id=identity, resource_scope=scope
    )
    assert audit.origin == "dream" and audit.dream_receipt_id == claim.receipt_id
    visible = await topics.get_content(topic.id, resource_scope=scope)
    assert [entry.id for entry in getattr(visible, f"{kind}s")] == [identity]
    page = await topics.list_page(skip=0, limit=50, search="Gardening", resource_scope=scope)
    assert [entry.id for entry in getattr(page.items[0], f"{kind}s")] == [identity]
    denied = await topics.get_content(
        topic.id,
        resource_scope=AgentManagementScope(user_id=reader.id, agent_ids=frozenset({other.id})),
    )
    assert getattr(denied, f"{kind}s") == []
    assert getattr(denied.summary, f"{kind}s") == 0

    # Manual assignment uses its own metadata lock and never creates a content revision.
    alternate = await topics.create(TopicCreate(title="Seeds"))
    from fastapi import HTTPException
    from app.topic import router as topic_router
    from app.dream import router as dream_router

    async def allowed_privilege(*args, **kwargs):
        return True

    async def current_scope():
        return scope

    monkeypatch.setattr(topic_router, "current_management_scope", current_scope)
    monkeypatch.setattr(topic_router, "check_privilege", allowed_privilege)
    monkeypatch.setattr(dream_router, "current_management_scope", current_scope)
    metadata_record = await db.get(Document, identity) if kind == "document" else item
    await db.refresh(metadata_record)
    edit = TopicResourceAssignmentWrite(
        topic_id=alternate.id,
        expected_topic_id=topic.id,
        expected_lock_version=metadata_record.lock_version,
    )
    changed = await topic_router.change_resource_topic(kind, identity, edit)
    await db.refresh(item)
    await db.refresh(metadata_record)
    assert item.topic_id == alternate.id and changed.lock_version == metadata_record.lock_version
    assert (
        await db.execute(
            select(type(item).content, type(item).revision).where(type(item).id == identity)
        )
    ).one() == (content, revision)
    with pytest.raises(HTTPException) as stale:
        await topic_router.change_resource_topic(kind, identity, edit)
    assert stale.value.status_code == 409
    audit = await dream_router.read_topic_assignment(alternate.id, kind, identity)
    assert audit.origin == "manual"
    # Returning to a previously inferred Topic remains an explicit manual choice.
    await topic_router.change_resource_topic(
        kind,
        identity,
        TopicResourceAssignmentWrite(
            topic_id=topic.id,
            expected_topic_id=alternate.id,
            expected_lock_version=metadata_record.lock_version,
        ),
    )
    audit = await dream_router.read_topic_assignment(topic.id, kind, identity)
    assert audit.origin == "manual"

    async def denied_privilege(*args, **kwargs):
        return False

    monkeypatch.setattr(topic_router, "check_privilege", denied_privilege)
    with pytest.raises(HTTPException) as denied_privilege_error:
        await topic_router.change_resource_topic(kind, identity, edit)
    assert denied_privilege_error.value.status_code == 403
    monkeypatch.setattr(topic_router, "check_privilege", allowed_privilege)
    scope = AgentManagementScope(user_id=reader.id, agent_ids=frozenset({other.id}))
    with pytest.raises(HTTPException) as denied_resource:
        await topic_router.change_resource_topic(kind, identity, edit)
    assert denied_resource.value.status_code in (403, 404)
    with pytest.raises(HTTPException) as denied_audit:
        await dream_router.read_topic_assignment(topic.id, kind, identity)
    assert denied_audit.value.status_code == 404

    target = await topics.create(TopicCreate(title="Plants"))
    await topics.merge(topic.id, target.id)
    await db.refresh(item)
    assert item.topic_id == target.id
    await topics.delete_topic(target.id)
    await db.refresh(item, attribute_names=["topic_id", "content", "revision"])
    assert item.topic_id is None
    assert (
        await db.execute(
            select(type(item).content, type(item).revision).where(type(item).id == identity)
        )
    ).one() == (content, revision)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
@pytest.mark.parametrize("change", ["edit", "delete", "assign"])
async def test_late_classification_cannot_overwrite_a_changed_resource(
    db,
    agents,
    memory_storage,
    kind,
    change,
):
    item = await resource(db, agents[0], kind)
    first = await topics.create(TopicCreate(title="Gardening"))
    second = await topics.create(TopicCreate(title="Plants"))
    mechanism = getattr(classification, f"{kind}_topic_classification_mechanism")
    claim = await mechanism.claim_one()
    assert claim is not None
    payload = {
        "decision": TopicClassification(action="reuse", topic_id=first.id).model_dump(mode="json"),
        "candidate_ids": [str(first.id)],
        "language": "en",
        "creation_mode": "auto",
    }
    if change == "edit":
        item.revision += 1
        if kind == "dataset":
            item.lock_version += 1
    elif change == "delete":
        item.soft_delete()
    else:
        item.topic_id = second.id
    await db.commit()
    assert await mechanism.apply(claim, payload) == 0
    assert await mechanism.count_pending() == int(change == "edit")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
@pytest.mark.parametrize("mode", ["forbid", "propose", "auto"])
async def test_resource_topic_creation_obeys_dream_policy(
    db, agents, memory_storage, monkeypatch, kind, mode
):
    item = await resource(db, agents[0], kind)
    mechanism = getattr(classification, f"{kind}_topic_classification_mechanism")
    monkeypatch.setattr(runtime_settings, "DREAM_TOPIC_CREATION_MODE", mode)

    async def classify(**kwargs):
        return TopicClassification(action="create", title="Gardening"), 0.01

    monkeypatch.setattr(classification, "classify", classify)
    claim = await mechanism.claim_one()
    prepared = await mechanism.prepare(claim)
    assert await mechanism.apply(claim, prepared.payload) == int(mode == "auto")
    await db.refresh(item)
    assert (item.topic_id is not None) == (mode == "auto")
    assert await db.scalar(select(func.count(Topic.id))) == int(mode == "auto")
