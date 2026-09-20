"""Keep file descriptors and reservations alive until blocking I/O has finished."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


async def complete_io[**P, T](operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Drain an uncancellable OS operation before propagating caller cancellation.

    Repeated cancellation cannot detach the worker from its owning coroutine.
    Callers still own cleanup of an unpublished creation on CancelledError.
    """
    return await complete_await(asyncio.to_thread(operation, *args, **kwargs))


async def complete_await[T](operation: Coroutine[Any, Any, T]) -> T:
    """Finish owned cleanup before returning even repeated caller cancellation."""
    pending = asyncio.create_task(operation)
    cancelled: asyncio.CancelledError | None = None
    while not pending.done():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            cancelled = exc
        except Exception:
            break
    if cancelled is not None:
        # Retrieve any worker error; cancellation remains the caller's outcome.
        if not pending.cancelled():
            pending.exception()
        raise cancelled
    return pending.result()
