"""Cached, bounded thumbnails for authorized documents and their attachments."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from collections.abc import Awaitable, Callable
from contextvars import Context
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from core.user import HumanActor

from core.preview import render_html_pdf, thumbnails
from core.params import runtime_settings

from . import document_attachment_service, document_thumbnail_cache, service
from .schemas import DocumentAttachmentPublic, DocumentThumbnailRender


_tasks: dict[str, asyncio.Task[None]] = {}
WebThumbnailCapture = Callable[[int | HumanActor, str], Awaitable[tuple[bytes, str] | None]]
_web_thumbnail_capture: WebThumbnailCapture | None = None
HtmlThumbnailCapture = Callable[[int | HumanActor, str, bytes], Awaitable[tuple[bytes, str] | None]]
_html_thumbnail_capture: HtmlThumbnailCapture | None = None
_document_capture_slots = asyncio.Semaphore(2)


async def read_document_thumbnail(
    document_id: UUID, snapshot: DocumentThumbnailRender, *, actor_agent_id: int | HumanActor,
) -> bytes | None:
    """Capture the saved HTML revision after checking the current reader's access."""
    item, _, _, _, _ = await service.get_item(document_id, agent_id=actor_agent_id)
    if item.node_kind != "document":
        raise service.MemoryNotFoundError("Document not found.")
    if item.document_type == "dataset":
        return None
    if (snapshot.revision, snapshot.lock_version) != (item.revision, item.lock_version):
        raise service.MemoryConflictError("The document changed while preparing its thumbnail.")
    # Include the submitted snapshot so a reader cannot poison another reader's cache.
    digest = sha256(snapshot.html.encode("utf-8")).hexdigest()
    reference = f"document://{document_id}/thumbnail/v3/{item.revision}/{item.lock_version}/{digest}"
    cache_path = document_thumbnail_cache.cache_path(document_id, reference)
    revision_path = cache_path.with_suffix(".revision.json")
    revision_metadata = json.dumps({
        "document_id": str(document_id), "revision": item.revision,
        "lock_version": item.lock_version, "renderer_version": 3, "snapshot_hash": digest,
    }, sort_keys=True).encode("utf-8")

    async def read_current() -> bytes | None:
        if await asyncio.to_thread(thumbnails.read, revision_path, 4096) != revision_metadata:
            return None
        return await asyncio.to_thread(thumbnails.read, cache_path)

    cached = await read_current()
    if cached is not None:
        return cached
    async with _document_capture_slots:
        cached = await read_current()
        if cached is not None:
            return cached
        try:
            pdf = await render_html_pdf(snapshot.html, first_page_only=True)
            result = await asyncio.to_thread(_printed_document_thumbnail, pdf)
            if result is not None:
                # An edit during Chromium rendering must not republish the invalidated capture.
                current = await service.item_record(document_id)
                if current is None or (current.revision, current.lock_version) != (snapshot.revision, snapshot.lock_version):
                    return None
                await asyncio.to_thread(thumbnails.write, cache_path, result)
                await asyncio.to_thread(thumbnails.write, revision_path, revision_metadata)
                return result
            return None
        except Exception as exc:
            logger.debug("Document thumbnail capture failed (error_type={})", type(exc).__name__)
            return None


def register_web_thumbnail_capture(
    capture: WebThumbnailCapture, *, html_capture: HtmlThumbnailCapture,
) -> None:
    """Inject the optional browser capability at the application composition root."""

    global _web_thumbnail_capture, _html_thumbnail_capture
    _web_thumbnail_capture = capture
    _html_thumbnail_capture = html_capture


def _printed_document_thumbnail(content: bytes) -> bytes | None:
    """Crop the top of the printed page at full page width before downsampling."""
    import pypdfium2 as pdfium  # type: ignore

    with pdfium.PdfDocument(content) as document:
        if not len(document):
            return None
        page = document[0]
        try:
            bitmap = cast(Any, page).render(scale=2)
            try:
                image = cast(Image.Image, bitmap.to_pil())
                height = round(image.width * thumbnails.MAX_SIZE[1] / thumbnails.MAX_SIZE[0])
                return thumbnails.encode(image.crop((0, 0, image.width, min(height, image.height))))
            finally:
                bitmap.close()
        finally:
            page.close()


def _reference(document_id: UUID, attachment_id: UUID) -> str:
    return f"document://{document_id}/attachments/{attachment_id}"


def _pdf_thumbnail(path: Path) -> bytes | None:
    try:
        import pypdfium2 as pdfium  # type: ignore

        document = pdfium.PdfDocument(str(path))
        try:
            if len(document) == 0:
                return None
            page = document[0]
            try:
                # pypdfium2 does not expose complete typing for its renderer.
                rendered = cast(Any, page).render(scale=2)
                return thumbnails.encode(cast(Image.Image, rendered.to_pil()))
            finally:
                page.close()
        finally:
            document.close()
    except Exception:
        return None


def _video_thumbnail(path: Path) -> bytes | None:
    """Decode one early representative video frame without scanning the whole file."""

    try:
        import av

        with av.open(str(path), mode="r") as container:
            if not container.streams.video:
                return None
            stream = container.streams.video[0]
            width = int(stream.codec_context.width or 0)
            height = int(stream.codec_context.height or 0)
            if width <= 0 or height <= 0 or width * height > 32_000_000:
                return None

            # Prefer a frame around 10% of the media, capped at five seconds,
            # so short black title frames do not dominate the preview.
            target_seconds = 0.0
            if container.duration is not None and container.duration > 0:
                duration_seconds = float(container.duration / av.time_base)
                target_seconds = min(max(duration_seconds * 0.1, 0.2), 5.0)
                container.seek(
                    int(target_seconds * av.time_base),
                    backward=True,
                    any_frame=False,
                )

            candidate: Image.Image | None = None
            for index, frame in enumerate(container.decode(video=0)):
                candidate = cast(Image.Image, cast(Any, frame).to_image())
                frame_time = frame.time
                if frame_time >= target_seconds or index >= 60:
                    return thumbnails.encode(candidate)
            return thumbnails.encode(candidate) if candidate is not None else None
    except Exception:
        return None


def _text_thumbnail(path: Path) -> bytes | None:
    try:
        text = path.read_text(encoding="utf-8")[:4_000]
    except (OSError, UnicodeError):
        return None
    image = Image.new("RGB", thumbnails.MAX_SIZE, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    y = 18
    for raw_line in text.splitlines()[:12]:
        line = raw_line.expandtabs(2)[:72]
        draw.text((20, y), line, fill="#38424f", font=font)
        y += 23
    return thumbnails.encode(image)


def _web_url(path: Path, attachment: DocumentAttachmentPublic) -> str | None:
    media_type = attachment.media_type.split(";", 1)[0].strip().casefold()
    if media_type != "text/uri-list" and not attachment.name.casefold().endswith(".url"):
        return None
    try:
        with path.open(encoding="utf-8") as source:
            content = source.read(16_000)
    except (OSError, UnicodeError):
        return None
    for line in content.splitlines():
        candidate = line.strip()
        if candidate.casefold().startswith("url="):
            candidate = candidate[4:].strip()
        if candidate.startswith("https://"):
            return candidate
    return None


def _read_html(path: Path) -> bytes | None:
    # Match Chat's bounded private HTML materialization.
    with path.open("rb") as source:
        content = source.read(runtime_settings.BROWSER_HTML_MAX_BYTES + 1)
    return content if len(content) <= runtime_settings.BROWSER_HTML_MAX_BYTES else None


async def _generate(
    *,
    reference: str,
    attachment: DocumentAttachmentPublic,
    path: Path,
    actor_agent_id: int | HumanActor,
) -> None:
    try:
        media_type = attachment.media_type.split(";", 1)[0].strip().casefold()
        web_url = await asyncio.to_thread(_web_url, path, attachment)
        if web_url is not None:
            if _web_thumbnail_capture is not None:
                # The browser writes under the target URL. Never duplicate this
                # image under the attachment URI or delete it with the shortcut.
                await _web_thumbnail_capture(actor_agent_id, web_url)
            return
        if media_type == "text/html" or attachment.name.casefold().endswith((".html", ".htm")):
            if _html_thumbnail_capture is not None:
                content = await asyncio.to_thread(_read_html, path)
                if content is not None:
                    await _html_thumbnail_capture(actor_agent_id, reference, content)
            return
        if media_type.startswith("image/"):
            content = await asyncio.to_thread(thumbnails.from_image, path)
        elif media_type.startswith("video/"):
            content = await asyncio.to_thread(_video_thumbnail, path)
        elif media_type == "application/pdf" or attachment.name.casefold().endswith(".pdf"):
            content = await asyncio.to_thread(_pdf_thumbnail, path)
        elif media_type.startswith("text/"):
            content = await asyncio.to_thread(_text_thumbnail, path)
        else:
            content = None
        if content is not None and len(content) <= thumbnails.MAX_BYTES:
            await asyncio.to_thread(thumbnails.write, thumbnails.cache_path(reference), content)
    except Exception as exc:
        logger.debug(
            "Document attachment thumbnail generation failed (error_type={})",
            type(exc).__name__,
        )


async def read_or_schedule_document_attachment_thumbnail(
    document_id: UUID,
    attachment_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
) -> bytes | None:
    """Read a cached thumbnail or start one bounded background generation."""

    attachment, path = await document_attachment_service.document_attachment_path(
        document_id,
        attachment_id,
        actor_agent_id=actor_agent_id,
    )
    reference = _reference(document_id, attachment_id)
    web_url = await asyncio.to_thread(_web_url, path, attachment)
    cache_path = thumbnails.cache_path(web_url or reference)
    cached = await asyncio.to_thread(thumbnails.read, cache_path)
    if cached is not None:
        return cached
    if reference not in _tasks:
        task = asyncio.create_task(
            _generate(
                reference=reference,
                attachment=attachment,
                path=path,
                actor_agent_id=actor_agent_id,
            ),
            name="document-attachment-thumbnail",
            context=Context(),
        )
        _tasks[reference] = task

        def forget(completed: asyncio.Task[None]) -> None:
            if _tasks.get(reference) is completed:
                _tasks.pop(reference, None)

        task.add_done_callback(forget)
    return None


async def delete_document_attachment_thumbnail(
    document_id: UUID,
    attachment_id: UUID,
) -> None:
    """Remove a cached derivative after its immutable source is deleted."""

    reference = _reference(document_id, attachment_id)
    task = _tasks.pop(reference, None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await asyncio.to_thread(thumbnails.delete, reference)


__all__ = [
    "read_document_thumbnail",
    "delete_document_attachment_thumbnail",
    "read_or_schedule_document_attachment_thumbnail",
    "register_web_thumbnail_capture",
]
