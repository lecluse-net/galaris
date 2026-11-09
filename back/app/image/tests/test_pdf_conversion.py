"""PDF inputs become real authorized images usable by an image-constrained Process."""

# Imported pytest fixtures are intentionally injected into test parameters.
# ruff: noqa: F811

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID

from fastmcp import FastMCP
from PIL import Image
import pytest

from app.file_share import ResourceContext, materialize_resource, resource_create, resource_info
from app.image import mcp as image_mcp
from app.process import process_service
from app.process.bpmn import Flow, Node, Workflow
from app.process.native_definitions import create
from app.process.tests.test_native_bpmn import native as native, finish_run
from app.process.values import Variable, ValueContractError
from app.tools import RecoverableToolError
from app.tools.mcp_loader import McpToolContext, add_galaris_tools
from core.document import render_pdf_page


def pdf_bytes() -> bytes:
    output = BytesIO()
    with Image.new("RGB", (80, 40), "red") as first, Image.new("RGB", (80, 40), "blue") as second:
        first.save(output, format="PDF", save_all=True, append_images=[second])
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("typed_values", [False, True])
@pytest.mark.parametrize("boundary", ["conversation", "task"])
async def test_pdf_image_is_a_real_page_and_launches_an_image_constrained_process(db, native, tmp_path, monkeypatch, typed_values, boundary):
    from sqlalchemy import select
    from app.connection import Connection
    from app.conversation.mcp import conversation_process_start
    from app.conversation.tests.test_process_admission import conversation, context, provider
    from app.tools.models import Tool
    from app.tools.mcp_loader import list_enabled_native_mcp_definitions

    owner, other = native
    image_tool = await db.scalar(select(Tool).where(Tool.code == "image"))
    connection = await db.scalar(select(Connection).where(Connection.agent_id == owner.id, Connection.tool_id == image_tool.id))
    if connection is None:
        db.add(Connection(agent_id=owner.id, tool_id=image_tool.id, active=True))
    else:
        connection.active = True
    image_tool.conversation_enabled = False
    await db.commit()
    assert "image_from_pdf" not in {item.name for item in await list_enabled_native_mcp_definitions(
        owner.id, runtime="internal", conversation_only=True)}
    image_tool.conversation_enabled = True
    await db.commit()
    assert "image_from_pdf" in {item.name for item in await list_enabled_native_mcp_definitions(
        owner.id, runtime="internal", conversation_only=True)}
    resource_ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    content = pdf_bytes()
    source = await resource_create(resource_ctx, "file://", content, name="Synthetic pages.pdf")
    graph = Workflow(schema_version="galaris.bpmn/v2",
        variables=[Variable(name="scan", type="File", nullable=False, mime_type="image/*")],
        nodes=[Node(id="start", kind="start", inputs=["scan"]), Node(id="end", kind="end", outputs=["scan"])],
        flows=[Flow(id="done", source="start", target="end")])
    definition = await create(actor_agent_id=owner.id, title="Synthetic image admission", graph=graph)
    with pytest.raises(ValueContractError, match="expected media type"):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
            input_data={"scan": {"type": "File", "value": source.uri}})
    turn, _ = await conversation(db, owner, f"Launch the workflow using physical page 2 of {source.uri} as an image.")
    result = await image_mcp.image_from_pdf(context(turn), source.uri, "file://", page=2)
    uri = result["uri"]
    assert result["media_type"] == "image/png" and result["page"] == 2 and result["page_count"] == 2
    assert result["source_uri"] == source.uri and uri != source.uri
    info = await resource_info(resource_ctx, uri)
    assert info.media_type == "image/png"
    await materialize_resource(resource_ctx, uri, tmp_path / "page.png", max_bytes=32_000_000)
    with Image.open(tmp_path / "page.png") as image:
        assert image.format == "PNG" and image.size == (160, 80)
        red, _, blue = image.convert("RGB").getpixel((80, 40))
        assert blue > 200 and red < 30
    with pytest.raises(PermissionError):
        await resource_info(ResourceContext(agent_id=other.id, runtime="internal"), uri)
    await materialize_resource(resource_ctx, source.uri, tmp_path / "source.pdf", max_bytes=64_000_000)
    assert (tmp_path / "source.pdf").read_bytes() == content
    inputs = {"scan": {"type": "File", "value": uri}}
    submitted = inputs if typed_values else {"scan": uri}
    if boundary == "conversation":
        provider(monkeypatch, [{"workflow_id": definition.code, "input": submitted, "typed_values": typed_values}])
        launched = await conversation_process_start(context(turn), workflow_id=definition.code,
            input=submitted, typed_values=typed_values)
        replay = await conversation_process_start(context(turn), workflow_id=definition.code,
            input=submitted, typed_values=typed_values)
        assert replay["run_id"] == launched["run_id"] and replay["created"] is False
    else:
        from app.process.mcp import process_start
        launched = await process_start(McpToolContext(agent_id=owner.id, runtime="internal"),
            workflow_id=definition.code, input=submitted, typed_values=typed_values)
    await process_service.process_start_jobs(engine_code="galaris")
    run = await finish_run(db, UUID(launched["run_id"]))
    assert run.status == "success" and run.output == inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [0, -1, True, 1.5, 3])
async def test_pdf_conversion_rejects_invalid_pages_without_publishing(tmp_path, monkeypatch, page):
    from app.file_share import MaterializedResource

    async def materialize(ctx, uri, destination, *, max_bytes):
        destination.write_bytes(pdf_bytes())
        return MaterializedResource(uri=uri, name="Synthetic.pdf", media_type="application/pdf", size=destination.stat().st_size)

    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(image_mcp, "materialize_resource", materialize)
    publish = AsyncMock()
    monkeypatch.setattr(image_mcp, "resource_create", publish)
    with pytest.raises(RecoverableToolError, match="page"):
        await image_mcp.image_from_pdf(McpToolContext(agent_id=17, runtime="internal"), "file://synthetic", "file://", page=page)
    publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not a PDF", b"%PDF-1.7\ncorrupted"])
async def test_pdf_conversion_checks_actual_bytes_and_does_not_publish_corrupt_inputs(tmp_path, monkeypatch, content):
    from app.file_share import MaterializedResource

    paths = []
    async def materialize(ctx, uri, destination, *, max_bytes):
        paths.append(destination)
        destination.write_bytes(content)
        return MaterializedResource(uri=uri, name="Synthetic.pdf", media_type="application/pdf", size=len(content))

    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(image_mcp, "materialize_resource", materialize)
    publish = AsyncMock()
    monkeypatch.setattr(image_mcp, "resource_create", publish)
    with pytest.raises(RecoverableToolError):
        await image_mcp.image_from_pdf(McpToolContext(agent_id=17, runtime="internal"), "file://synthetic", "file://")
    publish.assert_not_awaited()
    assert paths and all(not path.exists() for path in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["source_denied", "destination_denied", "destination_exists"])
async def test_pdf_conversion_preserves_access_denials_and_never_overwrites(db, monkeypatch, failure):
    from app.file_share import MaterializedResource

    paths = []
    async def materialize(ctx, uri, destination, *, max_bytes):
        if failure == "source_denied":
            raise PermissionError("Source unavailable")
        paths.append(destination)
        destination.write_bytes(pdf_bytes())
        return MaterializedResource(uri=uri, name="Synthetic.pdf", media_type="application/pdf", size=destination.stat().st_size)

    monkeypatch.setattr(image_mcp, "_context_language", AsyncMock(return_value="en"))
    monkeypatch.setattr(image_mcp, "materialize_resource", materialize)
    publish = AsyncMock(side_effect=FileExistsError("Existing destination") if failure == "destination_exists" else PermissionError("Destination unavailable"))
    overwrite = AsyncMock()
    monkeypatch.setattr(image_mcp, "resource_create", publish)
    monkeypatch.setattr(image_mcp, "resource_write", overwrite)
    with pytest.raises(RecoverableToolError):
        await image_mcp.image_from_pdf(McpToolContext(agent_id=17, runtime="internal"), "file://synthetic", "console://output.png")
    assert publish.await_count == (0 if failure == "source_denied" else 1)
    overwrite.assert_not_awaited()
    assert all(not path.exists() for path in paths)


@pytest.mark.asyncio
async def test_pdf_render_enforces_source_and_pixel_budgets(tmp_path):
    from pypdf import PdfWriter

    large = tmp_path / "large.pdf"
    with large.open("wb") as stream:
        stream.write(b"%PDF-1.7\n")
        stream.truncate(64_000_001)
    with pytest.raises(ValueError, match="64 MB"):
        await render_pdf_page(large, tmp_path / "unused.png")
    writer = PdfWriter()
    writer.add_blank_page(width=12000, height=6000)
    writer.write(tmp_path / "wide.pdf")
    result = await render_pdf_page(tmp_path / "wide.pdf", tmp_path / "wide.png")
    assert max(result.width, result.height) <= 3000
    with Image.open(tmp_path / "wide.png") as image:
        assert image.size == (result.width, result.height)


@pytest.mark.asyncio
async def test_pdf_render_cancellation_kills_and_drains_the_worker(monkeypatch, tmp_path):
    from core.document import pdf_page

    entered, draining, reaped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Worker:
        returncode = None
        async def communicate(self):
            entered.set()
            await asyncio.Event().wait()
        def kill(self):
            self.returncode = -9
        async def wait(self):
            draining.set()
            await reaped.wait()
            return self.returncode
    worker = Worker()
    monkeypatch.setattr(pdf_page.asyncio, "create_subprocess_exec", AsyncMock(return_value=worker))
    task = asyncio.create_task(render_pdf_page(tmp_path / "source", tmp_path / "image"))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.wait_for(draining.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and worker.returncode == -9
    reaped.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_pdf_conversion_is_exposed_with_an_explicit_destination_and_positive_page():
    mcp = FastMCP("test")
    add_galaris_tools(mcp, 1, runtime="internal", enabled_tool_codes={"image"})
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    schema = tools["image_from_pdf"].parameters
    assert schema["required"] == ["file", "destination"]
    assert schema["properties"]["page"]["minimum"] == 1
