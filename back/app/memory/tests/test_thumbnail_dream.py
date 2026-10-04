"""Dream and Memory reuse durable derivatives without re-rendering or weakening ACLs."""

from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select

from app.dream.mechanisms.file_thumbnails import file_thumbnails_mechanism as mechanism
from app.dream import service as receipts
from app.dream.models import DreamReceipt
from app.memory import service, document_attachment_service, document_thumbnail_service
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.preview import thumbnails


@pytest.mark.asyncio
async def test_dream_attachment_thumbnail_survives_reopening_and_checks_access(agents, memory_storage, tmp_path, monkeypatch, db):
    owner, peer = agents
    monkeypatch.setattr(type(thumbnails.settings), 'GALARIS_THUMBNAIL_ROOT', str(tmp_path / 'cache'))
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title='Synthetic model', memory_type='working', node_kind='document',
        media_type='text/html', payload=MemoryPayload(text='<p>Model</p>'),
    ))
    attachment = await document_attachment_service.add_document_attachment_bytes(
        item.id, name='triangle.obj', media_type='model/obj',
        content=b'v -1 -1 0\nv 1 -1 0\nv 0 1 0\nf 1 2 3\n', actor_agent_id=owner.id,
    )
    png = thumbnails.encode(Image.new('RGB', (320, 220), 'blue'))
    renderer = AsyncMock(return_value=png)
    monkeypatch.setattr(document_thumbnail_service, 'render_model_thumbnail', renderer)
    assert await mechanism.count_pending() == 1
    claim = await mechanism.claim_one()
    assert claim is not None and claim.subject_kind == 'attachment_thumbnail'
    assert await mechanism.claim_one() is None
    result = await mechanism.apply(claim, claim.prepared_payload)
    assert result == 1
    # Replaying after a crash between derivative publication and receipt success reuses disk.
    assert await mechanism.apply(claim, claim.prepared_payload) == 1
    await receipts.mark_success(claim, result_count=result)
    assert await mechanism.count_pending() == 0
    read = document_thumbnail_service.read_or_schedule_document_attachment_thumbnail
    document_thumbnail_service._tasks.clear()
    assert await read(item.id, attachment.id, actor_agent_id=owner.id) == png
    assert await read(item.id, attachment.id, actor_agent_id=owner.id) == png
    renderer.assert_awaited_once()
    with pytest.raises(service.MemoryPermissionError):
        await read(item.id, attachment.id, actor_agent_id=peer.id)
    record = await db.scalar(select(DreamReceipt).where(DreamReceipt.id == claim.receipt_id))
    assert record.status == 'success' and record.cost == 0


@pytest.mark.asyncio
async def test_thumbnail_source_removed_after_claim_is_skipped(agents, memory_storage, db):
    owner, _ = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title='Synthetic source', memory_type='working', node_kind='document',
        media_type='text/html', payload=MemoryPayload(text='<p>Attachment</p>'),
    ))
    attachment = await document_attachment_service.add_document_attachment_bytes(
        item.id, name='notes.txt', media_type='text/plain', content=b'Synthetic notes', actor_agent_id=owner.id,
    )
    claim = await mechanism.claim_one()
    assert claim is not None
    await document_attachment_service.delete_document_attachment(item.id, attachment.id, actor_agent_id=owner.id)
    assert await mechanism.apply(claim, claim.prepared_payload) == 0
