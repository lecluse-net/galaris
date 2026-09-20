from __future__ import annotations

from pathlib import Path
import asyncio
import threading
from uuid import uuid4

import pytest

from app.memory.contracts import ResourceNotFoundError, ResourceTooLargeError
from app.memory.storage import NativeFileStorage


@pytest.mark.asyncio
async def test_symlinked_bucket_cannot_escape_storage_root(tmp_path):
    from app.memory.contracts import ResourceStorageError
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    resource_id = str(uuid4())
    (outside / resource_id).write_bytes(b"private")
    (root / resource_id[:2]).symlink_to(outside, target_is_directory=True)
    storage = NativeFileStorage(root)
    for operation in (storage.read, storage.path_for_read, storage.delete):
        with pytest.raises(ResourceStorageError, match="escapes"):
            await operation(resource_id)
    assert (outside / resource_id).read_bytes() == b"private"


@pytest.mark.asyncio
async def test_failed_atomic_replacement_preserves_original_and_removes_partial(tmp_path, monkeypatch):
    from app.memory import storage as module
    storage = NativeFileStorage(tmp_path)
    resource_id = await storage.create(b"original")
    def unavailable(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(module.os, "replace", unavailable)
    with pytest.raises(OSError):
        await storage.update(resource_id, b"new revision")
    assert await storage.read(resource_id) == b"original"
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.asyncio
async def test_stream_limit_rejection_keeps_existing_resources(tmp_path):
    storage = NativeFileStorage(tmp_path, max_bytes=4)
    existing = await storage.create(b"kept")
    async def chunks():
        yield b"1234"
        yield b"5"
    with pytest.raises(ResourceTooLargeError):
        await storage.create_stream(chunks())
    assert await storage.read(existing) == b"kept"
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1
    assert (await storage.path_for_read(existing)).read_bytes() == b"kept"
    missing = str(uuid4())
    with pytest.raises(ResourceNotFoundError):
        await storage.path_for_read(missing)
    with pytest.raises(ResourceNotFoundError):
        await storage.update(missing, b"new")


@pytest.mark.asyncio
async def test_existing_storage_uses_changed_resource_limit_and_keeps_saved_content(tmp_path, monkeypatch):
    from core.params import runtime_settings
    storage = NativeFileStorage(tmp_path)
    monkeypatch.setattr(runtime_settings, 'MEMORY_RESOURCE_MAX_BYTES', 2048)
    existing = await storage.create(b'x' * 1500)
    monkeypatch.setattr(runtime_settings, 'MEMORY_RESOURCE_MAX_BYTES', 1024)
    assert await storage.read(existing) == b'x' * 1500
    with pytest.raises(ResourceTooLargeError):
        await storage.create(b'x' * 1500)
    async def chunks():
        yield b'x' * 1024
        yield b'x'
    with pytest.raises(ResourceTooLargeError):
        await storage.create_stream(chunks())
    monkeypatch.setattr(runtime_settings, 'MEMORY_RESOURCE_MAX_BYTES', 2048)
    assert await storage.read(await storage.create(b'x' * 1500)) == b'x' * 1500
    assert not list(tmp_path.rglob('*.part'))


@pytest.mark.asyncio
async def test_deleting_one_resource_does_not_remove_its_bucket_peers(tmp_path, monkeypatch):
    from app.memory import storage as module
    from uuid import UUID
    identifiers = iter([UUID("aa000000-0000-0000-0000-000000000001"), UUID("aa000000-0000-0000-0000-000000000002")])
    monkeypatch.setattr(module, "uuid4", lambda: next(identifiers))
    storage = NativeFileStorage(tmp_path)
    first, second = await storage.create(b"first"), await storage.create(b"second")
    assert await storage.delete(first)
    assert await storage.read(second) == b"second"


def test_storage_registry_requires_explicit_known_provider(tmp_path, monkeypatch):
    from app.memory import storage as module
    from app.memory.contracts import ResourceStorageError
    monkeypatch.setattr(module, "_providers", {})
    monkeypatch.setattr(type(module.settings), "GALARIS_MEMORY_ROOT", str(tmp_path))
    assert module.registered_storage_codes() == ("native",)
    assert isinstance(module.get_storage(), NativeFileStorage)
    with pytest.raises(ResourceStorageError, match="Unknown"):
        module.get_storage("missing")
    from types import SimpleNamespace
    with pytest.raises(ValueError, match="non-empty"):
        module.register_storage(SimpleNamespace(code=" "))


@pytest.mark.asyncio
async def test_native_storage_round_trip_is_atomic_and_opaque(tmp_path: Path) -> None:
    storage = NativeFileStorage(tmp_path, max_bytes=20)

    resource_id = await storage.create(b"first")

    assert "/" not in resource_id
    assert await storage.read(resource_id) == b"first"
    await storage.update(resource_id, b"second")
    assert await storage.read(resource_id) == b"second"
    assert await storage.delete(resource_id)
    assert not await storage.delete(resource_id)
    with pytest.raises(ResourceNotFoundError):
        await storage.read(resource_id)


@pytest.mark.asyncio
async def test_native_storage_rejects_oversize_and_non_opaque_ids(tmp_path: Path) -> None:
    storage = NativeFileStorage(tmp_path, max_bytes=4)

    with pytest.raises(ResourceTooLargeError):
        await storage.create(b"12345")
    with pytest.raises(ResourceNotFoundError):
        await storage.read("../../secret")

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_cancelled_creation_drains_the_writer_and_removes_unpublished_file(tmp_path, monkeypatch):
    storage = NativeFileStorage(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = storage._atomic_write

    def delayed(path, content):
        entered.set()
        assert release.wait(5)
        original(path, content)

    monkeypatch.setattr(storage, "_atomic_write", delayed)
    operation = asyncio.create_task(storage.create(b"unpublished"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        operation.cancel()
        await asyncio.sleep(0)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.asyncio
async def test_cancelled_stream_keeps_existing_resources_and_removes_temporary(tmp_path):
    storage = NativeFileStorage(tmp_path)
    previous = await storage.create(b"previous revision")
    entered = asyncio.Event()

    async def chunks():
        yield b"first chunk"
        entered.set()
        await asyncio.Event().wait()

    operation = asyncio.create_task(storage.create_stream(chunks()))
    await entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert await storage.read(previous) == b"previous revision"
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["write", "flush", "fsync", "replace", "_sync_directory"])
async def test_stream_cancellation_drains_each_blocking_phase(tmp_path, monkeypatch, phase):
    from app.memory import storage as module
    from core.util import complete_io
    entered, release = threading.Event(), threading.Event()

    async def controlled(operation, *args, **kwargs):
        if operation.__name__ != phase:
            return await complete_io(operation, *args, **kwargs)
        def delayed():
            entered.set()
            assert release.wait(5)
            return operation(*args, **kwargs)
        return await complete_io(delayed)

    monkeypatch.setattr(module, "complete_io", controlled)
    storage = NativeFileStorage(tmp_path)
    async def chunks():
        yield b"audio"
    pending = asyncio.create_task(storage.create_stream(chunks()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
