"""Startup's deadline includes blocked connections, pings and repeated failures."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.database import database


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_phase", ["connect", "query"])
async def test_deadline_cancels_blocked_attempt_and_releases_context(monkeypatch, blocked_phase):
    released = asyncio.Event()

    async def query(*args):
        await asyncio.Event().wait()

    @asynccontextmanager
    async def connect():
        try:
            if blocked_phase == "connect":
                await asyncio.Event().wait()
            yield SimpleNamespace(execute=query)
        finally:
            released.set()

    monkeypatch.setattr(database, "engine", SimpleNamespace(connect=connect))
    start = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutError):
        await database.wait_for_db(timeout=0.05)
    assert asyncio.get_running_loop().time() - start < 0.8
    assert released.is_set()


@pytest.mark.asyncio
async def test_retries_share_one_deadline(monkeypatch):
    attempts = 0
    released = asyncio.Event()

    @asynccontextmanager
    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.sleep(0.03)
            raise OSError("Database starting")
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            released.set()

    monkeypatch.setattr(database, "engine", SimpleNamespace(connect=connect))
    start = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutError):
        await database.wait_for_db(timeout=0.1, initial_delay=0.001)
    assert attempts == 2
    assert asyncio.get_running_loop().time() - start < 0.8
    assert released.is_set()


@pytest.mark.asyncio
async def test_transient_failure_can_recover_within_deadline(monkeypatch):
    attempts = 0
    execute = AsyncMock()

    @asynccontextmanager
    async def connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Database starting")
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(database, "engine", SimpleNamespace(connect=connect))
    await database.wait_for_db(timeout=1, initial_delay=0.001)
    assert attempts == 2
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_retried(monkeypatch):
    entered = asyncio.Event()
    released = asyncio.Event()

    @asynccontextmanager
    async def connect():
        try:
            entered.set()
            await asyncio.Event().wait()
            yield None
        finally:
            released.set()

    monkeypatch.setattr(database, "engine", SimpleNamespace(connect=connect))
    task = asyncio.create_task(database.wait_for_db(timeout=60))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
