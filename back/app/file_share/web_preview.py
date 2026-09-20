"""Bounded public HTTPS metadata shared by document and conversation previews."""
from __future__ import annotations
import asyncio
import json
import re
import httpx
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from core.preview import WebLinkPreview
from .web_transport import PublicHttpsContent, read_public_https_bytes
from .resource_uri import ResourceUriError, parse_resource_uri
_WEB_TIMEOUT_SECONDS = 15
_WEB_PAGE_BYTES = 1_048_576
_RESOURCE_PREVIEW_BYTES = 64 * 1_048_576
_YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}

class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self._in_title = True
            return
        if normalized != "meta":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        key = (values.get("property") or values.get("name") or "").strip().casefold()
        content = values.get("content", "").strip()
        if key and content and key not in self.metadata:
            self.metadata[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


@dataclass(frozen=True, slots=True)
class WebMetadata:
    url: str
    title: str
    description: str
    site_name: str
    image_url: str | None
    media_type: str = "text/html"
    download_available: bool = False
    youtube_id: str | None = None


async def _read_web_bytes(
    url: str,
    *,
    max_bytes: int,
    truncate: bool = False,
) -> PublicHttpsContent:
    async with asyncio.timeout(_WEB_TIMEOUT_SECONDS):
        return await read_public_https_bytes(
            url,
            max_bytes=max_bytes,
            truncate=truncate,
        )


def _compact_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _youtube_video_id(value: str) -> str | None:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    candidate = ""
    if hostname == "youtu.be" and len(parts) == 1:
        candidate = parts[0]
    elif hostname in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in {"embed", "shorts", "live"}:
            candidate = parts[1]
    return candidate if _YOUTUBE_ID_PATTERN.fullmatch(candidate) else None


def _safe_image_url(page_url: str, candidate: str) -> str | None:
    if not candidate.strip():
        return None
    resolved = urljoin(page_url, candidate.strip())
    try:
        reference = parse_resource_uri(resolved)
    except ResourceUriError:
        return None
    return str(reference) if reference.scheme == "https" else None


async def _youtube_metadata(url: str, video_id: str) -> WebMetadata:
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed_url = "https://www.youtube.com/oembed?" + urlencode(
        {"url": canonical_url, "format": "json"}
    )
    try:
        response = await _read_web_bytes(
            oembed_url,
            max_bytes=128 * 1024,
        )
        payload = cast(dict[str, Any], json.loads(response.content.decode("utf-8")))
        title = _compact_text(payload.get("title"), limit=300)
        author = _compact_text(payload.get("author_name"), limit=160)
        image_url = _safe_image_url(
            response.url,
            str(payload.get("thumbnail_url") or ""),
        )
    except (OSError, ValueError, TypeError, TimeoutError, httpx.HTTPError):
        title = "YouTube"
        author = "YouTube"
        image_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return WebMetadata(
        url=url,
        title=title or "YouTube",
        description="",
        site_name=author or "YouTube",
        image_url=image_url,
        media_type="text/html",
        youtube_id=video_id,
    )


async def web_metadata(url: str) -> WebMetadata:
    video_id = _youtube_video_id(url)
    if video_id is not None:
        return await _youtube_metadata(url, video_id)

    try:
        response = await _read_web_bytes(url, max_bytes=_WEB_PAGE_BYTES, truncate=True)
    except (httpx.HTTPError, OSError, TimeoutError):
        hostname = urlsplit(url).hostname or url
        return WebMetadata(url=url, title=hostname, description="", site_name=hostname, image_url=None)
    hostname = urlsplit(response.url).hostname or urlsplit(url).hostname or "Web"
    if response.media_type not in _HTML_MEDIA_TYPES:
        return WebMetadata(
            url=response.url,
            title=response.url.rsplit("/", 1)[-1] or hostname,
            description="",
            site_name=hostname,
            image_url=None,
            media_type=response.media_type,
            download_available=len(response.content) <= _RESOURCE_PREVIEW_BYTES,
        )
    parser = _MetadataParser()
    parser.feed(response.content.decode("utf-8", errors="replace"))
    title = (
        parser.metadata.get("og:title")
        or parser.metadata.get("twitter:title")
        or " ".join(parser.title_parts)
        or hostname
    )
    description = (
        parser.metadata.get("og:description")
        or parser.metadata.get("twitter:description")
        or parser.metadata.get("description")
        or ""
    )
    image_url = next((
        resolved
        for key in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")
        if (resolved := _safe_image_url(response.url, parser.metadata.get(key, "")))
    ), None)
    return WebMetadata(
        url=response.url,
        title=_compact_text(title, limit=300) or hostname,
        description=_compact_text(description, limit=600),
        site_name=_compact_text(parser.metadata.get("og:site_name"), limit=160) or hostname,
        image_url=image_url,
        media_type=response.media_type,
    )




async def document_web_preview(url: str) -> WebLinkPreview:
    metadata = await web_metadata(url)
    image = None
    if metadata.image_url:
        try:
            response = await _read_web_bytes(metadata.image_url, max_bytes=5 * 1_048_576)
            image = response.content
        except (OSError, ValueError, TimeoutError, httpx.HTTPError):
            pass
    return WebLinkPreview(
        metadata.title, metadata.description, metadata.site_name, image,
        page_url=metadata.url if metadata.youtube_id is None and metadata.media_type in _HTML_MEDIA_TYPES else None,
    )
