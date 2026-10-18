"""Bounded HTTP byte-range reads, including servers ignoring Range."""

from collections.abc import AsyncIterator
import re

import httpx


async def iter_http_range(response: httpx.Response, *, offset: int, length: int) -> AsyncIterator[bytes]:
    response.raise_for_status()
    skip = offset
    if response.headers.get("content-encoding", "identity") != "identity":
        raise ValueError("Byte ranges require an uncompressed representation")
    if response.status_code == 206:
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", response.headers.get("content-range", ""))
        if match is None or int(match[1]) != offset or int(match[2]) < offset + length - 1:
            raise ValueError("Provider returned an inconsistent byte range")
        skip = 0
    elif response.status_code != 200:
        raise ValueError("Provider refused the byte range")
    remaining = length
    async for chunk in response.aiter_bytes(64 * 1024):
        if skip:
            ignored = min(skip, len(chunk))
            skip -= ignored
            chunk = chunk[ignored:]
        if chunk:
            selected = chunk[:remaining]
            remaining -= len(selected)
            yield selected
            if not remaining:
                return
    if remaining:
        raise OSError("Provider truncated the requested byte range")
