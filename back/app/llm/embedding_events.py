"""Notifications owned by model configuration, independent from its consumers."""

from collections.abc import Awaitable, Callable

EmbeddingChangeListener = Callable[[], Awaitable[None]]
_listeners: dict[str, EmbeddingChangeListener] = {}


def register_embedding_change_listener(key: str, listener: EmbeddingChangeListener) -> None:
    _listeners[key] = listener


async def notify_embedding_change() -> None:
    for listener in tuple(_listeners.values()):
        await listener()
