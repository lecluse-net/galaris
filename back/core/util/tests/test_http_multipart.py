"""Multipart disk handles remain scoped even when a request is interrupted."""

import asyncio
from pathlib import Path

import httpx
import pytest

from core.util import post_multipart_file


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ConnectError, asyncio.CancelledError])
async def test_multipart_upload_closes_disk_source_on_interruption(tmp_path: Path, monkeypatch, failure):
    source = tmp_path / "synthetic.ogg"
    source.write_bytes(b"Synthetic audio")
    handles = []
    original_open = Path.open

    def opened(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        handles.append(handle)
        return handle

    async def interrupted(request):
        assert b"Synthetic audio" in await request.aread()
        raise failure("Synthetic interruption")

    monkeypatch.setattr(Path, "open", opened)
    async with httpx.AsyncClient(transport=httpx.MockTransport(interrupted)) as client:
        with pytest.raises(failure):
            await post_multipart_file(client, "https://speech.example.test/transcribe", source,
                filename="synthetic.ogg", mime_type="audio/ogg", data={"language": "fr"}, headers={})
    assert handles and all(handle.closed for handle in handles)
