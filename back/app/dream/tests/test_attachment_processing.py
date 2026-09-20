"""Media routing and document extraction preserve content without unwanted inference."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import pytest

from app.dream import attachment_processing as processing
from app.dream.attachment_extract import extract
from app.memory.facade import AttachmentAnalysisSource


def source(name="notes.txt", mime="text/plain"):
    return AttachmentAnalysisSource(uuid4(), uuid4(), uuid4(), 1, None, None, name, mime, 0)


@pytest.mark.asyncio
async def test_options_do_not_analyze_each_others_documents(tmp_path, monkeypatch):
    path = tmp_path / "document"
    path.write_text("All relevant details", encoding="utf-8")
    summary = AsyncMock(return_value="Summary")
    native = AsyncMock(return_value="Scanned page")
    monkeypatch.setattr(processing, "summarize_text", summary)
    monkeypatch.setattr(processing, "describe_document", native)
    assert await processing.analyze_attachment("document", path, source()) is None
    summary.assert_not_awaited()
    native.assert_not_awaited()
    assert await processing.analyze_attachment("text", path, source()) == "Summary"
    native.assert_not_awaited()
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    pdf = source("scan.pdf", "application/pdf")
    assert await processing.analyze_attachment("text", path, pdf) is None
    assert summary.await_count == 1
    assert await processing.analyze_attachment("document", path, pdf) == "Scanned page"
    native.assert_awaited_once()


def test_office_text_and_expansion_limits(tmp_path):
    path = tmp_path / "document.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<document><p><t>Budget 1200</t></p><p><t>Approved</t></p></document>')
    assert extract(path, path.name, "application/octet-stream") == "Budget 1200 Approved"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE doc [<!ENTITY x "untrusted">]><doc>&x;</doc>')
    with pytest.raises(ValueError, match="entities"):
        extract(path, path.name, "application/octet-stream")


def test_spreadsheet_resolves_shared_strings_in_their_cells(tmp_path):
    path = tmp_path / "budget.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", '<sst><si><t>Budget</t></si><si><t>Approved</t></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row><c r="A1" t="s"><v>1</v></c><c r="B1"><v>1200</v></c><c r="C1" t="s"><v>0</v></c></row></sheetData></worksheet>')
    assert "A1: Approved | B1: 1200 | C1: Budget" in extract(path, path.name, "application/octet-stream")


@pytest.mark.asyncio
async def test_long_text_covers_the_end_before_reducing(db, monkeypatch):
    llm = SimpleNamespace(code="local")
    inference = AsyncMock(return_value=SimpleNamespace(output="Short summary", cost=0.0))
    monkeypatch.setattr(processing.llm_service, "get_profile_llm_for_agent_id", AsyncMock(return_value=llm))
    monkeypatch.setattr(processing, "run_structured", inference)
    text = "a" * 40_000 + "IMPORTANT FINAL CONCLUSION"
    assert await processing.summarize_text(text, source()) == "Short summary"
    prompts = [call.kwargs["prompt"] for call in inference.await_args_list]
    assert any("IMPORTANT FINAL CONCLUSION" in prompt for prompt in prompts)
    assert prompts[-1].count("Short summary") == 3


@pytest.mark.asyncio
async def test_empty_video_transcript_keeps_item_unfilled(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    monkeypatch.setattr(processing, "normalize_for_transcription_chunks", AsyncMock(return_value=[]))
    with pytest.raises(ValueError, match="no transcribable audio"):
        await processing.analyze_attachment("video", path, replace(source(), media_type="video/mp4"))


@pytest.mark.asyncio
async def test_cancelled_conversion_kills_and_reaps_worker(tmp_path, monkeypatch):
    import asyncio
    process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=asyncio.CancelledError),
                              kill=lambda: None, wait=AsyncMock())
    from unittest.mock import Mock
    process.kill = Mock()
    monkeypatch.setattr(processing.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await processing.extract_attachment_text(tmp_path / "document", source())
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_application_composes_real_media_services(monkeypatch, tmp_path):
    from app import audio, image
    from app.dream import interface
    from modules import configure_dream_media

    vision = AsyncMock(return_value="Description")
    normalize = AsyncMock(return_value=[])
    monkeypatch.setattr(image, "describe_image", vision)
    monkeypatch.setattr(audio, "normalize_for_transcription_chunks_isolated", normalize)
    configure_dream_media()
    try:
        assert await interface.describe_image(b"image", "image/png", instruction="Describe", agent_id=None) == "Description"
        assert await interface.normalize_for_transcription_chunks(tmp_path / "video", tmp_path / "chunks") == []
        vision.assert_awaited_once()
        normalize.assert_awaited_once()
    finally:
        monkeypatch.undo()
        configure_dream_media()
