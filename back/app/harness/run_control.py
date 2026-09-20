"""In-process lifecycle control for internal-harness runs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

from loguru import logger

Cleanup = Callable[[], Awaitable[None]]
CancelRequest = Callable[[], None]


@dataclass
class RunResources:
    """Collect task-scoped resources that must be released exactly once."""

    _cleanups: dict[str, Cleanup] = field(default_factory=dict[str, Cleanup])
    _closed: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add_cleanup(self, key: str, cleanup: Cleanup) -> None:
        if self._closed:
            raise RuntimeError("Run resources are already closed.")
        self._cleanups.setdefault(key, cleanup)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            cleanups = tuple(reversed(tuple(self._cleanups.items())))
            self._cleanups.clear()

        for key, cleanup in cleanups:
            try:
                await cleanup()
            except asyncio.CancelledError:
                # Cleanup runs under ``shield`` but keep this defensive boundary so one
                # resource cannot prevent the following resources from being released.
                logger.warning("Harness run cleanup was cancelled (resource={})", key)
            except Exception:
                logger.exception("Harness run cleanup failed (resource={})", key)


@dataclass
class _ActiveRun:
    task: asyncio.Task[object]
    resources: RunResources
    cancel_request: CancelRequest | None = None


_active_runs: dict[UUID, _ActiveRun] = {}
_registry_lock = asyncio.Lock()


async def register(
    run_id: UUID,
    task_id: UUID | None,
    resources: RunResources,
) -> None:
    current = asyncio.current_task()
    if current is None:
        raise RuntimeError("A harness run must execute inside an asyncio task.")
    active = _ActiveRun(task=current, resources=resources)
    async with _registry_lock:
        if run_id in _active_runs:
            raise RuntimeError(f"Harness run {run_id} is already active.")
        if task_id is not None and task_id in _active_runs:
            raise RuntimeError(f"Task {task_id} is already active in the internal harness.")
        _active_runs[run_id] = active
        if task_id is not None:
            _active_runs[task_id] = active


async def unregister(run_id: UUID, task_id: UUID | None) -> None:
    current = asyncio.current_task()
    async with _registry_lock:
        for identifier in (run_id, task_id):
            if identifier is None:
                continue
            active = _active_runs.get(identifier)
            if active is not None and active.task is current:
                _active_runs.pop(identifier, None)


async def set_cancel_request(
    run_id: UUID,
    cancel_request: CancelRequest | None,
) -> None:
    """Switch a live run between cooperative and asyncio cancellation."""

    current = asyncio.current_task()
    async with _registry_lock:
        active = _active_runs.get(run_id)
        if active is not None and active.task is current:
            active.cancel_request = cancel_request


async def cancel(run_id: UUID) -> None:
    """Cancel one live run and wait until its resource cleanup has completed."""

    async with _registry_lock:
        active = _active_runs.get(run_id)
    if active is None:
        # Cancellation races are expected: scheduler cancellation may already have
        # completed the coroutine before the explicit driver request arrives.
        return

    if active.cancel_request is None:
        active.task.cancel()
    else:
        try:
            active.cancel_request()
        except Exception:
            logger.exception(
                "Harness cooperative cancellation failed; cancelling asyncio task"
            )
            active.task.cancel()
    if active.task is not asyncio.current_task():
        try:
            await active.task
        except asyncio.CancelledError:
            pass
    await active.resources.close()


def is_active(run_id: UUID) -> bool:
    active = _active_runs.get(run_id)
    return active is not None and not active.task.done()
