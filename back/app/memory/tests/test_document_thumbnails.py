from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import av
import pytest
from PIL import Image

from app.memory.document_thumbnail_service import (
    _text_thumbnail,
    _video_thumbnail,
    _web_url,
)
from app.memory.schemas import DocumentAttachmentPublic, DocumentThumbnailRender
from app.memory import document_thumbnail_service
from app.memory import service
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemoryGrantUpdate
from core.preview import thumbnails
from app.browser import service as browser_service
from app.browser.schemas import BrowserScreenshot, BrowserScreenshotPart


@pytest.mark.asyncio
async def test_document_capture_tracks_saved_revisions_and_rechecks_access(
    agents, memory_storage, tmp_path, monkeypatch,
):
    owner, peer = agents
    cache_root = tmp_path / "thumbnails"
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(cache_root))
    captured = []

    async def capture(html, *, first_page_only):
        assert first_page_only
        captured.append(html)
        return html.encode()

    monkeypatch.setattr(document_thumbnail_service, "render_html_pdf", capture)
    monkeypatch.setattr(document_thumbnail_service, "_printed_document_thumbnail", lambda html:
        thumbnails.encode(Image.new("RGB", (80, 60), "blue" if b"First" in html else "red")))
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Report", memory_type="working", node_kind="document", media_type="text/html",
        payload=MemoryPayload(text="<h1>First revision</h1><table><tr><td>Result</td></tr></table>"),
    ))
    await service.set_item_grant(item.id, peer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    snapshot = DocumentThumbnailRender(html="<h1>First revision</h1><table><tr><td>Result</td></tr></table>", revision=item.revision, lock_version=item.lock_version)
    first = await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=peer.id)
    assert first is not None
    assert "<h1>First revision</h1>" in captured[0]
    assert "<table>" in captured[0]
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) == first
    assert len(captured) == 1

    await service.update_item(item.id, MemoryItemUpdate(
        expected_revision=item.revision, payload=MemoryPayload(text="<h1>Second revision</h1>"),
    ), actor_agent_id=owner.id)
    assert not list(cache_root.rglob("*.png"))
    assert not list(cache_root.rglob("*.revision.json"))
    with pytest.raises(service.MemoryConflictError):
        await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id)
    snapshot = DocumentThumbnailRender(html="<h1>Second revision</h1>", revision=item.revision, lock_version=item.lock_version)
    second = await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=peer.id)
    assert second is not None and second != first
    assert len(captured) == 2
    metadata = [json.loads(path.read_text()) for path in cache_root.rglob("*.revision.json")]
    assert {value["revision"] for value in metadata} == {item.revision}
    assert all(value["document_id"] == str(item.id) for value in metadata)
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) == second
    assert len(captured) == 2

    await service.remove_item_grant(item.id, peer.id, actor_agent_id=owner.id)
    snapshot.lock_version = item.lock_version
    await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=peer.id)


@pytest.mark.asyncio
async def test_document_thumbnail_isolates_snapshots_and_recovers_from_renderer_failure(
    agents, memory_storage, tmp_path, monkeypatch,
):
    owner, _ = agents
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path / "thumbnails"))
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Illustrated report", memory_type="working", node_kind="document", media_type="text/html",
        payload=MemoryPayload(text="<p>Illustration</p>"),
    ))
    png = thumbnails.encode(Image.new("RGB", (64, 48), "green"))
    snapshot = DocumentThumbnailRender(html='<p>Illustration</p>', revision=item.revision, lock_version=item.lock_version)
    capture = AsyncMock(side_effect=RuntimeError("renderer unavailable"))
    monkeypatch.setattr(document_thumbnail_service, "render_html_pdf", capture)
    monkeypatch.setattr(document_thumbnail_service, "_printed_document_thumbnail", lambda _: png)
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) is None
    assert not list((tmp_path / "thumbnails").rglob("*.revision.json"))
    capture.side_effect = None
    capture.return_value = b"pdf"
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) == png
    assert capture.await_count == 2
    snapshot.html = '<p>Another client snapshot</p>'
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) == png
    assert capture.await_count == 3
    assert len(list((tmp_path / "thumbnails").rglob("*.revision.json"))) == 2

    async def edit_during_capture(html, *, first_page_only):
        await service.update_item(item.id, MemoryItemUpdate(
            payload=MemoryPayload(text='<p>Edited during capture</p>'),
        ), actor_agent_id=owner.id)
        return b"late pdf"

    monkeypatch.setattr(document_thumbnail_service, "render_html_pdf", edit_during_capture)
    snapshot.html = '<p>Capture in flight</p>'
    assert await document_thumbnail_service.read_document_thumbnail(item.id, snapshot, actor_agent_id=owner.id) is None
    assert not list((tmp_path / "thumbnails").rglob("*.png"))


@pytest.mark.asyncio
async def test_document_thumbnail_endpoint_enforces_management_scope(agents, memory_storage, monkeypatch):
    from app.agent import AgentManagementScope
    from app.memory import router
    from fastapi import HTTPException

    owner, peer = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Private", memory_type="working", node_kind="document", media_type="text/html",
        payload=MemoryPayload(text="<p>Private</p>"),
    ))
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(
        user_id=owner.user_id, agent_ids=frozenset({owner.id}),
    )))
    capture = AsyncMock(side_effect=RuntimeError("renderer unavailable"))
    monkeypatch.setattr(document_thumbnail_service, "render_html_pdf", capture)
    snapshot = DocumentThumbnailRender(html='<p>Private</p>', revision=item.revision, lock_version=item.lock_version)
    response = await router.read_document_thumbnail(item.id, snapshot, agent_id=owner.id)
    assert response.status_code == 204
    with pytest.raises(HTTPException) as denied:
        await router.read_document_thumbnail(item.id, snapshot, agent_id=peer.id)
    assert denied.value.status_code == 404
    capture.assert_awaited_once()


def _attachment(name: str, media_type: str) -> DocumentAttachmentPublic:
    return DocumentAttachmentPublic(
        id=uuid4(),
        name=name,
        media_type=media_type,
        size_bytes=1,
        created_at=datetime.now(timezone.utc),
    )


def test_transparent_image_thumbnail_keeps_alpha_and_its_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 0)).save(source)

    content = thumbnails.from_image(source)

    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.size == (40, 20)
        assert thumbnail.mode == "RGBA"
        assert thumbnail.getpixel((0, 0)) == (255, 0, 0, 0)


@pytest.mark.parametrize("size, expected", [((600, 900), (213, 320)), ((1200, 600), (520, 260)), ((900, 900), (320, 320)), ((24, 16), (24, 16))])
def test_thumbnail_fits_bounds_without_white_padding_or_cropping(tmp_path: Path, size: tuple[int, int], expected: tuple[int, int]) -> None:
    source = tmp_path / "image.png"
    image = Image.new("RGB", size, "#1976d2")
    image.save(source)
    content = thumbnails.from_image(source)
    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.size == expected
        assert thumbnail.getpixel((0, 0)) == (25, 118, 210)
        assert thumbnail.getpixel((thumbnail.width - 1, thumbnail.height - 1)) == (25, 118, 210)


def test_thumbnail_applies_exif_orientation_before_fitting(tmp_path: Path) -> None:
    source = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (900, 600), "blue")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    content = thumbnails.from_image(source)
    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.size == (213, 320)
        assert not thumbnail.getexif()


def test_palette_transparency_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "palette.png"
    image = Image.new("P", (40, 20), 0)
    image.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762)
    image.putpixel((20, 10), 1)
    image.save(source, transparency=0)
    content = thumbnails.from_image(source)
    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.getpixel((0, 0))[3] == 0
        assert thumbnail.getpixel((20, 10)) == (0, 0, 255, 255)


@pytest.mark.asyncio
async def test_document_thumbnail_is_shared_with_browser_after_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    attachment = _attachment("portrait.png", "image/png")
    source = tmp_path / "portrait.png"
    Image.new("RGB", (600, 900), "blue").save(source)
    reference = f"document://{document_id}/attachments/{attachment.id}"
    cache_root = tmp_path / "cache"
    from core import settings
    monkeypatch.setattr(type(settings), "GALARIS_THUMBNAIL_ROOT", str(cache_root))
    authorized_path = AsyncMock(return_value=(attachment, source))
    monkeypatch.setattr(document_thumbnail_service.document_attachment_service, "document_attachment_path", authorized_path)

    assert await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(document_id, attachment.id, actor_agent_id=7) is None
    await document_thumbnail_service._tasks[reference]
    content = await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(document_id, attachment.id, actor_agent_id=7)
    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.size == (213, 320)
        assert thumbnail.getpixel((0, 0)) == (0, 0, 255)
    assert authorized_path.await_count == 2
    from app.browser import read_cached_thumbnail
    assert await read_cached_thumbnail(reference=reference) == (content, "image/png")
    assert list(cache_root.iterdir()) == [thumbnails.cache_path(reference)]
    authorized_path.side_effect = PermissionError("denied")
    with pytest.raises(PermissionError):
        await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(
            document_id, attachment.id, actor_agent_id=8,
        )


def test_text_thumbnail_is_bounded_png(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("First line\nSecond line", encoding="utf-8")

    content = _text_thumbnail(source)

    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.size == (520, 320)


def test_video_thumbnail_extracts_an_early_frame(tmp_path: Path) -> None:
    source = tmp_path / "preview.mkv"
    with av.open(str(source), mode="w", format="matroska") as container:
        stream = container.add_stream("mpeg4", rate=1)
        stream.width = 64
        stream.height = 32
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame.from_image(Image.new("RGB", (64, 32), "#e53935"))
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)

    content = _video_thumbnail(source)

    assert content is not None
    with Image.open(BytesIO(content)) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.size == (64, 32)
        red, green, blue = thumbnail.getpixel((32, 16))
        assert red > 180
        assert green < 100
        assert blue < 100


def test_web_thumbnail_only_accepts_https_url_attachments(tmp_path: Path) -> None:
    source = tmp_path / "site.url"
    source.write_text("[InternetShortcut]\nURL=https://example.com/page\n", encoding="utf-8")
    attachment = _attachment("site.url", "application/octet-stream")

    assert _web_url(source, attachment) == "https://example.com/page"

    source.write_text("URL=http://internal.test/\n", encoding="utf-8")
    assert _web_url(source, attachment) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("html", [False, True])
async def test_document_and_chat_share_one_capture_and_deletion_scope(tmp_path, monkeypatch, html):
    document_id = uuid4()
    attachment = _attachment("page.html" if html else "site.url", "text/html" if html else "text/uri-list")
    reference = f"document://{document_id}/attachments/{attachment.id}"
    url = "https://example.org/"
    cache_reference = reference if html else url
    source = tmp_path / attachment.name
    source.write_text("<h1>Example</h1>" if html else f"URL={url}", encoding="utf-8")
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(cache_root))
    authorized_path = AsyncMock(return_value=(attachment, source))
    monkeypatch.setattr(document_thumbnail_service.document_attachment_service, "document_attachment_path", authorized_path)
    image = thumbnails.encode(Image.new("RGB", (520, 320), "blue"))
    screenshot = BrowserScreenshot(
        session_id="thumbnail", url=url, title="Example", description="Shared description",
        site_name="Example", revision=1, page_width=1440, page_height=900,
        captured_height=900, truncated=False,
        parts=[BrowserScreenshotPart(index=0, y=0, width=520, height=320,
            mime_type="image/png", data=base64.b64encode(image).decode())],
    )
    capture = AsyncMock(return_value=screenshot)
    monkeypatch.setattr(browser_service.browser_executor, "open", capture)
    monkeypatch.setattr(browser_service.browser_executor, "render_html", capture)
    monkeypatch.setattr(browser_service.browser_executor, "close", AsyncMock())

    async def capture_web(agent_id, url):
        return await browser_service.capture_public_page_thumbnail(agent_id=agent_id, url=url)

    async def capture_html(agent_id, reference, content):
        return await browser_service.capture_html_page_thumbnail(agent_id=agent_id, reference=reference, content=content)

    monkeypatch.setattr(document_thumbnail_service, "_web_thumbnail_capture", capture_web)
    monkeypatch.setattr(document_thumbnail_service, "_html_thumbnail_capture", capture_html)
    assert await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(document_id, attachment.id, actor_agent_id=7) is None
    document_task = document_thumbnail_service._tasks[reference]
    # A discussion requests the same resource while the document is generating it.
    chat_capture = capture_html(7, reference, source.read_bytes()) if html else capture_web(7, url)
    await asyncio.gather(document_task, chat_capture)
    content = await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(document_id, attachment.id, actor_agent_id=7)
    assert content == image
    assert await browser_service.read_cached_thumbnail(reference=cache_reference) == (content, "image/png")
    assert (await browser_service.read_cached_page_metadata(reference=cache_reference)).description == "Shared description"
    capture.assert_awaited_once()
    assert list(cache_root.glob("*.png")) == [thumbnails.cache_path(cache_reference)]
    assert not (cache_root / "documents").exists()

    if not html:
        # Another shortcut to the same URL neither copies nor regenerates it.
        await document_thumbnail_service.read_or_schedule_document_attachment_thumbnail(uuid4(), attachment.id, actor_agent_id=7)
        capture.assert_awaited_once()
    await document_thumbnail_service.delete_document_attachment_thumbnail(document_id, attachment.id)
    remaining = await browser_service.read_cached_thumbnail(reference=cache_reference)
    assert remaining is None if html else remaining == (content, "image/png")
    assert thumbnails.cache_path(cache_reference).with_suffix(".json").exists() is not html
