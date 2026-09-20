"""Bound buffers before allocation at HTTP boundaries requiring complete bodies."""

import asyncio
import zlib
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from .byte_budget import buffered_io_budget


async def _decoded_chunks(response: httpx.Response) -> AsyncIterator[bytes]:
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding in {"", "identity"}:
        async for chunk in response.aiter_bytes(chunk_size=65_536):
            yield chunk
        return
    if encoding not in {"gzip", "deflate"}:
        raise ValueError("Unsupported response compression")
    decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
    async for raw in response.aiter_raw(chunk_size=65_536):
        while raw:
            decoded = decoder.decompress(raw, max_length=65_536)
            raw = decoder.unconsumed_tail
            if decoded:
                yield decoded
            if decoder.unused_data:
                raise ValueError("Unexpected trailing compressed response")
    if not decoder.eof:
        raise ValueError("Incomplete compressed response")


async def read_response(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Bound decoded chunks before accumulation, including compressed responses."""
    declared = response.headers.get("content-length")
    if (
        response.headers.get("content-encoding", "identity") == "identity"
        and declared
        and declared.isdigit()
        and int(declared) > max_bytes
    ):
        raise ValueError("Provider response exceeds the size limit")
    data = bytearray()
    async for chunk in _decoded_chunks(response):
        if len(chunk) > max_bytes - len(data):
            raise ValueError("Provider response exceeds the size limit")
        data.extend(chunk)
    return bytes(data)


async def post_buffered(
    url: str,
    *,
    headers: dict[str, str],
    json: Any = None,
    content: bytes | None = None,
    params: dict[str, str] | None = None,
    max_bytes: int = 32 * 1024 * 1024,
    timeout: float = 90,
) -> bytes:
    async with buffered_io_budget.reserve(3 * max_bytes, owner=f"http:{uuid4()}"):
        async with (
            asyncio.timeout(timeout),
            httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
        ):
            async with client.stream(
                "POST",
                url,
                headers={**headers, "Accept-Encoding": "identity"},
                json=json,
                content=content,
                params=params,
            ) as response:
                response.raise_for_status()
                return await read_response(response, max_bytes=max_bytes)
