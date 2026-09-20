from io import BytesIO
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

import app.browser as browser
from app.browser import service
from app.file_share import web_preview
from core.preview import WebLinkPreview, preview_web_link, thumbnails


@pytest.mark.asyncio
async def test_document_reuses_chat_thumbnail_cache_even_without_page_metadata(monkeypatch, tmp_path):
    url = "https://example.org/"
    output = BytesIO()
    Image.new("RGB", (320, 200), "blue").save(output, "PNG")
    # The same cache that Chat's image endpoint reads.
    monkeypatch.setattr(type(service.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    thumbnails.write(thumbnails.cache_path(url), output.getvalue())
    thumbnails.write(thumbnails.cache_path(url).with_suffix('.json'), b'{"title":"News","description":"Site description","site_name":"Publisher"}')
    open_browser = AsyncMock()
    monkeypatch.setattr(service.browser_executor, "open", open_browser)

    async def fetch(url, **kwargs):
        httpx.Response(403, request=httpx.Request("GET", url)).raise_for_status()

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    result = await preview_web_link(url, agent_id=7)
    assert result.image == (await browser.read_cached_thumbnail(reference=url))[0]
    assert result.description == "Site description"
    assert result.title == "News"
    open_browser.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_uses_existing_browser_capture_with_actor_scope(monkeypatch):
    url = "https://example.org/news"
    metadata = WebLinkPreview("News", "Description", "Publisher", b"og-image", page_url=url)
    monkeypatch.setattr(browser, "document_web_preview", AsyncMock(return_value=metadata))
    capture = AsyncMock(return_value=(b"shared-page-capture", "image/jpeg"))
    monkeypatch.setattr(browser, "capture_public_page_thumbnail", capture)
    result = await preview_web_link(url, agent_id=7)
    capture.assert_awaited_once_with(agent_id=7, url=url)
    assert result.image == b"shared-page-capture"
    assert result.title == "News"


@pytest.mark.asyncio
async def test_youtube_keeps_its_video_thumbnail_without_a_page_capture(monkeypatch):
    metadata = WebLinkPreview("Video", "", "YouTube", b"video-thumbnail")
    monkeypatch.setattr(browser, "document_web_preview", AsyncMock(return_value=metadata))
    capture = AsyncMock()
    monkeypatch.setattr(browser, "capture_public_page_thumbnail", capture)
    assert await preview_web_link("https://youtu.be/dQw4w9WgXcQ", agent_id=7) == metadata
    capture.assert_not_awaited()
