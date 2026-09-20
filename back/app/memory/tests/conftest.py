from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry


@pytest_asyncio.fixture
async def agents(db: AsyncSession) -> tuple[Agent, Agent]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Memory test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    first = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Memory",
        code=f"memory-a-{suffix}",
        agent_driver="internal",
    )
    second = Agent(
        title_id=title.id,
        first_name="Bob",
        last_name="Memory",
        code=f"memory-b-{suffix}",
        agent_driver="internal",
    )
    db.add_all([first, second])
    await db.flush()
    return first, second


@pytest_asyncio.fixture
async def memory_storage(tmp_path: Path) -> AsyncIterator[Path]:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        yield tmp_path
    finally:
        reset_storage_registry()
