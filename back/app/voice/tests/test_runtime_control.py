from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.voice import runtime_control


@pytest.fixture(autouse=True)
def fake_owner_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from collections.abc import AsyncGenerator
    from typing import Any

    connection = AsyncMock()
    connection.scalar.return_value = True

    @asynccontextmanager
    async def connect() -> AsyncGenerator[Any]:
        yield connection

    monkeypatch.setattr(runtime_control, "engine", SimpleNamespace(connect=connect))
    monkeypatch.setattr(runtime_control, "_session_is_active", AsyncMock(return_value=True))


@pytest.mark.asyncio
async def test_local_owner_is_stopped_before_acknowledgment() -> None:
    session_id = uuid4()
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run() -> None:
        async with runtime_control.own_session(session_id):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    owner = asyncio.create_task(run())
    await started.wait()
    assert await runtime_control.cancel_session(session_id)
    assert stopped.is_set()
    assert owner.cancelled()
    assert session_id not in runtime_control._owners
    assert await runtime_control.cancel_session(session_id)


@pytest.mark.asyncio
async def test_non_cooperative_owner_does_not_acknowledge_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_control, "_CANCEL_WAIT_SECONDS", 0.01)
    session_id = uuid4()
    started = asyncio.Event()
    release = asyncio.Event()

    async def run() -> None:
        async with runtime_control.own_session(session_id):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

    owner = asyncio.create_task(run())
    await started.wait()
    try:
        assert not await runtime_control.cancel_session(session_id)
    finally:
        release.set()
        await owner
    assert await runtime_control.cancel_session(session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_module", ["engine", "realtime_engine"])
async def test_both_engines_register_cancellable_owners(
    monkeypatch: pytest.MonkeyPatch,
    engine_module: str,
) -> None:
    from app.voice.engine import AgentVoiceEngine
    from app.voice.realtime_engine import RealtimeAgentVoiceEngine

    cls = AgentVoiceEngine if engine_module == "engine" else RealtimeAgentVoiceEngine
    engine = object.__new__(cls)
    session_id = uuid4()
    engine._session_id = session_id
    started = asyncio.Event()

    async def hold() -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "_run_owned", AsyncMock(side_effect=hold))
    owner = asyncio.create_task(engine.run())
    await started.wait()
    assert await runtime_control.cancel_session(session_id)
    assert owner.cancelled()


@pytest.mark.asyncio
async def test_durable_fence_stops_owner_without_local_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from collections.abc import AsyncGenerator
    from typing import Any

    db = AsyncMock()
    db.scalar.return_value = "CANCELLED"
    monkeypatch.setattr(runtime_control, "_session_is_active", AsyncMock(side_effect=[True, False]))

    @asynccontextmanager
    async def fake_db() -> AsyncGenerator[Any]:
        yield db

    monkeypatch.setattr(runtime_control, "get_db_session", fake_db)
    monkeypatch.setattr(runtime_control, "_POLL_SECONDS", 0.001)
    session_id = uuid4()

    async def run() -> None:
        async with runtime_control.own_session(session_id):
            await asyncio.Event().wait()

    owner = asyncio.create_task(run())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=1)
    assert runtime_control._session_is_active.await_count >= 2
    assert session_id not in runtime_control._owners


@pytest.mark.asyncio
async def test_durable_fence_failure_stops_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from collections.abc import AsyncGenerator
    from typing import Any

    db = AsyncMock()
    db.scalar.side_effect = ConnectionError("isolated database unavailable")
    monkeypatch.setattr(runtime_control, "_session_is_active", AsyncMock(side_effect=[True, ConnectionError("database unavailable")]))

    @asynccontextmanager
    async def fake_db() -> AsyncGenerator[Any]:
        yield db

    monkeypatch.setattr(runtime_control, "get_db_session", fake_db)
    monkeypatch.setattr(runtime_control, "_POLL_SECONDS", 0.001)

    async def run() -> None:
        async with runtime_control.own_session(uuid4()):
            await asyncio.Event().wait()

    owner = asyncio.create_task(run())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner, timeout=1)
