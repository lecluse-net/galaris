"""Fail-open observers for committed Document changes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from uuid import UUID

from loguru import logger
from core.database import get_db_session, release_db_transaction


DocumentObserver = Callable[[UUID, str], None | Awaitable[None]]
_observers: dict[str, DocumentObserver] = {}


def register_document_observer(name: str, observer: DocumentObserver) -> None:
    normalized = name.strip()
    if not normalized:
        raise ValueError("A Document observer requires a name.")
    _observers[normalized] = observer


async def notify_document(item_id: UUID, action: str) -> None:
    if action == "sharing":
        from core import websocket
        await websocket.emit("document", "invalidate", {}, None)
    if _observers:
        # Do not hold a caller connection while a downstream session waits for
        # another slot in the pool. Notifications follow the source commit.
        await release_db_transaction()
    for name, observer in sorted(_observers.items()):
        try:
            # Source writes have committed. A broken downstream SQL operation
            # must neither poison the caller's session nor its saved result.
            async with get_db_session():
                value = observer(item_id, action)
                if inspect.isawaitable(value):
                    await value
        except Exception:
            logger.exception(
                "Document observer {} failed for item {}", name, item_id
            )


def unregister_document_observer(name: str) -> None:
    _observers.pop(name, None)


def reset_document_observers() -> None:
    _observers.clear()


__all__ = [
    "notify_document",
    "register_document_observer",
    "reset_document_observers",
    "unregister_document_observer",
]
