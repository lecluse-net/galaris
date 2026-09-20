"""Bounded streaming primitives shared by adapters and resource providers."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from .thread_io import complete_io

DEFAULT_DOWNLOAD_BYTES = 512 * 1024 * 1024


async def copy_download(
    chunks: AsyncIterator[bytes],
    destination: Path,
    *,
    max_bytes: int = DEFAULT_DOWNLOAD_BYTES,
    timeout_seconds: float = 120,
) -> int:
    """Count decoded bytes before writing and remove partial files on any failure."""
    if max_bytes <= 0 or timeout_seconds <= 0:
        raise ValueError("Download limits must be positive")
    size = 0
    try:
        async with asyncio.timeout(timeout_seconds):
            with destination.open("wb") as output:
                async for chunk in chunks:
                    if len(chunk) > max_bytes - size:
                        raise ValueError(
                            f"Resource exceeds the {max_bytes}-byte materialization limit"
                        )
                    # A bounded write avoids blocking the event loop; cancellation must
                    # finish that write before closing its descriptor.
                    await complete_io(output.write, chunk)
                    size += len(chunk)
        return size
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


async def read_buffered_file(path: Path, *, max_bytes: int) -> bytes:
    """Bound the actual read, including a file that grows after stat/admission."""
    if max_bytes < 0:
        raise ValueError("File byte limit must be nonnegative")

    def read() -> bytes:
        with path.open("rb") as source:
            content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("File exceeds its admitted byte limit")
        return content

    return await complete_io(read)
