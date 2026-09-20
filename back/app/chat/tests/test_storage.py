from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import UploadFile

from app.chat import storage
from core.params.runtime_settings import runtime_settings
from core.settings import settings


@pytest.mark.asyncio
async def test_upload_uses_uuid_path_and_round_trips(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = str(tmp_path)
    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", root)
    file_id = uuid4()
    upload = UploadFile(
        filename="../../unsafe.txt",
        file=BytesIO(b"bounded payload"),
        headers={"content-type": "text/plain"},
    )

    path, size, mime_type = await storage.store_upload(upload, file_id)

    assert path == storage.attachment_path(file_id)
    assert path.name == file_id.hex
    assert "unsafe" not in str(path)
    assert size == 15
    assert mime_type == "text/plain"
    assert await storage.read_bytes(file_id) == b"bounded payload"


@pytest.mark.asyncio
async def test_upload_rejects_active_content(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    upload = UploadFile(
        filename="payload.svg",
        file=BytesIO(b"<svg/>"),
        headers={"content-type": "image/svg+xml"},
    )

    with pytest.raises(ValueError, match="active or executable"):
        await storage.store_upload(upload, uuid4())


@pytest.mark.asyncio
async def test_upload_rejects_active_content_with_misleading_mime(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    upload = UploadFile(
        filename="innocent.txt",
        file=BytesIO(b"<!doctype html><script>alert(1)</script>"),
        headers={"content-type": "text/plain"},
    )

    with pytest.raises(ValueError, match="active or executable"):
        await storage.store_upload(upload, uuid4())


@pytest.mark.asyncio
async def test_upload_enforces_per_file_limit(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    monkeypatch.setattr(runtime_settings, "MESSENGER_CONTENT_MAX_MB", 1)
    upload = UploadFile(
        filename="large.bin",
        file=BytesIO(b"x" * 1_000_001),
        headers={"content-type": "application/octet-stream"},
    )
    file_id = uuid4()

    with pytest.raises(ValueError, match="exceeds"):
        await storage.store_upload(upload, file_id)
    assert not storage.attachment_path(file_id).exists()


@pytest.mark.asyncio
async def test_upload_rejects_declared_oversized_file_before_streaming(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    monkeypatch.setattr(runtime_settings, "MESSENGER_CONTENT_MAX_MB", 1)
    upload = UploadFile(
        filename="large-video.mkv",
        file=BytesIO(b"not-read"),
        size=1_000_001,
        headers={"content-type": "video/x-matroska"},
    )
    file_id = uuid4()

    with pytest.raises(storage.AttachmentTooLargeError) as raised:
        await storage.store_upload(upload, file_id)

    assert raised.value.limit == 1_000_000
    assert upload.file.tell() == 0
    assert not storage.attachment_path(file_id).exists()


@pytest.mark.asyncio
async def test_store_path_uses_delivered_filename_for_mime_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    source = tmp_path / "materialized-output"
    source.write_bytes(b"not-a-real-jpeg")
    file_id = uuid4()

    _path, size, mime_type = await storage.store_path(
        source,
        file_id,
        filename="generated-image.jpg",
    )

    assert size == len(b"not-a-real-jpeg")
    assert mime_type == "image/jpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "disk_full", "disconnect"])
async def test_failed_upload_never_publishes_or_leaves_partial_file(tmp_path, monkeypatch, failure):
    import asyncio
    import errno
    from unittest.mock import AsyncMock, Mock

    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path))
    upload = UploadFile(filename="x.txt", file=BytesIO(b""))
    error = asyncio.CancelledError() if failure == "cancel" else OSError(errno.ENOSPC, "full") if failure == "disk_full" else ConnectionError("disconnected")
    if failure == "disk_full":
        monkeypatch.setattr(upload, "read", AsyncMock(side_effect=[b"first chunk", b""]))
        monkeypatch.setattr(storage.os, "fsync", Mock(side_effect=error))
    else:
        monkeypatch.setattr(upload, "read", AsyncMock(side_effect=[b"first chunk", error]))
    file_id = uuid4()
    with pytest.raises(type(error)):
        await storage.store_upload(upload, file_id)
    assert not storage.attachment_path(file_id).exists()
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.asyncio
async def test_concurrent_uploads_cannot_overrun_capacity(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path))
    monkeypatch.setattr(runtime_settings, "GALARIS_INTERNAL_MESSENGER_MAX_BYTES", 1_000_000)
    results = await asyncio.gather(*(
        storage.store_upload(UploadFile(filename="x.txt", file=BytesIO(b"x" * 700_000)), uuid4())
        for _ in range(4)
    ), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert all(not isinstance(result, Exception) or isinstance(result, storage.AttachmentStorageFullError) for result in results)
    assert storage._stored_bytes() == 700_000


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["write", "fsync"])
async def test_cancellation_waits_for_the_inflight_disk_write_before_cleanup(tmp_path, monkeypatch, stage):
    import asyncio
    import threading

    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    operation = storage._stored_bytes if stage == "write" else storage.os.fsync

    def delayed_operation(*args):
        entered.set()
        assert release.wait(timeout=5)
        return operation(*args)

    if stage == "write":
        monkeypatch.setattr(storage, "_stored_bytes", delayed_operation)
    else:
        monkeypatch.setattr(storage.os, "fsync", delayed_operation)
    file_id = uuid4()
    pending = asyncio.create_task(storage.store_upload(
        UploadFile(filename="x.txt", file=BytesIO(b"pending write")), file_id,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not storage.attachment_path(file_id).exists()
    assert not list(tmp_path.rglob("*.part"))
