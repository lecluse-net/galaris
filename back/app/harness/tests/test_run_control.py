from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.harness import run_control


@pytest.mark.asyncio
async def test_cancel_accepts_task_id_and_releases_resources_once() -> None:
    run_id = uuid4()
    task_id = uuid4()
    resources = run_control.RunResources()
    cleanup = AsyncMock()
    resources.add_cleanup("resource", cleanup)
    entered = asyncio.Event()

    async def worker() -> None:
        await run_control.register(run_id, task_id, resources)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.shield(resources.close())
            await run_control.unregister(run_id, task_id)

    execution = asyncio.create_task(worker())
    await entered.wait()

    assert run_control.is_active(run_id)
    assert run_control.is_active(task_id)
    await run_control.cancel(task_id)

    assert execution.cancelled()
    assert not run_control.is_active(run_id)
    assert not run_control.is_active(task_id)
    cleanup.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_call_recovery_reaches_only_the_live_owner_without_closing_its_resources():
    from unittest.mock import Mock

    run_id = uuid4()
    resources = run_control.RunResources()
    cleanup = AsyncMock()
    resources.add_cleanup("synthetic-resource", cleanup)
    callback = Mock(return_value=True)
    ready, done = asyncio.Event(), asyncio.Event()

    async def worker():
        await run_control.register(run_id, None, resources)
        await run_control.set_call_recovery_request(run_id, callback)
        ready.set()
        try:
            await done.wait()
        finally:
            await run_control.set_call_recovery_request(run_id, None)
            await run_control.unregister(run_id, None)
            await resources.close()

    execution = asyncio.create_task(worker())
    try:
        await ready.wait()
        await run_control.set_call_recovery_request(run_id, lambda: False)  # Non-owner cannot replace it.
        assert await run_control.request_call_recovery(uuid4()) is False
        assert await run_control.request_call_recovery(run_id) is True
        callback.assert_called_once_with()
        assert not execution.done()
        cleanup.assert_not_awaited()
    finally:
        done.set()
        await execution
    assert await run_control.request_call_recovery(run_id) is False
    cleanup.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancel_is_idempotent_after_run_completion() -> None:
    run_id, task_id = uuid4(), uuid4()
    resources = run_control.RunResources()
    cleanup = AsyncMock()
    resources.add_cleanup("resource", cleanup)

    async def worker() -> str:
        await run_control.register(run_id, task_id, resources)
        try:
            return "completed"
        finally:
            await resources.close()
            await run_control.unregister(run_id, task_id)

    execution = asyncio.create_task(worker())
    assert await execution == "completed"
    await run_control.cancel(run_id)
    await run_control.cancel(task_id)
    await run_control.cancel(run_id)

    assert execution.result() == "completed"
    assert not run_control.is_active(run_id)
    assert not run_control.is_active(task_id)
    cleanup.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancel_prefers_registered_cooperative_request() -> None:
    run_id = uuid4()
    resources = run_control.RunResources()
    entered = asyncio.Event()
    released = asyncio.Event()
    requested = asyncio.Event()

    def cooperative_cancel() -> None:
        requested.set()
        released.set()

    async def worker() -> None:
        await run_control.register(run_id, None, resources)
        await run_control.set_cancel_request(run_id, cooperative_cancel)
        entered.set()
        try:
            await released.wait()
            raise asyncio.CancelledError
        finally:
            await run_control.unregister(run_id, None)

    execution = asyncio.create_task(worker())
    await entered.wait()

    await run_control.cancel(run_id)

    assert requested.is_set()
    assert execution.cancelled()
    assert not run_control.is_active(run_id)
