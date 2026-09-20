"""Single signal-driven convergence point for inbound messaging.

Every bridge converts its native payload to a canonical ``ObservedMessengerMessage`` and calls
``dispatch_incoming``. This module deduplicates messages by tool and native identifier before
emitting the shared event. Bridges remain responsible for ignoring their own echoes.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Awaitable, Callable, Deque, Optional, Set, Tuple

from loguru import logger

from app.messenger.events import message_received
from app.messenger._observations import ObservedMessengerMessage
from app.messenger.models import Message

InboundHandler = Callable[[Message], Awaitable[None]]

# Bounded deduplication of recently seen ``(connection_id, tool_id, message_id)`` pairs.
# A single Messenger tool can own several bot/account connections, so the connection must be
# part of the key just like it is in the durable uniqueness constraint.
_DEDUP_MAXLEN = 2048
_seen_order: Deque[Tuple[Optional[int], Optional[int], str]] = deque(maxlen=_DEDUP_MAXLEN)
_seen: Set[Tuple[Optional[int], Optional[int], str]] = set()


def on_message(handler: InboundHandler) -> InboundHandler:
    """Subscribe a handler to canonical, deduplicated inbound messages."""
    return message_received.connect(handler)


def _already_seen(message: Message) -> bool:
    """Return whether this message was processed recently."""
    if not message.remote_message_id:
        return False
    key = (message.connection_id, message.tool_id, message.remote_message_id)
    if key in _seen:
        return True
    if len(_seen_order) == _seen_order.maxlen:
        evicted = _seen_order[0]
        _seen.discard(evicted)
    _seen_order.append(key)
    _seen.add(key)
    return False


def _forget_seen(message: Message) -> None:
    """Allow a failed durable admission to be attempted again in this process."""

    if not message.remote_message_id:
        return
    key = (message.connection_id, message.tool_id, message.remote_message_id)
    _seen.discard(key)
    try:
        _seen_order.remove(key)
    except ValueError:
        pass


async def dispatch_incoming(
    message: ObservedMessengerMessage,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Persist, deduplicate, and emit a canonical inbound message.

    The boolean result tells push bridges whether the payload was new. Provider webhooks still
    acknowledge duplicates successfully.
    """
    from app.messenger import journal

    connection_id = journal.connection_id_for(message)
    if connection_id is None or not message.id:
        logger.error(
            "Rejected inbound Messenger message without canonical connection or remote id"
        )
        return False
    inserted = await journal.persist_inbound(
        message,
        connection_id=connection_id,
        platform=message.platform or "messenger",
        metadata=metadata,
    )
    stored = await journal.stored_message(
        connection_id=connection_id,
        remote_message_id=message.id,
        direction="inbound",
    )
    if stored is None:
        raise RuntimeError("The persisted inbound Messenger message cannot be reloaded.")
    from app.messenger import facade

    spec = facade.get_spec(stored.platform)
    if not inserted and stored.status == "admitted":
        return False
    # Enforce the instant-message age contract before the shared signal. This keeps every current
    # and future subscriber from creating a Conversation, Task, interaction, or other business
    # effect for imported history. The service repeats the guard for direct recovery callers.
    from app.messenger.service import archive_stale_instant_message

    if await archive_stale_instant_message(stored):
        return inserted
    if spec is not None and spec.inbound_admission == "task":
        try:
            from app.messenger.service import admit_incoming

            await admit_incoming(stored)
        except Exception as exc:
            await journal.update_inbound_admission_status(
                connection_id=connection_id,
                remote_message_id=message.id,
                status="failed",
                error=type(exc).__name__,
            )
            raise
        await journal.update_inbound_admission_status(
            connection_id=connection_id,
            remote_message_id=message.id,
            status="admitted",
        )
        return True
    if not message_received.has_required_receivers:
        logger.warning(
            "Inbound message received (tool_id={}) but 'message_received' has no subscribers "
            "(app.messenger.on_message or message_received.connect was not called)",
            stored.tool_id,
        )
        raise RuntimeError("Inbound Messenger admission has no registered receiver.")
    if _already_seen(stored):
        return False
    failures = await message_received.send_async_collect(stored)
    if failures:
        _forget_seen(stored)
        failure = failures[0]
        await journal.update_inbound_admission_status(
            connection_id=connection_id,
            remote_message_id=message.id,
            status="failed",
            error=type(failure).__name__,
        )
        raise failure
    await journal.update_inbound_admission_status(
        connection_id=connection_id,
        remote_message_id=message.id,
        status="admitted",
    )
    return True


def _reset_dedup_for_tests() -> None:  # pyright: ignore[reportUnusedFunction]
    """Reset the deduplication cache for tests."""
    _seen_order.clear()
    _seen.clear()
