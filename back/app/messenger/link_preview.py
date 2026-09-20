"""Safe previews for canonical resource references and public Web links in Chat."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast
from urllib.parse import urldefrag

from loguru import logger

from core.params import runtime_settings

from app.file_share import (
    ResourceContext,
    ResourceDescriptor,
    ResourceUriError,
    PublicHttpsContent,
    PROTOCOL_SCHEMES,
    materialize_resource,
    parse_resource_uri,
    read_public_https_bytes,
    resource_info,
    resource_read,
)

from .contracts import MessageResourcePreview
from app.file_share import web_metadata as _web_metadata


def _compact_text(value: object, *, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


async def _read_web_bytes(url: str, *, max_bytes: int, truncate: bool = False) -> PublicHttpsContent:
    async with asyncio.timeout(_WEB_TIMEOUT_SECONDS):
        return await read_public_https_bytes(url, max_bytes=max_bytes, truncate=truncate)


_REFERENCE_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"'`]+",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = ".,;:!?"
_MAX_PREVIEWS = 8
_MAX_REFERENCE_LENGTH = 2_048
_RESOURCE_PREVIEW_CHARS = 50_000
_RESOURCE_PREVIEW_BYTES = 64 * 1_048_576
_WEB_IMAGE_BYTES = 5 * 1_048_576
_WEB_TIMEOUT_SECONDS = 15
_IMAGE_MEDIA_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}
_RESOURCE_KINDS = {
    "task",
    "text",
    "voice",
    "goal",
    "goal_cycle",
    "process",
    "skill",
}
ResourcePreviewKind = Literal[
    "document",
    "memory",
    "task",
    "text",
    "voice",
    "goal",
    "goal_cycle",
    "process",
    "skill",
    "file",
    "resource",
]


@dataclass(slots=True)
class PreviewResourceFile:
    """One bounded server-side resource copy kept alive until the HTTP response ends."""

    path: Path
    name: str
    media_type: str
    _temporary: TemporaryDirectory[str]

    def cleanup(self) -> None:
        self._temporary.cleanup()


def _trim_reference(value: str) -> str:
    result = value.rstrip(_TRAILING_PUNCTUATION)
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while result.endswith(closing) and result.count(closing) > result.count(opening):
            result = result[:-1]
    return result


def extract_preview_references(
    text: str,
    *,
    include_file_resources: bool = False,
) -> tuple[str, ...]:
    """Return unique, exact item references from one message in display order."""

    references: list[str] = []
    seen: set[str] = set()
    for match in _REFERENCE_PATTERN.finditer(text):
        raw = _trim_reference(match.group(0))
        if not raw or len(raw) > _MAX_REFERENCE_LENGTH:
            continue
        if raw.casefold().startswith("https://"):
            raw = urldefrag(raw)[0]
        try:
            reference = parse_resource_uri(raw)
        except ResourceUriError:
            continue
        normalized = str(reference)
        is_existing_preview = reference.scheme in {
            "document",
            "memory",
            "galaris",
            "https",
        }
        is_file_resource = (
            include_file_resources
            and reference.scheme not in PROTOCOL_SCHEMES
        )
        if not is_existing_preview and not is_file_resource:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        references.append(normalized)
        if len(references) >= _MAX_PREVIEWS:
            break
    return tuple(references)


def _resource_kind(uri: str) -> ResourcePreviewKind:
    reference = parse_resource_uri(uri)
    if reference.scheme == "document":
        return "document"
    if reference.scheme == "memory":
        return "memory"
    if reference.scheme != "galaris":
        return "file"
    first = reference.segments[0] if reference.segments else ""
    return cast(ResourcePreviewKind, first) if first in _RESOURCE_KINDS else "resource"


def _content_format(descriptor: ResourceDescriptor, kind: str) -> Literal[
    "html", "markdown", "text", "json", "none"
]:
    media_type = descriptor.media_type.casefold()
    if media_type == "text/html" and kind in {"document", "memory"} and descriptor.metadata.get("content_profile_version") == 1:
        return "html"
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "none"
    if kind == "document" or media_type in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if media_type.startswith("text/"):
        return "text"
    if media_type.endswith("+json") or media_type == "application/json":
        return "json"
    return "none"


def _json_description(content: str) -> str:
    try:
        raw_payload: object = json.loads(content)
    except json.JSONDecodeError:
        return ""
    if not isinstance(raw_payload, dict):
        return ""
    payload = cast(dict[str, object], raw_payload)
    candidates: list[object] = [
        payload.get("summary"),
        payload.get("description"),
        payload.get("objective"),
        payload.get("result"),
    ]
    round_payload = payload.get("round")
    if isinstance(round_payload, dict):
        typed_round = cast(dict[str, object], round_payload)
        candidates.extend(
            [typed_round.get("summary"), typed_round.get("result")]
        )
    for candidate in candidates:
        result = _compact_text(candidate, limit=500)
        if result:
            return result
    return ""


async def _resource_preview(uri: str, *, agent_id: int) -> MessageResourcePreview:
    context = ResourceContext(agent_id=agent_id, runtime="internal")
    descriptor = await resource_info(context, uri)
    kind = _resource_kind(uri)
    content: str | None = None
    content_format = _content_format(descriptor, kind)
    truncated = False
    readable = not descriptor.is_collection and "read" in descriptor.capabilities
    media_type = descriptor.media_type.split(";", 1)[0].strip().casefold()
    if readable and content_format != "none":
        try:
            result = await resource_read(
                context,
                uri,
                max_chars=_RESOURCE_PREVIEW_CHARS,
            )
            if result.encoding == "utf-8":
                content = result.content
                truncated = result.next_offset is not None
        except (FileNotFoundError, PermissionError, ValueError):
            content = None
    title = _compact_text(descriptor.metadata.get("label"), limit=300) or descriptor.name or uri
    description = ""
    if content:
        description = (
            _json_description(content)
            if content_format == "json"
            else _compact_text(content, limit=500)
        )
    subtitle_parts = [
        _compact_text(descriptor.metadata.get("status"), limit=80),
        _compact_text(descriptor.modified_at, limit=80),
    ]
    if content_format == "html" and content is not None:
        from core.util import visible_text
        description = _compact_text(visible_text(content), limit=500)
    return MessageResourcePreview(
        uri=uri,
        kind=kind,
        title=title,
        subtitle=" · ".join(part for part in subtitle_parts if part),
        description=description,
        media_type=descriptor.media_type,
        content=content,
        content_format=content_format,
        truncated=truncated,
        image_available=(
            readable
            and kind == "file"
            and media_type in _HTML_MEDIA_TYPES
            and (
                descriptor.size is None
                or descriptor.size <= runtime_settings.BROWSER_HTML_MAX_BYTES
            )
        ),
        download_available=(
            readable
            and kind == "file"
            and (
                descriptor.size is None
                or descriptor.size <= _RESOURCE_PREVIEW_BYTES
            )
        ),
        metadata={
            **descriptor.metadata,
            "revision": descriptor.revision,
            "updated_at": descriptor.modified_at,
        } if kind == "document" else descriptor.metadata,
    )


async def preview_reference(
    uri: str,
    *,
    agent_id: int,
) -> MessageResourcePreview | None:
    """Build one bounded preview; inaccessible links are omitted from the conversation."""

    try:
        if parse_resource_uri(uri).scheme == "https":
            metadata = await _web_metadata(uri)
            is_external_html = (
                metadata.youtube_id is None
                and metadata.media_type in _HTML_MEDIA_TYPES
            )
            return MessageResourcePreview(
                uri=uri,
                kind="youtube" if metadata.youtube_id else "web",
                title=metadata.title,
                subtitle=metadata.site_name,
                description=metadata.description,
                media_type=metadata.media_type,
                image_available=(metadata.image_url is not None or is_external_html),
                download_available=metadata.download_available,
                open_mode="external" if is_external_html else "inline",
                external_url=metadata.url,
                embed_url=(
                    f"https://www.youtube-nocookie.com/embed/{metadata.youtube_id}"
                    if metadata.youtube_id
                    else None
                ),
            )
        return await _resource_preview(uri, agent_id=agent_id)
    except Exception as exc:
        logger.debug("Chat link preview unavailable: {}", type(exc).__name__)
        return None


async def materialize_preview_resource(
    uri: str,
    *,
    agent_id: int,
    max_bytes: int = _RESOURCE_PREVIEW_BYTES,
) -> PreviewResourceFile | None:
    """Materialize one exact, readable Chat reference for an inline browser response."""

    temporary = TemporaryDirectory(prefix="galaris_chat_preview_")
    destination = Path(temporary.name) / "resource"
    try:
        materialized = await materialize_resource(
            ResourceContext(agent_id=agent_id, runtime="internal"),
            uri,
            destination,
            max_bytes=max_bytes,
        )
        return PreviewResourceFile(
            path=destination,
            name=materialized.name,
            media_type=materialized.media_type,
            _temporary=temporary,
        )
    except Exception as exc:
        temporary.cleanup()
        logger.debug(
            "Chat resource materialization unavailable: {}",
            type(exc).__name__,
        )
        return None


async def preview_references(
    references: tuple[str, ...],
    *,
    agent_id: int,
) -> list[MessageResourcePreview]:
    previews: list[MessageResourcePreview | None] = [None] * len(references)
    web_indexes = [
        index
        for index, uri in enumerate(references)
        if parse_resource_uri(uri).scheme == "https"
    ]
    web_previews = await asyncio.gather(
        *(preview_reference(references[index], agent_id=agent_id) for index in web_indexes)
    )
    for index, preview in zip(web_indexes, web_previews, strict=True):
        previews[index] = preview
    for index, uri in enumerate(references):
        if index in web_indexes:
            continue
        previews[index] = await preview_reference(uri, agent_id=agent_id)
    return [preview for preview in previews if preview is not None]


async def preview_image(
    uri: str,
) -> tuple[bytes, str] | None:
    """Resolve a bounded thumbnail for one public Web preview."""

    try:
        if parse_resource_uri(uri).scheme != "https":
            return None
        metadata = await _web_metadata(uri)
        if metadata.image_url is None:
            return None
        response = await _read_web_bytes(
            metadata.image_url,
            max_bytes=_WEB_IMAGE_BYTES,
        )
        if response.media_type not in _IMAGE_MEDIA_TYPES:
            return None
        return response.content, response.media_type
    except Exception as exc:
        logger.debug("Chat link preview image unavailable: {}", type(exc).__name__)
        return None


__all__ = [
    "extract_preview_references",
    "materialize_preview_resource",
    "PreviewResourceFile",
    "preview_image",
    "preview_reference",
    "preview_references",
]
