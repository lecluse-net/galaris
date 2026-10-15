"""Multipart file uploads with scoped ownership of disk handles."""

from contextlib import nullcontext
from pathlib import Path

import httpx


async def post_multipart_file(
    client: httpx.AsyncClient,
    url: str,
    source: bytes | Path,
    *,
    filename: str,
    mime_type: str,
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    """Stream disk sources and close their handles on success, failure or cancellation."""
    with source.open("rb") if isinstance(source, Path) else nullcontext(source) as upload:
        return await client.post(
            url,
            data=data,
            files={"file": (filename, upload, mime_type)},
            headers=headers,
        )
