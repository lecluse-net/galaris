import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.messenger import service
from app.messenger.interface import BridgeSpec


async def _stable_signatures(connection_ids: set[int]) -> dict[int, str]:
    return {connection_id: "stable" for connection_id in connection_ids}


@pytest.mark.asyncio
async def test_listeners_running_tracks_root_supervisor() -> None:
    original = service._listener_supervisor  # pyright: ignore[reportPrivateUsage]
    root = asyncio.create_task(asyncio.Event().wait())
    try:
        service._listener_supervisor = root  # pyright: ignore[reportPrivateUsage]
        assert service.listeners_running() is True

        root.cancel()
        await asyncio.gather(root, return_exceptions=True)
        assert service.listeners_running() is False
    finally:
        service._listener_supervisor = original  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_listener_discovery_combines_every_pull_based_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        BridgeSpec(kind="matrix", inbound_modes=["sync"]),
        BridgeSpec(
            kind="telegram",
            inbound_modes=["polling"],
        ),
        BridgeSpec(
            kind="whatsapp",
            inbound_modes=["push"],
        ),
    ]
    requested: list[str] = []
    session_active = False

    async def records(kind: str) -> list[object]:
        assert session_active
        requested.append(kind)
        return [SimpleNamespace(id={"matrix": 3, "telegram": 4}[kind])]

    class _Scalars:
        def all(self) -> list[int]:
            return [11, 22]

    class _Result:
        def scalars(self) -> _Scalars:
            return _Scalars()

    class _Db:
        async def execute(self, _statement: object) -> _Result:
            return _Result()

    @asynccontextmanager
    async def session() -> AsyncIterator[_Db]:
        nonlocal session_active
        session_active = True
        try:
            yield _Db()
        finally:
            session_active = False

    monkeypatch.setattr(service.facade, "enabled_specs", lambda: specs)
    monkeypatch.setattr(service.facade, "get_factory", lambda _kind: object)
    monkeypatch.setattr(service, "messaging_tool_records", records)
    monkeypatch.setattr(service, "get_db_session", session)

    assert await service._discover_active_listener_connections() == {11, 22}
    assert requested == ["matrix", "telegram"]


@pytest.mark.asyncio
async def test_reconcile_starts_and_stops_listener_with_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = AsyncMock()

    async def run_listener(connection_id: int) -> None:
        await started(connection_id)
        await asyncio.Event().wait()

    discoveries = [{12}, set()]

    async def discover() -> set[int]:
        return discoveries.pop(0)

    monkeypatch.setattr(service, "_run_listener", run_listener)
    monkeypatch.setattr(service, "_discover_active_listener_connections", discover)
    monkeypatch.setattr(
        service,
        "_listener_configuration_signatures",
        _stable_signatures,
    )
    service._listener_tasks.clear()
    service._listener_retry_after.clear()

    await service._reconcile_listeners()
    await asyncio.sleep(0)
    assert 12 in service._listener_tasks
    started.assert_awaited_once_with(12)

    await service._reconcile_listeners()
    assert service._listener_tasks == {}


@pytest.mark.asyncio
async def test_reconcile_respects_listener_retry_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = AsyncMock()

    async def discover() -> set[int]:
        return {12}

    monkeypatch.setattr(service, "_run_listener", started)
    monkeypatch.setattr(service, "_discover_active_listener_connections", discover)
    monkeypatch.setattr(
        service,
        "_listener_configuration_signatures",
        _stable_signatures,
    )
    service._listener_tasks.clear()
    service._listener_retry_after.clear()
    service._listener_retry_after[12] = service.time.monotonic() + 30.0

    await service._reconcile_listeners()

    assert service._listener_tasks == {}
    started.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_preserves_retry_delay_from_failed_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = AsyncMock()

    async def run_listener(connection_id: int) -> None:
        await started(connection_id)
        service._listener_retry_after[connection_id] = service.time.monotonic() + 30.0

    async def discover() -> set[int]:
        return {12}

    monkeypatch.setattr(service, "_run_listener", run_listener)
    monkeypatch.setattr(service, "_discover_active_listener_connections", discover)
    monkeypatch.setattr(
        service,
        "_listener_configuration_signatures",
        _stable_signatures,
    )
    service._listener_tasks.clear()
    service._listener_signatures.clear()
    service._listener_retry_after.clear()

    await service._reconcile_listeners()
    await service._listener_tasks[12]
    await service._reconcile_listeners()

    assert service._listener_tasks == {}
    assert service._listener_retry_after[12] > service.time.monotonic()
    started.assert_awaited_once_with(12)


@pytest.mark.asyncio
async def test_reconcile_restarts_listener_when_tool_configuration_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = AsyncMock()

    async def run_listener(connection_id: int) -> None:
        await started(connection_id)
        await asyncio.Event().wait()

    async def discover() -> set[int]:
        return {12}

    versions = iter(("first", "second"))

    async def signatures(connection_ids: set[int]) -> dict[int, str]:
        version = next(versions)
        return {connection_id: version for connection_id in connection_ids}

    monkeypatch.setattr(service, "_run_listener", run_listener)
    monkeypatch.setattr(service, "_discover_active_listener_connections", discover)
    monkeypatch.setattr(service, "_listener_configuration_signatures", signatures)
    service._listener_tasks.clear()
    service._listener_signatures.clear()
    service._listener_retry_after.clear()

    await service._reconcile_listeners()
    await asyncio.sleep(0)
    first = service._listener_tasks[12]
    await service._reconcile_listeners()
    await asyncio.sleep(0)

    assert first.cancelled()
    assert started.await_count == 2
    service._listener_tasks[12].cancel()
    await asyncio.gather(service._listener_tasks[12], return_exceptions=True)
    service._listener_tasks.clear()


@pytest.mark.asyncio
async def test_shutdown_prevents_listener_from_starting_after_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    construction_started = asyncio.Event()
    release_construction = asyncio.Event()
    listen = AsyncMock()
    messenger = SimpleNamespace(listen=listen)

    async def get_messenger(connection_id: int) -> object:
        assert connection_id == 12
        construction_started.set()
        try:
            await release_construction.wait()
        except asyncio.CancelledError:
            # Model a bridge constructor that must finish cleanup before returning.
            return messenger
        return messenger

    monkeypatch.setattr(service.facade, "get_messenger", get_messenger)
    service._listener_tasks.clear()
    service._listener_retry_after.clear()
    service._listeners_stopping = False

    task = asyncio.create_task(service._run_listener(12))
    service._listener_tasks[12] = task
    await construction_started.wait()

    await service.stop_listeners()

    assert task.done()
    listen.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_builds_registered_bridge_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import connection_service
    from app.tools import tool_service

    connection = SimpleNamespace(id=7, tool_id=3, active=True)
    tool = SimpleNamespace(
        code="custom-chat",
        messenger=SimpleNamespace(service="one_bot"),
    )

    async def get_connection(connection_id: int) -> object:
        assert connection_id == 7
        return connection

    async def get_tool_by_id(tool_id: int) -> object:
        assert tool_id == 3
        return tool

    class FakeBridge:
        @classmethod
        async def from_connection_id(cls, connection_id: int) -> SimpleNamespace:
            return SimpleNamespace(marker="messenger", connection_id=connection_id)

    monkeypatch.setattr(connection_service, "get_connection", get_connection)
    monkeypatch.setattr(tool_service, "get_tool_by_id", get_tool_by_id)
    monkeypatch.setattr(
        service.facade,
        "get_factory",
        lambda kind: FakeBridge if kind == "one_bot" else None,
    )

    messenger = await service.AppMessengerResolver().messenger_for_connection(7)

    assert messenger.marker == "messenger"
    assert messenger.connection_id == 7
    assert messenger.tool_code == "custom-chat"
