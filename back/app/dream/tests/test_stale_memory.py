from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.dream import scheduler
from app.dream.mechanisms import stale_memory as stale_memory_module
from app.dream.mechanisms.stale_memory import stale_memory_mechanism
from app.dream.models import DreamReceipt
from app.dream.registry import register_mechanism, reset_registry
from app.memory import service
from app.memory.models import MemoryItem
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.storage import (
    NativeFileStorage,
    register_storage,
    reset_storage_registry,
)


@pytest.fixture
def stale_memory_storage(tmp_path: Path) -> Path:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        yield tmp_path
    finally:
        reset_storage_registry()


async def _owner(db: AsyncSession) -> Agent:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Stale memory test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Retention",
        code=f"stale-memory-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    return owner


@pytest.mark.asyncio
async def test_dream_forgets_expired_memory_without_llm(
    db: AsyncSession,
    stale_memory_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del stale_memory_storage
    owner = await _owner(db)
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Expired note",
            payload=MemoryPayload(text="This note has passed its validity."),
            valid_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    item_id = item.id
    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr(scheduler.runtime_settings, "DREAM_ENABLED", True)
    monkeypatch.setattr(
        stale_memory_module.runtime_settings,
        "MEMORY_FORGET_AFTER_DAYS",
        0,
    )
    reset_registry()
    register_mechanism(stale_memory_mechanism)
    try:
        assert await scheduler.run_cycle() == 1
        assert await scheduler.run_cycle() == 0
    finally:
        reset_registry()

    db.expire_all()
    tombstone = await db.scalar(
        select(MemoryItem)
        .where(MemoryItem.id == item_id)
        .execution_options(include_historized=True)
    )
    assert tombstone is not None
    assert tombstone.title == "Forgotten memory"
    receipt = await db.scalar(
        select(DreamReceipt).where(
            DreamReceipt.mechanism_key == stale_memory_mechanism.key
        )
    )
    assert receipt is not None
    assert receipt.status == "success"
    assert receipt.cost == 0.0


@pytest.mark.asyncio
async def test_inactivity_retention_rechecks_activity_before_forgetting(
    db: AsyncSession,
    stale_memory_storage: Path,
) -> None:
    del stale_memory_storage
    owner = await _owner(db)
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Old but refreshed note",
            payload=MemoryPayload(text="The activity check is optimistic."),
        )
    )
    old = datetime.now(timezone.utc) - timedelta(days=40)
    await db.execute(
        update(MemoryItem)
        .where(MemoryItem.id == item.id)
        .values(created_at=old)
    )
    await db.commit()
    await db.refresh(item)
    expected_activity = item.activity_at

    item.last_accessed_at = datetime.now(timezone.utc)
    await db.commit()
    result = await service.forget_stale_item(
        item.id,
        expected_activity_at=expected_activity,
        forget_after_days=30,
    )

    assert result is None
    loaded, _content, _access, _content_type, _media_type = (
        await service.get_item(item.id, agent_id=owner.id)
    )
    assert loaded.id == item.id
