import os
import time

import pytest

from app.memory.storage import NativeFileStorage
from app.memory.storage_reconciliation import preview_native_orphans, remove_reviewed_orphans


@pytest.mark.asyncio
async def test_orphan_cleanup_requires_review_age_and_unchanged_content(db, tmp_path):
    storage = NativeFileStorage(tmp_path)
    old = await storage.create(b"orphan")
    fresh = await storage.create(b"new")
    old_path = await storage.path_for_read(old)
    os.utime(old_path, (time.time() - 172800, time.time() - 172800))
    review, _ = await preview_native_orphans(root=tmp_path)
    assert [item.resource_id for item in review] == [old]
    with pytest.raises(ValueError, match="Stop application writers"):
        await remove_reviewed_orphans(review, root=tmp_path)
    await storage.update(old, b"changed")
    assert await remove_reviewed_orphans(review, root=tmp_path, quiescent=True) == 0
    assert await storage.read(fresh) == b"new"
    os.utime(old_path, (time.time() - 172800, time.time() - 172800))
    review, _ = await preview_native_orphans(root=tmp_path)
    assert await remove_reviewed_orphans(review, root=tmp_path, quiescent=True) == 1


@pytest.mark.asyncio
async def test_reconciliation_keeps_current_and_historical_document_files(db, agents, memory_storage):
    from app.memory import service
    from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload

    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agents[0].id, title="Retained", payload=MemoryPayload(text="first")))
    await service.update_item(item.id, MemoryItemUpdate(payload=MemoryPayload(text="second")), actor_agent_id=agents[0].id)
    for path in memory_storage.rglob("*"):
        if path.is_file():
            os.utime(path, (time.time() - 172800, time.time() - 172800))
    review, _ = await preview_native_orphans(root=memory_storage)
    assert review == []
