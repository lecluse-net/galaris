import asyncio

import pytest
from sqlalchemy import select

from app.memory import service
from app.memory.models import MemoryItem
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.storage import get_storage


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_cancelled_publication_preserves_only_committed_files(db, agents, memory_storage, monkeypatch, committed):
    await db.commit()
    original = db.commit if committed else db.flush

    async def interrupted(*args, **kwargs):
        if committed:
            await original(*args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(db, "commit" if committed else "flush", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await service.create_item(MemoryItemCreate(owner_agent_id=agents[0].id, title="Cancelled creation", payload=MemoryPayload(text="durable")))
    monkeypatch.setattr(db, "commit" if committed else "flush", original)
    items = list(await db.scalars(select(MemoryItem).where(MemoryItem.title == "Cancelled creation")))
    files = [path for path in memory_storage.rglob("*") if path.is_file()]
    assert len(items) == len(files) == int(committed)
    if committed:
        assert await get_storage().read(items[0].resource_id) == b"<p>durable</p>"
