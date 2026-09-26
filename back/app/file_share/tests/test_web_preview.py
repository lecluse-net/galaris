import pytest
import httpx

from app.file_share import PublicHttpsContent, web_preview
from app.file_share.web_preview import document_web_preview as preview_web_link
from core.preview import read_web_image


@pytest.mark.asyncio
async def test_pasted_image_uses_registered_bounded_transport(monkeypatch):
    async def fetch(url, *, max_bytes, truncate=False):
        assert url == "https://example.org/image.png"
        assert max_bytes == 10_000_000
        assert truncate is False
        return PublicHttpsContent(url=url, media_type="image/png", content=b"original image")

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    assert await read_web_image("https://example.org/image.png") == b"original image"


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [
    '<meta property="og:image:url" content="/photo.jpg">',
    '<meta property="og:image" content="http://example.org/photo.jpg">'
    '<meta property="og:image:secure_url" content="https://example.org/photo.jpg">',
    '<meta property="og:image" content="http://example.org/old.jpg">'
    '<meta name="twitter:image" content="//example.org/photo.jpg">',
    '<meta name="twitter:image:src" content="/photo.jpg">',
])
async def test_document_preview_reads_alternate_thumbnail_metadata(monkeypatch, tags):
    calls = []

    async def fetch(url, *, max_bytes, truncate=False):
        calls.append(url)
        if url.endswith("photo.jpg"):
            return PublicHttpsContent(url=url, media_type="image/jpeg", content=b"thumbnail")
        return PublicHttpsContent(url=url, media_type="text/html", content=tags.encode())

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    preview = await preview_web_link("https://example.org/news")
    assert preview.image == b"thumbnail"
    assert calls == ["https://example.org/news", "https://example.org/photo.jpg"]


@pytest.mark.asyncio
async def test_registered_preview_transport_uses_youtube_metadata_and_bounded_thumbnail(monkeypatch):
    calls = []

    async def fetch(url, *, max_bytes, truncate=False):
        calls.append((url, max_bytes, truncate))
        if "oembed" in url:
            return PublicHttpsContent(url=url, media_type="application/json", content=(
                b'{"title":"Island tour","author_name":"Guide",'
                b'"thumbnail_url":"https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}'
            ))
        return PublicHttpsContent(url=url, media_type="image/jpeg", content=b"thumbnail")

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    preview = await preview_web_link("https://youtu.be/dQw4w9WgXcQ")
    assert preview.title == "Island tour"
    assert preview.site_name == "Guide"
    assert preview.image == b"thumbnail"
    assert len(calls) == 2
    assert calls[0][1] == 128 * 1024
    assert calls[1][1] == 5 * 1024 * 1024


@pytest.mark.asyncio
async def test_unavailable_thumbnail_preserves_page_title_and_description(monkeypatch):
    async def fetch(url, *, max_bytes, truncate=False):
        if url.endswith("image.png"):
            raise ValueError("Not a public address")
        return PublicHttpsContent(url=url, media_type="text/html", content=(
            b'<html><head><title>Report</title><meta name="description" content="Details">'
            b'<meta property="og:image" content="https://127.0.0.1/image.png"></head></html>'
        ))

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    preview = await preview_web_link("https://example.test/report")
    assert preview.title == "Report"
    assert preview.description == "Details"
    assert preview.image is None


@pytest.mark.asyncio
async def test_site_refusing_preview_keeps_a_card_without_fabricated_metadata(monkeypatch):
    async def fetch(url, *, max_bytes, truncate=False):
        response = httpx.Response(403, request=httpx.Request("GET", url))
        response.raise_for_status()

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    preview = await preview_web_link("https://www.lefigaro.fr/")
    assert preview.title == "www.lefigaro.fr"
    assert preview.description == ""
    assert preview.image is None


@pytest.mark.asyncio
async def test_thumbnail_http_refusal_preserves_available_page_metadata(monkeypatch):
    async def fetch(url, *, max_bytes, truncate=False):
        if url.endswith("photo.jpg"):
            httpx.Response(403, request=httpx.Request("GET", url)).raise_for_status()
        return PublicHttpsContent(url=url, media_type="text/html", content=(
            b'<meta property="og:title" content="News"><meta name="description" content="Daily news">'
            b'<meta property="og:image" content="https://example.org/photo.jpg">'
        ))

    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    preview = await preview_web_link("https://example.org/")
    assert preview.title == "News"
    assert preview.description == "Daily news"
    assert preview.image is None
