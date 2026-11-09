"""Operation reuse never substitutes URI identity for content or live permissions."""

# ruff: noqa: F811
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, update

from app.file_share import ResourceContext, resource_create
from app.file_share.models import FileOperationMemo
from app.file_share.mcp import file_to_pdf
from app.file_share.tests.test_pdf_export import image_bytes
from app.file_share.operation_memos import conversion_key, converted_resource, search_with_replay, _write
from app.image.mcp import image_from_pdf
from app.image.tests.test_pdf_conversion import pdf_bytes
from app.process.tests.test_native_bpmn import native as native
from app.tools import McpToolContext, RecoverableToolError


@pytest.mark.asyncio
async def test_real_pdf_and_image_conversions_reuse_exact_content_and_parameters(db, native, monkeypatch):
    import app.image.mcp as image_tools
    import app.file_share.mcp as file_tools
    owner, _ = native
    ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    resources = ResourceContext(agent_id=owner.id, runtime="internal")
    source = await resource_create(resources, "file://", pdf_bytes(), name="Synthetic.pdf")
    render = AsyncMock(wraps=image_tools.render_pdf_page)
    monkeypatch.setattr(image_tools, "render_pdf_page", render)
    first = await image_from_pdf(ctx, source.uri, "file://", page=1)
    replay = await image_from_pdf(ctx, source.uri, "file://", page=1)
    assert first["uri"] == replay["uri"] and replay["reused"] is True and render.await_count == 1
    second = await image_from_pdf(ctx, source.uri, "file://", page=2)
    assert second["uri"] != first["uri"] and render.await_count == 2
    image = await resource_create(resources, "file://", image_bytes(), name="Synthetic.png")
    export = AsyncMock(wraps=file_tools.convert_to_pdf)
    monkeypatch.setattr(file_tools, "convert_to_pdf", export)
    pdf = json.loads(await file_to_pdf(ctx, image.uri, "file://"))
    again = json.loads(await file_to_pdf(ctx, image.uri, "file://"))
    assert pdf["uri"] == again["uri"] and again["reused"] and export.await_count == 1


@pytest.mark.asyncio
async def test_conversion_receipt_never_bypasses_source_deletion_or_other_agent(db, native):
    from app.file_share.managed_files import delete_managed_file
    from uuid import UUID
    owner, other = native
    resources = ResourceContext(agent_id=owner.id, runtime="internal")
    source = await resource_create(resources, "file://", pdf_bytes(), name="Synthetic.pdf")
    ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    await image_from_pdf(ctx, source.uri, "file://")
    with pytest.raises(RecoverableToolError):
        await image_from_pdf(McpToolContext(agent_id=other.id, runtime="internal"), source.uri, "file://")
    await delete_managed_file(resources, UUID(source.uri.removeprefix("file://")))
    with pytest.raises(RecoverableToolError):
        await image_from_pdf(ctx, source.uri, "file://")


@pytest.mark.asyncio
async def test_conversion_keys_bind_source_bytes_name_parameters_runtime_and_destination(db, native, tmp_path):
    owner, other = native
    path = tmp_path / "source"; path.write_bytes(b"first")
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    arguments = dict(uri="file://synthetic", name="Synthetic.pdf", media_type="application/pdf", destination="file://", operation="test/v1")
    first = await conversion_key(ctx, path, **arguments)
    path.write_bytes(b"second")
    assert await conversion_key(ctx, path, **arguments) != first
    path.write_bytes(b"first")
    assert await conversion_key(ctx, path, **{**arguments, "destination": "console://output/"}) != first
    assert await conversion_key(ctx, path, **arguments, parameters={"page": 2}) != first
    assert await converted_resource(replace(ctx, agent_id=other.id), first) is None


@pytest.mark.asyncio
async def test_search_replay_is_bounded_to_same_pending_human_input_and_can_refresh(db, native, monkeypatch):
    from app.file_share import operation_memos as memos
    owner, _ = native
    await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "file://", b"Synthetic", name="Synthetic.txt")
    turn = SimpleNamespace(round_id="synthetic-round", source_request="Find my input", messages=({"text": "Synthetic"},),
        pending_interactions=({"kind": "process_input_preparation"},))
    ctx = ResourceContext(agent_id=owner.id, runtime="internal", conversation_turn=turn)
    search = AsyncMock(wraps=memos.resource_search)
    monkeypatch.setattr(memos, "resource_search", search)
    arguments = dict(mode="name", recursive=True, max_results=10, cursor=None)
    first = await search_with_replay(ctx, "file://", "Synthetic", **arguments)
    second = await search_with_replay(ctx, "file://", "Synthetic", **arguments)
    assert second == first and search.await_count == 1
    await search_with_replay(ctx, "file://", "Synthetic", **arguments, refresh=True)
    assert search.await_count == 2
    turn.source_request = "A different contribution"
    await search_with_replay(ctx, "file://", "Synthetic", **arguments)
    assert search.await_count == 3
    await db.execute(update(FileOperationMemo).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await db.commit()
    await search_with_replay(ctx, "file://", "Synthetic", **arguments)
    assert search.await_count == 4


@pytest.mark.asyncio
async def test_operation_history_has_a_hard_per_agent_bound(db, native):
    owner, _ = native
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    for index in range(205):
        await _write(ctx, str(index), {"synthetic": index}, timedelta(minutes=1))
    assert await db.scalar(select(func.count()).select_from(FileOperationMemo).where(FileOperationMemo.agent_id == owner.id)) == 200
