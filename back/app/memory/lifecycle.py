"""Fail-open observers for committed Memory item changes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from uuid import UUID

from loguru import logger


MemoryItemObserver = Callable[[UUID, str], None | Awaitable[None]]
_observers: dict[str, MemoryItemObserver] = {}


def register_memory_item_observer(name: str, observer: MemoryItemObserver) -> None:
    normalized = name.strip()
    if not normalized:
        raise ValueError("A Memory item observer requires a name.")
    _observers[normalized] = observer


async def notify_memory_item(item_id: UUID, action: str) -> None:
    for name, observer in sorted(_observers.items()):
        try:
            value = observer(item_id, action)
            if inspect.isawaitable(value):
                await value
        except Exception:
            logger.exception(
                "Memory item observer {} failed for item {}", name, item_id
            )


def unregister_memory_item_observer(name: str) -> None:
    _observers.pop(name, None)


def reset_memory_item_observers() -> None:
    _observers.clear()


__all__ = [
    "notify_memory_item",
    "register_memory_item_observer",
    "reset_memory_item_observers",
    "unregister_memory_item_observer",
]
