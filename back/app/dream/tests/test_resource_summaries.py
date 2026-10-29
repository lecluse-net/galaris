"""Source-owned summaries stay small, current and independent of Memory."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.document import DocumentRevision, document_service, resource_service as documents
from app.document.schemas import DocumentPayload, DocumentUpdate
from app.document import resource_summaries as document_summaries
from app.dataset import service as datasets, resource_summaries as dataset_summaries
from app.dataset.models import DatasetRevision
from app.memory.models import MemoryItem
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from core.database import get_db
from core.params import runtime_settings
from core.util.resource_summary import change_percent, normalize_source, needs_summary


def body(kind, text):
    return f"<p>{text}</p>" if kind == "document" else json.dumps(text)


async def create(kind, owner, text):
    if kind == "document":
        return await document_service.create_document(owner_agent_id=owner.id, title="Synthetic source",
            content=body(kind, text), task_id=None)
    item = await datasets.create(owner.id, title="Synthetic source", content=body(kind, text))
    await get_db().commit()
    return item


async def write(kind, item, owner, text):
    if kind == "document":
        return await documents.update_item(item.id, DocumentUpdate(payload=DocumentPayload(text=body(kind, text)),
            expected_revision=item.revision), actor_agent_id=owner.id)
    result = await datasets.replace(item.id, owner.id, content=body(kind, text), expected_revision=item.revision)
    await get_db().commit()
    return result


def test_summary_policy_uses_strict_thresholds_and_ignores_presentation():
    from pydantic import ValidationError
    from app.dream.mechanisms.resource_summaries import ResourceSummary
    with pytest.raises(ValidationError):
        ResourceSummary(description=" ", keywords=[" "])
    assert not needs_summary("x" * 1000, summary_present=False, generated=False, baseline=None, min_chars=1000, threshold=25)
    assert needs_summary("x" * 1001, summary_present=False, generated=False, baseline=None, min_chars=1000, threshold=25)
    assert change_percent("a" * 1200, "a" * 900 + "b" * 300) == 25
    assert change_percent("a" * 1200, "a" * 100 + "b" + "a" * 998 + "b" + "a" * 100) < 1
    assert change_percent("a" * 1200, "a" * 100 + "b" + "a" * 1000 + "b" + "a" * 100) < 1
    assert not needs_summary("a" * 900 + "b" * 300, summary_present=True, generated=True,
        baseline="a" * 1200, min_chars=1000, threshold=25)
    assert normalize_source('<p><strong>Useful</strong> text</p>', "html") == normalize_source('<div>Useful text</div>', "html")
    assert normalize_source('{ "b": 2, "a": 1 }', "json") == normalize_source('{"a":1,"b":2}', "json")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
async def test_summary_generation_and_cumulative_changes_preserve_content_history(db, agents, memory_storage, kind):
    owner, _ = agents
    port = document_summaries if kind == "document" else dataset_summaries
    item = await create(kind, owner, "a" * 1200)
    identity = item.id
    assert item.summary_pending
    assert await db.get(MemoryItem, identity) is None
    assert await port.apply(f"{identity}:{item.lock_version}", "Synthetic resource description", ["synthetic", "reference"])
    await db.commit()
    assert item.revision == 1 and not item.summary_pending
    assert item.summary_generated
    baseline = item.summary_source_text
    item = await write(kind, item, owner, "a" * 960 + "b" * 240)
    assert not item.summary_pending
    assert item.summary_source_text == baseline
    item = await write(kind, item, owner, "a" * 840 + "b" * 360)
    assert item.summary_pending
    stale = f"{identity}:{item.lock_version}"
    item = await write(kind, item, owner, "a" * 800 + "b" * 400)
    assert not await port.apply(stale, "Stale result must not overwrite current metadata", ["stale"])
    assert item.summary_pending and item.keywords == ["synthetic", "reference"]
    assert await port.apply(f"{identity}:{item.lock_version}", "Current description", ["current"])
    await db.commit()
    assert not item.summary_pending and item.revision == 4
    model = DocumentRevision if kind == "document" else DatasetRevision
    fk = model.document_id if kind == "document" else model.dataset_id
    assert await db.scalar(select(func.count()).select_from(model).where(fk == identity)) == 4
    assert await db.get(MemoryItem, identity) is None
    item = await write(kind, item, owner, "small again")
    assert not item.summary_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
async def test_small_resources_and_manual_summaries_do_not_trigger_dream(db, agents, memory_storage, kind):
    owner, other = agents
    item = await create(kind, owner, "small")
    assert not item.summary_pending
    item = await write(kind, item, owner, "a" * 1500)
    assert item.summary_pending
    if kind == "document":
        edit = DocumentUpdate(payload=DocumentPayload(text="<p>Manual source description.</p>"),
            keywords=["manual"], expected_lock_version=item.lock_version)
        with pytest.raises(documents.DocumentPermissionError):
            await documents.update_summary(item.id, edit, actor_agent_id=other.id)
        await documents.update_summary(item.id, edit, actor_agent_id=owner.id)
    else:
        with pytest.raises(datasets.DatasetNotFoundError):
            await datasets.metadata(item.id, other.id, expected_lock_version=item.lock_version,
                values={"summary_content": "Denied"})
        await datasets.metadata(item.id, owner.id, expected_lock_version=item.lock_version,
            values={"summary_content": "Manual source description.", "keywords": ["manual"]})
        await db.commit()
    assert not item.summary_pending and not item.summary_generated
    item = await write(kind, item, owner, "b" * 1500)
    assert not item.summary_pending and item.keywords == ["manual"]


@pytest.mark.asyncio
async def test_dream_reads_every_source_part_and_rejects_a_late_manual_edit(db, agents, memory_storage, monkeypatch):
    from app.dream.mechanisms import resource_summaries as mechanism
    from app.dream.contracts import DreamClaim
    from uuid import uuid4

    item = await create("document", agents[0], "a" * 48_000 + "Synthetic important final section")
    run = mechanism.document_summary_mechanism
    inference = AsyncMock(return_value=SimpleNamespace(output=mechanism.ResourceSummary(
        description="Synthetic reusable reference", keywords=["reference"]), cost=0.0))
    monkeypatch.setattr(mechanism, "run_structured", inference)
    monkeypatch.setattr(mechanism.llm_service, "get_profile_llm_for_agent_id", AsyncMock(return_value=SimpleNamespace()))
    claim = DreamClaim(receipt_id=uuid4(), lease_token=uuid4(), subject_kind="document",
        subject_id=f"{item.id}:{item.lock_version}", attempts=1, prepared_payload=None)
    prepared = await run.prepare(claim)
    assert any("Synthetic important final section" in call.kwargs["prompt"] for call in inference.await_args_list)
    await documents.update_summary(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Human description.</p>")),
        actor_agent_id=agents[0].id)
    assert await run.apply(claim, prepared.payload) == 0
    assert item.summary_content == "<p>Human description.</p>"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "dataset"])
async def test_dream_coalesces_pending_edits_and_rechecks_changed_policy(db, agents, memory_storage, monkeypatch, kind):
    from app.dream.mechanisms.resource_summaries import document_summary_mechanism, dataset_summary_mechanism, on_summary_policy_change
    owner = agents[0]
    item = await create(kind, owner, "a" * 600)
    assert not item.summary_pending
    monkeypatch.setattr(runtime_settings, "DREAM_RESOURCE_SUMMARY_MIN_CHARS", 500)
    await on_summary_policy_change("DREAM_RESOURCE_SUMMARY_MIN_CHARS", "500")
    await db.refresh(item)
    assert item.summary_pending
    item = await write(kind, item, owner, "a" * 650)
    item = await write(kind, item, owner, "a" * 700)
    mechanism = document_summary_mechanism if kind == "document" else dataset_summary_mechanism
    claim = await mechanism.claim_one()
    assert claim is not None and claim.subject_id == f"{item.id}:{item.lock_version}"
    assert await mechanism.claim_one() is None
