"""Manual and forced summaries preserve source content and reject stale inference."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.document import document_service, resource_service as service
from app.document.models import DocumentRevision
from app.document.schemas import DocumentGrantUpdate, DocumentItemCreate, DocumentPayload, DocumentUpdate
from app.document import summary_service as summaries
from core.user import HumanActor


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "data"])
async def test_forced_summary_replaces_manual_summary_even_for_short_documents(db, agents, memory_storage, monkeypatch, kind):
    owner, reader = agents
    content = '<p>Synthetic short source.</p>' if kind == 'text' else '{"synthetic": true}'
    item = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic source",
        content=content, task_id=None, document_type=kind)
    await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    manual = await summaries.edit_summary(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Manual summary.</p>"),
        keywords=["preserved"], expected_lock_version=item.lock_version), actor=owner.id)
    inference = AsyncMock(return_value=SimpleNamespace(output=summaries.GeneratedSummary(description="New <useful> description")))
    monkeypatch.setattr(summaries, 'run_structured', inference)
    monkeypatch.setattr(summaries.llm_service, 'get_profile_llm_for_agent_id', AsyncMock(return_value=SimpleNamespace()))
    with pytest.raises(service.DocumentPermissionError):
        await summaries.regenerate_summary(item.id, expected_lock_version=manual.lock_version, actor=reader.id)
    inference.assert_not_awaited()
    with pytest.raises(service.DocumentConflictError):
        await summaries.regenerate_summary(item.id, expected_lock_version=manual.lock_version - 1, actor=owner.id)
    inference.assert_not_awaited()
    result = await summaries.regenerate_summary(item.id, expected_lock_version=manual.lock_version, actor=owner.id)
    assert result.payload.text == '<p>New &lt;useful&gt; description</p>'
    assert result.keywords == ["preserved"]
    current, _ = await service.get_item_metadata(item.id, agent_id=owner.id)
    assert current.summary_generated and not current.summary_pending
    assert current.content == content and current.revision == 1
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == item.id)) == 1


@pytest.mark.asyncio
async def test_regeneration_covers_the_tail_and_preserves_a_late_manual_edit(db, agents, memory_storage, monkeypatch):
    owner = agents[0]
    item = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic long source",
        content='<p>' + 'a' * 48_000 + 'Important synthetic tail</p>', task_id=None)
    version = item.lock_version
    calls = []
    async def infer(**kwargs):
        calls.append(kwargs['prompt'])
        if len(calls) == 4:
            await summaries.edit_summary(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Concurrent human summary.</p>")), actor=owner.id)
        return SimpleNamespace(output=summaries.GeneratedSummary(description="Short synthetic description"))
    monkeypatch.setattr(summaries, 'run_structured', infer)
    monkeypatch.setattr(summaries.llm_service, 'get_profile_llm_for_agent_id', AsyncMock(return_value=SimpleNamespace()))
    with pytest.raises(service.DocumentConflictError):
        await summaries.regenerate_summary(item.id, expected_lock_version=version, actor=owner.id)
    assert any('Important synthetic tail' in prompt for prompt in calls)
    assert (await summaries.read_summary(item.id, actor=owner.id)).payload.text == '<p>Concurrent human summary.</p>'


@pytest.mark.asyncio
async def test_human_summary_writes_and_failed_regeneration_preserve_manual_text(db, agents, memory_storage, monkeypatch):
    owner = agents[0]
    item, _ = await service.create_item(DocumentItemCreate(title="Synthetic human source",
        node_kind="document", media_type="text/html", payload=DocumentPayload(text='<p>Short human source.</p>')),
        owner_user_id=owner.user_id)
    actor = HumanActor(owner.user_id)
    manual = await summaries.edit_summary(item.id, DocumentUpdate(payload=DocumentPayload(text="<p>Human summary.</p>"),
        expected_lock_version=item.lock_version), actor=actor)
    monkeypatch.setattr(summaries.llm_service, 'get_profile_llm_for_agent_id', AsyncMock(return_value=None))
    with pytest.raises(ValueError, match='No Dream model'):
        await summaries.regenerate_summary(item.id, expected_lock_version=manual.lock_version, actor=actor)
    assert (await summaries.read_summary(item.id, actor=actor)).payload.text == '<p>Human summary.</p>'
