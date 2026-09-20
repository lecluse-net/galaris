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
