"""Dream fills empty attachment items during rest without overwriting acquired text."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select

from app.dream import scheduler, attachment_processing as processing
from app.dream.mechanisms.attachment_memory import AttachmentMemoryMechanism
from app.dream.models import DreamReceipt
from app.dream.registry import register_mechanism, reset_registry
from app.dream.service import store_prepared
from app.memory import document_attachment_service as attachments, service
from app.memory.facade import attachment_analysis_source, fill_attachment_description
from app.memory.models import DocumentAttachment, MemoryAutomationJob, MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.params import runtime_settings
from core.params.runtime_settings import RuntimeSettings


async def add_attachment(db, owner, kind):
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Dream source", node_kind="document",
        memory_type="working", media_type="text/html", payload=MemoryPayload(text="<p>Source</p>"),
    ))
    if kind == "image":
        output = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
        data, name, mime = output.getvalue(), "image.png", "image/png"
    elif kind == "document":
        writer, output = PdfWriter(), BytesIO()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        data, name, mime = output.getvalue(), "scan.pdf", "application/pdf"
    elif kind == "video":
        data, name, mime = b"video fixture", "video.mp4", "video/mp4"
    else:
        data, name, mime = b"The project launches on October 1.", "notes.txt", "text/plain"
    attachment = await attachments.add_document_attachment_bytes(
        document.id, actor_agent_id=owner.id, name=name, media_type=mime, content=data,
    )
    record = await db.get(DocumentAttachment, attachment.id)
    source = await attachment_analysis_source(record.memory_item_id)
    await db.commit()
    return source


@pytest.fixture
def inference(monkeypatch, tmp_path):
    text = AsyncMock(return_value=SimpleNamespace(output="Lancement prévu le 1er octobre.", cost=0.0))
    vision = AsyncMock(return_value="Une image bleue.")
    from fastapi.responses import JSONResponse
    document = AsyncMock(return_value=JSONResponse({"choices": [{"message": {"content": "Une page blanche."}}]}))
    monkeypatch.setattr(processing, "run_structured", text)
    monkeypatch.setattr(processing, "describe_image", vision)
    monkeypatch.setattr(processing, "proxy_chat_completion", document)
    monkeypatch.setattr(processing.llm_service, "get_profile_llm_for_agent_id", AsyncMock(return_value=SimpleNamespace(code="local")))
    monkeypatch.setattr(processing.llm_service, "get_document_llm", AsyncMock(return_value=SimpleNamespace(code="local")))
    monkeypatch.setattr(processing, "normalize_for_transcription_chunks", AsyncMock(return_value=[SimpleNamespace(path=tmp_path / "audio.mp3")]))
    monkeypatch.setattr(processing.transcription_service, "transcribe_audio_file", AsyncMock(return_value="The project launches on October 1."))
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler, "has_active_task_work", AsyncMock(return_value=False))
    monkeypatch.setattr(runtime_settings, "DREAM_ENABLED", True)
    reset_registry()
    yield text, vision, document
    reset_registry()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "document", "image", "video"])
async def test_rest_cycles_fill_one_empty_item_at_a_time(db, agents, memory_storage, inference, monkeypatch, kind):
    owner = agents[0]
    first = await add_attachment(db, owner, kind)
    second = await add_attachment(db, owner, kind)
    mechanism = AttachmentMemoryMechanism(kind)
    register_mechanism(mechanism)
    setting = f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"
    assert getattr(RuntimeSettings(), setting) is False
    monkeypatch.setattr(runtime_settings, setting, False)
    assert await scheduler.run_cycle() == 0
    monkeypatch.setattr(runtime_settings, setting, True)
    monkeypatch.setattr(scheduler, "has_active_task_work", AsyncMock(return_value=True))
    assert await scheduler.run_cycle() == 0
    monkeypatch.setattr(scheduler, "has_active_task_work", AsyncMock(return_value=False))
    assert await mechanism.count_pending() == 2
    assert await scheduler.run_cycle() == 1
    assert await mechanism.count_pending() == 1
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 0
    for source in (first, second):
        item, content, *_ = await service.get_item(source.item_id, agent_id=owner.id)
        assert content and item.revision == source.revision + 1
        assert await db.scalar(select(MemoryRevision.id).where(MemoryRevision.item_id == item.id))
        assert await db.scalar(select(MemoryAutomationJob.id).where(
            MemoryAutomationJob.kind == "semantic_index",
            MemoryAutomationJob.payload["item_id"].as_string() == str(item.id),
        ))
    calls = sum(mock.await_count for mock in inference)
    assert calls >= 2
    assert await scheduler.run_cycle() == 0
    assert sum(mock.await_count for mock in inference) == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["filled", "removed", "owner"])
async def test_analysis_never_overwrites_late_edits_or_removed_sources(db, agents, memory_storage, inference, monkeypatch, change):
    source = await add_attachment(db, agents[0], "image")
    mechanism = AttachmentMemoryMechanism("image")
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", True)
    claim = await mechanism.claim_one()
    prepared = await mechanism.prepare(claim)
    if change == "filled":
        assert await fill_attachment_description(source, "Texte ajouté pendant l’analyse.")
    elif change == "removed":
        await attachments.delete_document_attachment(source.document_id, source.attachment_id, actor_agent_id=agents[0].id)
    else:
        from app.memory.models import MemoryItem
        document = await db.get(MemoryItem, source.document_id)
        document.owner_agent_id = agents[1].id
        await db.commit()
    assert await mechanism.apply(claim, prepared.payload) == 0
    if change == "filled":
        content = (await service.get_item(source.item_id, agent_id=agents[0].id))[1]
        assert "pendant" in content.decode() and "bleue" not in content.decode()


@pytest.mark.asyncio
async def test_checkpoint_survives_disable_and_resume_without_new_inference(db, agents, memory_storage, inference, monkeypatch):
    source = await add_attachment(db, agents[0], "image")
    mechanism = AttachmentMemoryMechanism("image")
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", True)
    claim = await mechanism.claim_one()
    prepared = await mechanism.prepare(claim)
    await store_prepared(claim, prepared.payload, cost=prepared.cost)
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", False)
    import asyncio
    with pytest.raises(asyncio.CancelledError):
        await mechanism.apply(claim, prepared.payload)
    receipt = await db.get(DreamReceipt, claim.receipt_id)
    receipt.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", True)
    register_mechanism(mechanism)
    assert await scheduler.run_cycle() == 1
    inference[1].assert_awaited_once()
    assert (await service.get_item(source.item_id, agent_id=agents[0].id))[1]


@pytest.mark.asyncio
async def test_failure_does_not_block_the_next_attachment(db, agents, memory_storage, inference, monkeypatch):
    await add_attachment(db, agents[0], "image")
    await add_attachment(db, agents[0], "image")
    monkeypatch.setattr(runtime_settings, "DREAM_ATTACHMENT_IMAGE_ENABLED", True)
    inference[1].side_effect = [RuntimeError("Vision unavailable"), "Une image bleue."]
    mechanism = AttachmentMemoryMechanism("image")
    register_mechanism(mechanism)
    await scheduler.run_cycle()
    assert await mechanism.count_pending() == 1
    assert await scheduler.run_cycle() == 1
    db.expire_all()
    receipts = list(await db.scalars(select(DreamReceipt).where(DreamReceipt.mechanism_key == mechanism.key)))
    assert sorted(receipt.status for receipt in receipts) == ["retry", "success"]
