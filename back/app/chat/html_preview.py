"""Short-lived capability URLs for isolated generated HTML previews."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from core.params import runtime_settings
from core.settings import settings

from .storage import sync_upload, write_bounded_chunk


_CHUNK_SIZE = 1024 * 1024
TTL_SECONDS = 60 * 60
_HTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}


class HtmlPreviewError(ValueError):
    """Expected rejection while creating a temporary HTML preview."""


class HtmlPreviewTooLargeError(HtmlPreviewError):
    """The submitted preview exceeds the configured Messenger content limit."""


def root() -> Path:
    return Path(settings.GALARIS_INTERNAL_MESSENGER_ROOT).resolve() / ".html-previews"


def path_for(ticket: UUID) -> Path:
    return root() / ticket.hex


async def cleanup_expired(*, now: float | None = None) -> None:
    """Delete expired capability files without following links."""

    directory = root()
    reference = time.time() if now is None else now

    def cleanup() -> None:
        if not directory.is_dir() or directory.is_symlink():
            return
        for path in directory.iterdir():
            try:
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and reference - path.stat().st_mtime > TTL_SECONDS
                ):
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue

    await asyncio.to_thread(cleanup)


async def store(upload: UploadFile) -> UUID:
    """Store one bounded HTML payload behind an unguessable temporary ticket."""

    media_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    filename = (upload.filename or "").lower()
    if media_type not in _HTML_MEDIA_TYPES and not filename.endswith((".html", ".htm", ".xhtml")):
        raise HtmlPreviewError("The preview payload must be HTML.")
    limit = runtime_settings.messenger_content_max_bytes
    if upload.size is not None and upload.size > limit:
        raise HtmlPreviewTooLargeError(f"The preview exceeds the {limit}-byte limit.")
    await cleanup_expired()
    directory = root()
    ticket = uuid4()
    destination = path_for(ticket)
    staging = directory / f".{ticket.hex}.part"
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True, mode=0o700)
    size = 0
    try:
        with staging.open("xb") as handle:
            while chunk := await upload.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > limit:
                    raise HtmlPreviewTooLargeError(f"The preview exceeds the {limit}-byte limit.")
                await write_bounded_chunk(handle, chunk)
            await sync_upload(handle)
        os.replace(staging, destination)
    except BaseException:
        await asyncio.to_thread(staging.unlink, missing_ok=True)
        raise
    return ticket


async def resolve(ticket: UUID, *, now: float | None = None) -> Path | None:
    """Resolve a live capability ticket to its regular file."""

    path = path_for(ticket)
    reference = time.time() if now is None else now

    def inspect() -> Path | None:
        try:
            if not path.is_file() or path.is_symlink():
                return None
            if reference - path.stat().st_mtime > TTL_SECONDS:
                path.unlink(missing_ok=True)
                return None
            return path
        except FileNotFoundError:
            return None

    return await asyncio.to_thread(inspect)


__all__ = [
    "HtmlPreviewError",
    "HtmlPreviewTooLargeError",
    "TTL_SECONDS",
    "cleanup_expired",
    "path_for",
    "resolve",
    "root",
    "store",
]
