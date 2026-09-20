"""Private, bounded binary storage for native Messenger attachments."""

from __future__ import annotations

import asyncio
import fcntl
import mimetypes
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from loguru import logger

from core.params import runtime_settings
from core.settings import settings


_CHUNK_SIZE = 1024 * 1024
_ACTIVE_MIME_TYPES = {
    "image/svg+xml",
    "text/html",
    "application/xhtml+xml",
    "application/javascript",
    "text/javascript",
    "application/x-msdownload",
    "application/x-sh",
}


class AttachmentStorageError(ValueError):
    """Expected, user-facing failure while storing one native Chat attachment."""


class AttachmentTooLargeError(AttachmentStorageError):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"The attachment exceeds the {limit}-byte limit.")


class AttachmentStorageFullError(AttachmentStorageError):
    """The configured global attachment capacity has been reached."""


class UnsupportedAttachmentTypeError(AttachmentStorageError):
    """The attachment contains an active or executable payload."""


def root() -> Path:
    return Path(settings.GALARIS_INTERNAL_MESSENGER_ROOT).resolve()


def attachment_path(file_id: UUID) -> Path:
    value = file_id.hex
    return root() / "attachments" / value[:2] / value


def _validate_mime(mime_type: str) -> str:
    normalized = (mime_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if normalized in _ACTIVE_MIME_TYPES:
        raise UnsupportedAttachmentTypeError(
            "This active or executable file type is not accepted."
        )
    return normalized


def _validated_content_type(
    declared_type: str,
    filename: str,
    prefix: bytes,
) -> str:
    """Reject active content even when its client-declared MIME type is misleading."""

    declared = _validate_mime(declared_type)
    guessed = _validate_mime(mimetypes.guess_type(filename)[0] or declared)
    normalized = prefix[:8_192].lstrip().lower()
    if (
        normalized.startswith((b"<!doctype html", b"<html", b"<script", b"#!"))
        or normalized.startswith(b"<svg")
        or (normalized.startswith(b"<?xml") and b"<svg" in normalized)
    ):
        raise UnsupportedAttachmentTypeError(
            "This active or executable file content is not accepted."
        )
    return guessed if declared == "application/octet-stream" else declared


def _stored_bytes() -> int:
    total = 0
    storage_root = root()
    if not storage_root.exists():
        return 0
    for directory, _names, files in os.walk(storage_root, followlinks=False):
        parent = Path(directory)
        for name in files:
            path = parent / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
    return total


async def write_bounded_chunk(handle: BinaryIO, chunk: bytes) -> None:
    """Account for attachments, previews and partial uploads across workers.

    Hold the filesystem lock only during accounting and writing, never while
    awaiting the uploader. Finish an in-flight write before cancellation cleanup.
    """
    def write() -> None:
        with (root() / ".capacity.lock").open("ab") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if _stored_bytes() + len(chunk) > runtime_settings.GALARIS_INTERNAL_MESSENGER_MAX_BYTES:
                raise AttachmentStorageFullError("Chat attachment storage is full.")
            handle.write(chunk)
            handle.flush()

    await _finish_io(write)


async def sync_upload(handle: BinaryIO) -> None:
    """Keep the descriptor open until an in-flight fsync has actually finished."""
    def sync() -> None:
        handle.flush()
        os.fsync(handle.fileno())

    await _finish_io(sync)


async def _finish_io(operation: Callable[[], None]) -> None:
    pending = asyncio.create_task(asyncio.to_thread(operation))
    try:
        await asyncio.shield(pending)
    except asyncio.CancelledError:
        try:
            await pending
        finally:
            raise


async def store_upload(upload: UploadFile, file_id: UUID) -> tuple[Path, int, str]:
    """Stream one upload to its final UUID path with a strict configured bound."""

    declared_type = upload.content_type or ""
    limit = runtime_settings.messenger_content_max_bytes
    if upload.size is not None and upload.size > limit:
        raise AttachmentTooLargeError(limit)
    destination = attachment_path(file_id)
    staging = root() / ".staging" / f"{file_id.hex}-{uuid4().hex}.part"
    await asyncio.to_thread(staging.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
    size = 0
    prefix = bytearray()
    try:
        with staging.open("xb") as handle:
            while chunk := await upload.read(_CHUNK_SIZE):
                if len(prefix) < 8_192:
                    prefix.extend(chunk[: 8_192 - len(prefix)])
                size += len(chunk)
                if size > limit:
                    raise AttachmentTooLargeError(limit)
                await write_bounded_chunk(handle, chunk)
            await sync_upload(handle)
        mime_type = _validated_content_type(
            declared_type,
            upload.filename or "",
            bytes(prefix),
        )
        os.replace(staging, destination)
    except BaseException:
        await asyncio.to_thread(staging.unlink, missing_ok=True)
        raise
    return destination, size, mime_type


async def store_path(
    source: Path,
    file_id: UUID,
    *,
    filename: str | None = None,
) -> tuple[Path, int, str]:
    """Copy a trusted agent-produced path through the same bounded storage path."""

    if not source.is_file() or source.is_symlink():
        raise ValueError("The attachment source must be a regular file.")
    with source.open("rb") as reader:
        return await store_upload(UploadFile(
            filename=filename or source.name,
            file=reader,
            size=source.stat().st_size,
        ), file_id)


async def read_bytes(file_id: UUID) -> bytes:
    path = attachment_path(file_id)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(file_id)
    limit = runtime_settings.messenger_content_max_bytes
    if path.stat().st_size > limit:
        raise AttachmentTooLargeError(limit)
    return await asyncio.to_thread(path.read_bytes)


async def copy_to(file_id: UUID, destination: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
    from core.util import copy_download
    source = attachment_path(file_id)
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(file_id)

    async def chunks():
        with source.open("rb") as reader:
            while chunk := reader.read(min(64 * 1024, max_bytes + 1)):
                yield chunk

    return await copy_download(chunks(), destination, max_bytes=max_bytes)


async def discard(file_id: UUID) -> None:
    await asyncio.to_thread(attachment_path(file_id).unlink, missing_ok=True)


async def reconcile_storage() -> None:
    """Remove stale staging files and old blobs without a canonical file row."""

    from core.database import get_db_session
    from app.messenger import live_internal_file_ids

    async with get_db_session():
        live_ids = await live_internal_file_ids()
    now = time.time()
    removed = 0
    for staging_root in (root() / ".staging", root() / "staging"):
        if staging_root.exists():
            for path in staging_root.glob("*.part"):
                try:
                    if not path.is_symlink() and now - path.stat().st_mtime > 3_600:
                        path.unlink(missing_ok=True)
                        removed += 1
                except FileNotFoundError:
                    continue
    attachments_root = root() / "attachments"
    if attachments_root.exists():
        for path in attachments_root.glob("*/*"):
            try:
                file_id = UUID(path.name)
                if (
                    not path.is_symlink()
                    and file_id not in live_ids
                    and now - path.stat().st_mtime > 86_400
                ):
                    path.unlink(missing_ok=True)
                    removed += 1
            except (FileNotFoundError, ValueError):
                continue
    if removed:
        logger.info("Chat storage reconciled: removed={}", removed)


__all__ = [
    "AttachmentStorageError",
    "AttachmentStorageFullError",
    "AttachmentTooLargeError",
    "UnsupportedAttachmentTypeError",
    "attachment_path",
    "copy_to",
    "discard",
    "read_bytes",
    "reconcile_storage",
    "root",
    "store_path",
    "store_upload",
]
