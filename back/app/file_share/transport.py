"""Standard streaming file-exchange interface.

Compatible services implement two primitives: download a remote reference to a local file and
upload a local file. Downloads enforce their caller's byte budget while streaming.
``target`` carries service-specific context such as a folder, page, workspace,
or messaging room.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from loguru import logger
from app.tools.contracts import ToolCallRejectedError
from core.util import DEFAULT_DOWNLOAD_BYTES
from .file_contracts import FileEntry

# Shared chunk size for transports that implement their own streaming.
CHUNK_SIZE = 1 << 20


@runtime_checkable
class FileTransport(Protocol):
    """Service capable of streaming file downloads and uploads."""

    async def download_to(
        self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES
    ) -> int:
        """Download ``remote`` to local ``dest`` and return the byte count."""
        ...

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Upload local ``src`` under ``filename`` and return its remote location."""
        ...


@runtime_checkable
class ShareableFileTransport(FileTransport, Protocol):
    """File transport able to create a public or user-facing share."""

    async def share(
        self,
        remote: str,
        permissions: int = 1,
        share_with: str | None = None,
    ) -> str: ...


@runtime_checkable
class StreamingFileTransport(Protocol):
    """Optional direct-streaming extension with bounded memory."""

    def iter_bytes(
        self,
        remote: str,
        *,
        target: str = "",
        offset: int = 0,
    ) -> AsyncIterator[bytes]: ...

    async def upload_stream(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        *,
        target: str = "",
    ) -> tuple[str, int]: ...


@runtime_checkable
class VersionedFileTransport(Protocol):
    """Optional HTTP-style optimistic concurrency, owned by the provider."""

    async def download_versioned(
        self, remote: str, dest: Path, *, max_bytes: int = DEFAULT_DOWNLOAD_BYTES
    ) -> FileEntry: ...

    async def upload_conditional(
        self,
        src: Path,
        filename: str,
        *,
        target: str = "",
        overwrite: bool,
        expected_etag: str | None = None,
    ) -> str: ...


async def upload_file(
    transport: FileTransport,
    src: Path,
    filename: str,
    *,
    target: str = "",
    overwrite: bool = True,
    expected_etag: str | None = None,
) -> str:
    if isinstance(transport, VersionedFileTransport):
        return await transport.upload_conditional(
            src,
            filename,
            target=target,
            overwrite=overwrite,
            expected_etag=expected_etag,
        )
    if expected_etag is not None:
        raise NotImplementedError("This provider does not support ETag preconditions.")
    return await transport.upload_from(src, filename, target=target)


async def transfer(
    source: FileTransport,
    source_remote: str,
    dest: FileTransport,
    *,
    source_target: str = "",
    dest_target: str = "",
    filename: str = "",
    overwrite: bool = True,
) -> tuple[str, int]:
    """Stream a file between transports and return destination location and byte count."""
    name = filename or Path(source_remote).name or "transfer.bin"
    if (
        isinstance(source, StreamingFileTransport)
        and isinstance(dest, StreamingFileTransport)
        and not isinstance(dest, VersionedFileTransport)
    ):
        location, size = await dest.upload_stream(
            source.iter_bytes(source_remote, target=source_target),
            name,
            target=dest_target,
        )
        logger.info(
            "file_share.transfer: {} bytes streamed {} -> {} ({})",
            size,
            source_remote or "?",
            dest.__class__.__name__,
            location,
        )
        return location, size

    fd, tmp_name = tempfile.mkstemp(prefix="galaris_xfer_")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        try:
            size = await source.download_to(source_remote, tmp_path, target=source_target)
        except Exception as exc:
            # Only the disposable staging file can have changed: no destination
            # call has started. Direct streaming above cannot make this guarantee.
            raise ToolCallRejectedError(
                "The source download failed before any destination upload."
            ) from exc
        name = filename or Path(source_remote).name or tmp_path.name
        location = await upload_file(dest, tmp_path, name, target=dest_target, overwrite=overwrite)
        logger.info(
            "file_share.transfer: {} bytes {} -> {} ({})",
            size,
            source_remote or "?",
            dest.__class__.__name__,
            location,
        )
        return location, size
    finally:
        tmp_path.unlink(missing_ok=True)
