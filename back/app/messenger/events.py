"""Minimal async-native messaging event bus for dependency inversion.

Publishers emit signals instead of calling consumers directly. Receivers are isolated so one
failure cannot prevent other subscribers from receiving an event.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, List

from loguru import logger

Receiver = Callable[..., Any]


class Signal:
    """Asynchronous publish/subscribe signal with isolated receivers."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._receivers: List[Receiver] = []
        self._optional: set[Receiver] = set()

    def connect(self, receiver: Receiver, *, required: bool = True) -> Receiver:
        """Subscribe a receiver idempotently and return it for decorator use."""
        if receiver not in self._receivers:
            self._receivers.append(receiver)
        if required:
            self._optional.discard(receiver)
        else:
            self._optional.add(receiver)
        return receiver

    def disconnect(self, receiver: Receiver) -> None:
        if receiver in self._receivers:
            self._receivers.remove(receiver)
        self._optional.discard(receiver)

    @property
    def has_receivers(self) -> bool:
        return bool(self._receivers)

    @property
    def has_required_receivers(self) -> bool:
        return any(receiver not in self._optional for receiver in self._receivers)

    async def send_async_collect(
        self, *args: Any, **kwargs: Any
    ) -> list[Exception]:
        """Notify every receiver and return the failures after isolating them."""

        failures: list[Exception] = []
        for receiver in list(self._receivers):
            try:
                result = receiver(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                if receiver not in self._optional:
                    failures.append(exc)
                logger.exception(
                    "Signal '{}': receiver {} failed",
                    self.name, getattr(receiver, "__qualname__", receiver),
                )
        return failures

    async def send_async(self, *args: Any, **kwargs: Any) -> None:
        """Notify receivers sequentially while isolating and logging failures."""

        await self.send_async_collect(*args, **kwargs)


# Messaging-domain signals.

# Canonical, deduplicated inbound message.
message_received = Signal("message_received")

# Live, persisted input about to enter business admission. Optional consumers
# schedule independent work and must never delay or reject admission.
message_admitting = Signal("message_admitting")

# Confirmed outbound message, available for optional logging and auditing.
message_sent = Signal("message_sent")

# Canonical message persisted without triggering inbound business admission.
# Live voice turns use this signal because their execution lifecycle is already
# owned by app.voice; consumers such as Chat may still refresh their projection.
message_journaled = Signal("message_journaled")

# A persisted choice was attached to a prompt, captured, or applied.
interaction_changed = Signal("interaction_changed")
