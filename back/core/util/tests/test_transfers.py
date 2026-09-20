import asyncio

import pytest

from core.util import copy_download


@pytest.mark.asyncio
async def test_copy_stops_before_writing_or_requesting_more_oversized_data(tmp_path):
    destination = tmp_path / "partial"
    consumed = []
    async def chunks():
        consumed.append(1)
        yield b"1234"
        consumed.append(2)
        yield b"5678"
        consumed.append(3)
        yield b"never"
    with pytest.raises(ValueError):
        await copy_download(chunks(), destination, max_bytes=6)
    assert consumed == [1, 2]
    assert not destination.exists()


@pytest.mark.asyncio
async def test_copy_deadline_cancels_slow_stream_and_removes_partial_file(tmp_path):
    stopped = asyncio.Event()
    async def chunks():
        try:
            yield b"first"
            await asyncio.Event().wait()
        finally:
            stopped.set()
    destination = tmp_path / "partial"
    with pytest.raises(TimeoutError):
        await copy_download(chunks(), destination, max_bytes=100, timeout_seconds=0.02)
    assert stopped.is_set() and not destination.exists()


@pytest.mark.asyncio
async def test_copy_accepts_exact_byte_budget(tmp_path):
    async def chunks():
        yield b"12"
        yield b"3456"
    destination = tmp_path / "file"
    assert await copy_download(chunks(), destination, max_bytes=6) == 6
    assert destination.read_bytes() == b"123456"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,timeout", [(0, 1), (-1, 1), (10, 0), (10, -1)])
async def test_invalid_download_limits_do_not_touch_destination(tmp_path, limit, timeout):
    async def chunks():
        pytest.fail("Invalid request consumed the source")
        yield b""
    destination = tmp_path / "existing"
    destination.write_bytes(b"preserved")
    with pytest.raises(ValueError):
        await copy_download(chunks(), destination, max_bytes=limit, timeout_seconds=timeout)
    assert destination.read_bytes() == b"preserved"


@pytest.mark.asyncio
async def test_negative_read_limit_is_rejected_before_accessing_file(tmp_path):
    from core.util import read_buffered_file
    with pytest.raises(ValueError, match="nonnegative"):
        await read_buffered_file(tmp_path / "missing", max_bytes=-1)


@pytest.mark.asyncio
async def test_buffered_read_enforces_actual_size_after_admission(tmp_path):
    from core.util import read_buffered_file
    path = tmp_path / "growing"
    path.write_bytes(b"123456")
    with pytest.raises(ValueError, match="admitted byte limit"):
        await read_buffered_file(path, max_bytes=5)
    assert await read_buffered_file(path, max_bytes=6) == b"123456"
