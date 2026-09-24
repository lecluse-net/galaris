"""Start specialized topic classification alongside live message admission.

The canonical journal is the recovery queue. This worker shares Dream's receipt
and mechanism, but is independent of its idle-only, preemptible maintenance loop.
"""

import asyncio
from collections import deque
from contextvars import Context
from uuid import UUID

from loguru import logger

from app.llm import llm_correlation_scope, llm_execution_scope
from app.messenger import Message, message_admitting

from .contracts import DreamClaim
from .mechanisms.sequential_topic_classification import message_topic_classification_mechanism
from .service import (
    claim_execution_timeout,
    mark_failure,
    mark_success,
    receipt_correlation_ref,
    release_interrupted,
    store_prepared,
)


_pending: dict[UUID, deque[UUID]] = {}
_workers: dict[UUID, asyncio.Task[None]] = {}
_enabled = False


def schedule(message: Message) -> None:
    """Copy identifiers only; never share the request's ORM session or await AI."""
    room_id = message.messenger_room_id
    if not _enabled or room_id is None or message.direction != "inbound":
        return
    if not message.text.strip() or message.topic_id is not None or message.topic_overridden:
        return
    queue = _pending.setdefault(room_id, deque())
    if message.id not in queue:
        queue.append(message.id)
    if room_id not in _workers:
        _workers[room_id] = asyncio.create_task(
            _drain(room_id),
            name=f"live-topic:{room_id}",
            context=Context(),
        )


async def _classify(message_id: UUID) -> None:
    mechanism = message_topic_classification_mechanism
    claim: DreamClaim | None = None
    try:
        claim = await mechanism.claim_message(message_id)
        if claim is None:
            return
        with (
            llm_correlation_scope(receipt_correlation_ref(claim.receipt_id)),
            llm_execution_scope(
                source_kind="message", source_id=str(message_id), messenger_origin=True
            ),
        ):
            async with asyncio.timeout(claim_execution_timeout()):
                prepared = await mechanism.prepare(claim)
                payload = (
                    {**prepared.payload, "classification_trigger": "message_admission"}
                    if prepared.payload
                    else {}
                )
                await store_prepared(claim, payload, cost=prepared.cost)
                count = await mechanism.apply(claim, payload)
                await mark_success(claim, result_count=count)
    except asyncio.CancelledError:
        if claim is not None:
            await asyncio.shield(release_interrupted(claim, "Live topic worker stopped."))
        raise
    except Exception as exc:
        if claim is not None:
            await mark_failure(claim, exc)
        logger.exception("Live topic classification failed for message {}", message_id)


async def _drain(room_id: UUID) -> None:
    try:
        queue = _pending[room_id]
        while queue:
            await _classify(queue[0])
            queue.popleft()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Live topic worker failed for room {}; Dream will recover", room_id)
    finally:
        _pending.pop(room_id, None)
        _workers.pop(room_id, None)


def start() -> None:
    global _enabled
    _enabled = True
    message_admitting.connect(schedule, required=False)


async def stop() -> None:
    global _enabled
    _enabled = False
    message_admitting.disconnect(schedule)
    workers = tuple(_workers.values())
    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    _pending.clear()
    _workers.clear()
