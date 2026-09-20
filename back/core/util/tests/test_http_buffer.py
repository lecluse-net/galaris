import asyncio
import gzip
import zlib

import httpx
import pytest

from core.util import http_buffer


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_stream_without_declared_length_is_bounded_before_append():
    stream = Stream([b"a" * 65536, b"b" * 65536])
    response = httpx.Response(200, stream=stream)
    with pytest.raises(ValueError, match="size limit"):
        await http_buffer.read_response(response, max_bytes=65536)


@pytest.mark.asyncio
async def test_compressed_bomb_is_rejected_with_bounded_decode_chunks():
    response = httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Stream([gzip.compress(b"a" * 1000000)]))
    with pytest.raises(ValueError, match="size limit"):
        await http_buffer.read_response(response, max_bytes=100)


@pytest.mark.asyncio
async def test_small_compressed_response_is_supported():
    response = httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Stream([gzip.compress(b"audio")]))
    assert await http_buffer.read_response(response, max_bytes=100) == b"audio"


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding,content", [("identity", b"audio"), ("", b"audio"),
    ("gzip", gzip.compress(b"audio")), ("deflate", zlib.compress(b"audio"))])
async def test_supported_encodings_preserve_exact_payload_at_the_limit(encoding, content):
    response = httpx.Response(200, headers={"content-encoding": encoding}, stream=Stream([content]))
    assert await http_buffer.read_response(response, max_bytes=5) == b"audio"


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding,content,reason", [
    ("br", b"unsupported", "Unsupported"),
    ("gzip", gzip.compress(b"audio")[:-4], "Incomplete"),
    ("gzip", gzip.compress(b"audio") + b"trailing", "trailing"),
    ("deflate", zlib.compress(b"audio")[:-2], "Incomplete"),
])
async def test_invalid_compressed_provider_body_cannot_be_accepted_as_media(monkeypatch, encoding, content, reason):
    stream = Stream([content])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-encoding": encoding}, stream=stream))
    original = httpx.AsyncClient
    monkeypatch.setattr(http_buffer.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(ValueError, match=reason):
        await http_buffer.post_buffered("https://media.test", headers={}, max_bytes=100)
    assert stream.closed and http_buffer.buffered_io_budget.used == 0


@pytest.mark.asyncio
async def test_oversized_declared_body_is_rejected_without_reading():
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("An oversized declared body must not be downloaded")
            yield b""
    response = httpx.Response(200, headers={"content-length": "1000"}, stream=Unreadable())
    with pytest.raises(ValueError, match="size limit"):
        await http_buffer.read_response(response, max_bytes=10)


@pytest.mark.asyncio
async def test_trickle_has_total_deadline_and_closes_transport(monkeypatch):
    stream = Stream([b"a"] * 100, delay=0.01)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    original = httpx.AsyncClient
    monkeypatch.setattr(http_buffer.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(TimeoutError):
        await http_buffer.post_buffered("https://speech.test", headers={}, max_bytes=100, timeout=0.03)
    assert stream.closed
    assert http_buffer.buffered_io_budget.used == 0
