"""Supported files become complete PDFs with canonical ownership and process compatibility."""

# Imported pytest fixtures are intentionally injected into test parameters.
# ruff: noqa: F811

import asyncio
from io import BytesIO
import json
from unittest.mock import AsyncMock
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest

from app.file_share import ResourceContext, materialize_resource, resource_create, resource_info
from app.file_share.mcp import file_to_pdf
from app.process import process_service
from app.process.bpmn import Flow, Node, Workflow
from app.process.native_definitions import create
from app.process.tests.test_native_bpmn import native as native, finish_run
from app.process.values import Variable
from app.tools.mcp_loader import McpToolContext, list_enabled_native_mcp_definitions
from core.document import convert_to_pdf


def image_bytes(format="PNG", *, multiple=False):
    output = BytesIO()
    with Image.new("RGB", (80, 40), "red") as first, Image.new("RGB", (80, 40), "blue") as second:
        first.save(output, format=format, **({"save_all": True, "append_images": [second]} if multiple else {}))
    return output.getvalue()


def pdf_bytes():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    writer.write(output)
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("format,multiple", [("PNG", False), ("JPEG", False), ("BMP", False), ("GIF", True), ("TIFF", True), ("WEBP", True)])
async def test_image_export_preserves_all_frames_and_source(tmp_path, format, multiple):
    source = tmp_path / ("Synthetic." + format.lower())
    content = image_bytes(format, multiple=multiple)
    source.write_bytes(content)
    result = await convert_to_pdf(source, source.name, "image/" + format.lower(), tmp_path / "output")
    reader = PdfReader(tmp_path / "output" / "export.pdf")
    assert len(reader.pages) == result.page_count == (2 if multiple else 1)
    assert all(float(page.mediabox.width) / float(page.mediabox.height) == 2 for page in reader.pages)
    assert source.read_bytes() == content


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [".docx", ".xlsx", ".odt", ".ods", ".odp", ".rtf"])
async def test_office_export_uses_real_libreoffice_and_keeps_all_printed_pages(tmp_path, suffix):
    from app.document.tests.test_document_thumbnails import _office_source

    source = tmp_path / ("Synthetic" + suffix)
    if suffix == ".rtf":
        source.write_bytes(b"{\\rtf1\\ansi Synthetic export 1200.\\page Second synthetic page.}")
    elif suffix == ".odp":
        namespace = "urn:oasis:names:tc:opendocument:xmlns:"
        with ZipFile(source, "w") as archive:
            archive.writestr("mimetype", "application/vnd.oasis.opendocument.presentation")
            archive.writestr("META-INF/manifest.xml", f'<manifest:manifest xmlns:manifest="{namespace}manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
            archive.writestr("content.xml", f'<office:document-content xmlns:office="{namespace}office:1.0" xmlns:draw="{namespace}drawing:1.0" xmlns:text="{namespace}text:1.0" xmlns:svg="{namespace}svg-compatible:1.0" office:version="1.2"><office:body><office:presentation><draw:page draw:name="Slide1"><draw:frame svg:width="20cm" svg:height="5cm"><draw:text-box><text:p>Synthetic export 1200.</text:p></draw:text-box></draw:frame></draw:page></office:presentation></office:body></office:document-content>')
    else:
        _office_source(source)
    before = source.read_bytes()
    result = await convert_to_pdf(source, source.name, "application/octet-stream", tmp_path / "output")
    reader = PdfReader(tmp_path / "output" / "export.pdf")
    assert len(reader.pages) == result.page_count
    assert "1200" in "\n".join(page.extract_text() for page in reader.pages)
    if suffix in {".docx", ".ods", ".rtf"}:
        assert result.page_count >= 2
    assert bool(result.warnings) == (suffix in {".xlsx", ".ods"})
    assert source.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("name,mime,content,expected", [
    ("notes.txt", "text/plain", "Café <script>literal</script>".encode(), "Café &lt;script&gt;literal&lt;/script&gt;"),
    ("notes.txt", "text/plain", "Café UTF16".encode("utf-16"), "Café UTF16"),
    ("notes.md", "text/markdown", b"# Synthetic heading\n\n**Total 1200**", "<h1>Synthetic heading</h1>"),
    ("document", "text/html", b"<h1>Synthetic HTML</h1>", "<h1>Synthetic HTML</h1>"),
    ("notes.json", "application/json", b'{"total":1200}', "1200"),
    ("notes.xml", "application/xml", b"<total>1200</total>", "&lt;total&gt;1200&lt;/total&gt;"),
    ("notes.csv", "text/csv", b"label,total\nSynthetic,1200", "Synthetic,1200"),
    ("drawing.svg", "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><rect width="80" height="40" fill="red"/></svg>', "data:image/svg+xml;base64,"),
])
async def test_textual_export_uses_static_renderer_and_validates_its_pdf(tmp_path, monkeypatch, name, mime, content, expected):
    import core.preview

    render = AsyncMock(return_value=pdf_bytes())
    monkeypatch.setattr(core.preview, "render_html_pdf", render)
    source = tmp_path / "original"
    source.write_bytes(content)
    result = await convert_to_pdf(source, name, mime, tmp_path / "output")
    assert expected in render.call_args.args[0]
    assert result.page_count == len(PdfReader(tmp_path / "output" / "export.pdf").pages) == 1
    assert result.warnings and source.read_bytes() == content


@pytest.mark.asyncio
async def test_existing_pdf_is_validated_and_copied_without_reencoding(tmp_path):
    source = tmp_path / "original"
    content = pdf_bytes()
    source.write_bytes(content)
    result = await convert_to_pdf(source, "Synthetic.pdf", "application/pdf", tmp_path / "output")
    assert result.page_count == 1 and (tmp_path / "output" / "export.pdf").read_bytes() == content


@pytest.mark.asyncio
@pytest.mark.parametrize("name,mime,content", [("archive.zip", "application/zip", b"PK\x03\x04broken"),
    ("movie.mp4", "video/mp4", b"synthetic unsupported binary"),
    ("broken.pdf", "application/pdf", b"%PDF-1.7\ncorrupted"),
    ("broken.txt", "text/plain", b"\x00\xff")])
async def test_unsupported_and_corrupt_sources_never_become_a_successful_pdf(tmp_path, name, mime, content):
    source = tmp_path / "original"
    source.write_bytes(content)
    with pytest.raises(ValueError):
        await convert_to_pdf(source, name, mime, tmp_path / "output")


@pytest.mark.asyncio
async def test_pdf_tool_is_available_in_conversation_and_feeds_a_pdf_constrained_process(db, native, tmp_path):
    from sqlalchemy import select, func
    from app.tools import RecoverableToolError
    from app.tools.mandatory_tools import sync_integrated_tool_connections
    from core.storage import StoredFile

    owner, other = native
    await sync_integrated_tool_connections(agent_id=owner.id)
    await db.commit()
    assert "file_to_pdf" in {item.name for item in await list_enabled_native_mcp_definitions(
        owner.id, runtime="internal", conversation_only=True)}
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    original = image_bytes()
    source = await resource_create(context, "file://", original, name="Synthetic.png")
    result = json.loads(await file_to_pdf(McpToolContext(agent_id=owner.id, runtime="internal"), source.uri, "file://"))
    info = await resource_info(context, result["uri"])
    assert info.media_type == "application/pdf" and result["source_uri"] == source.uri
    await materialize_resource(context, result["uri"], tmp_path / "result.pdf", max_bytes=64_000_000)
    assert len(PdfReader(tmp_path / "result.pdf").pages) == result["page_count"] == 1
    with pytest.raises(PermissionError):
        await resource_info(ResourceContext(agent_id=other.id, runtime="internal"), result["uri"])
    count = await db.scalar(select(func.count()).select_from(StoredFile))
    with pytest.raises(RecoverableToolError):
        await file_to_pdf(McpToolContext(agent_id=other.id, runtime="internal"), source.uri, "file://")
    assert await db.scalar(select(func.count()).select_from(StoredFile)) == count
    graph = Workflow(schema_version="galaris.bpmn/v2",
        variables=[Variable(name="document", type="File", nullable=False, mime_type="application/pdf")],
        nodes=[Node(id="start", kind="start", inputs=["document"]), Node(id="end", kind="end", outputs=["document"])],
        flows=[Flow(id="done", source="start", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic PDF admission", graph=graph)
    values = {"document": {"type": "File", "value": result["uri"]}}
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data=values)
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, launched.run_id)
    assert run.status == "success" and run.output == values
    await materialize_resource(context, source.uri, tmp_path / "source.png", max_bytes=64_000_000)
    assert (tmp_path / "source.png").read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("size,name,mime", [(64_000_001, "Synthetic.png", "image/png"), (8_000_001, "Synthetic.txt", "text/plain")])
async def test_pdf_export_checks_source_budgets_before_conversion(tmp_path, size, name, mime):
    source = tmp_path / "original"
    with source.open("wb") as stream:
        stream.truncate(size)
    with pytest.raises(ValueError, match="input limit|export limit"):
        await convert_to_pdf(source, name, mime, tmp_path / "output")
    assert not (tmp_path / "output" / "export.pdf").exists()


@pytest.mark.asyncio
async def test_export_cancellation_drains_the_entire_converter_group(tmp_path, monkeypatch):
    from core.document import pdf_export

    entered, draining, reaped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Worker:
        pid, returncode = 12345, None
        async def communicate(self):
            entered.set()
            await asyncio.Event().wait()
        async def wait(self):
            draining.set()
            await reaped.wait()
            return self.returncode
    worker = Worker()
    monkeypatch.setattr(pdf_export.asyncio, "create_subprocess_exec", AsyncMock(return_value=worker))
    killed = []
    def kill_group(pid, signal):
        killed.append(pid)
        worker.returncode = -9
    monkeypatch.setattr(pdf_export.os, "killpg", kill_group)
    source = tmp_path / "original"
    source.write_bytes(b"synthetic binary")
    task = asyncio.create_task(convert_to_pdf(source, "Synthetic.bin", "application/octet-stream", tmp_path / "output"))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.wait_for(draining.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and killed == [12345]
    reaped.set()
    with pytest.raises(asyncio.CancelledError):
        await task
