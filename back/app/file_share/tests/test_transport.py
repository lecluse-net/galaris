from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.file_share.transport import transfer


class StreamingTransport:
    def __init__(self, content: bytes = b"") -> None:
        self.content = content
        self.download_called = False
        self.upload_called = False

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024) -> int:
        self.download_called = True
        raise AssertionError("temporary-file fallback must not be used")

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        self.upload_called = True
        raise AssertionError("temporary-file fallback must not be used")

    async def iter_bytes(
        self,
        remote: str,
        *,
        target: str = "",
        offset: int = 0,
    ) -> AsyncIterator[bytes]:
        yield self.content[offset:]

    async def upload_stream(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        *,
        target: str = "",
    ) -> tuple[str, int]:
        parts = [chunk async for chunk in chunks]
        self.content = b"".join(parts)
        return f"{target}/{filename}".strip("/"), len(self.content)


@pytest.mark.asyncio
async def test_transfer_streams_directly_between_capable_transports() -> None:
    source = StreamingTransport(b"large-binary-payload")
    destination = StreamingTransport()

    location, size = await transfer(
        source,
        "video.bin",
        destination,
        dest_target="Downloads",
    )

    assert location == "Downloads/video.bin"
    assert size == len(b"large-binary-payload")
    assert destination.content == source.content
    assert source.download_called is False
    assert destination.upload_called is False


@pytest.mark.asyncio
async def test_direct_stream_read_failure_does_not_claim_destination_is_untouched() -> None:
    class InterruptedSource(StreamingTransport):
        async def iter_bytes(self, remote, *, target="", offset=0):
            yield b"partial"
            raise ConnectionError("source disconnected during streaming")

    class Destination(StreamingTransport):
        async def upload_stream(self, chunks, filename, *, target=""):
            async for chunk in chunks:
                self.content += chunk
            return filename, len(self.content)

    destination = Destination()
    # A streaming destination may already contain bytes when the source fails.
    # This must remain an uncertain effect, never a pre-upload rejection.
    with pytest.raises(ConnectionError):
        await transfer(InterruptedSource(), "report.bin", destination)
    assert destination.content == b"partial"
