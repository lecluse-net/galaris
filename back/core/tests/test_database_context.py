from __future__ import annotations

import asyncio
from contextvars import Context

import pytest

from core.database import get_db, release_db_transaction


@pytest.mark.asyncio
async def test_release_db_transaction_keeps_managed_session_available(db) -> None:
    assert get_db() is db
    assert await release_db_transaction() is True
    assert get_db() is db


@pytest.mark.asyncio
async def test_release_db_transaction_accepts_database_free_runtime() -> None:
    async def release_without_context() -> bool:
        return await release_db_transaction()

    task = asyncio.create_task(release_without_context(), context=Context())
    assert await task is False
