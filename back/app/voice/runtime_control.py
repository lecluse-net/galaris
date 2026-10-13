"""Durable fencing and PostgreSQL-coordinated ownership of direct audio calls."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from core.database import engine, get_db_session
from .models import VoiceConversationSession, VoiceConversationStatus

_POLL_SECONDS = 0.25
_CANCEL_WAIT_SECONDS = 1.0
_owners: dict[UUID, set[asyncio.Task[Any]]] = {}


def _lock_key(session_id: UUID) -> int:
    # Independent namespace; collisions only delay deletion, never allow early deletion.
    return int.from_bytes(
        hashlib.blake2b(b"voice-owner:" + session_id.bytes, digest_size=8).digest(),
        "big",
        signed=True,
    )


async def _session_is_active(session_id: UUID) -> bool:
    async with get_db_session() as db:
        return (
            await db.scalar(
                select(VoiceConversationSession.status).where(
                    VoiceConversationSession.id == session_id
                )
            )
            == VoiceConversationStatus.ACTIVE.value
        )


async def _watch_session(session_id: UUID, owner: asyncio.Task[Any]) -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            async with asyncio.timeout(5):
                active = await _session_is_active(session_id)
        except Exception:
            active = False  # Fail closed on loss of the durable fence.
        if not active:
            owner.cancel()
            return


@asynccontextmanager
async def own_session(session_id: UUID) -> AsyncGenerator[None]:
    """Hold a shared PG lock until all enclosed engine/transport finalizers return.

    A connection-scoped lock survives transaction commits, unlike a row/transaction
    lock. Process death releases it automatically; no heartbeat TTL can falsely
    acknowledge a stalled but still live owner. Never use the request DB connection.
    """
    owner = asyncio.current_task()
    if owner is None:
        raise RuntimeError("Voice execution requires an asyncio task")
    owners = _owners.setdefault(session_id, set())
    if owner in owners:
        yield
        return
    key = _lock_key(session_id)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock_shared(:key)"), {"key": key})
        await connection.commit()
        try:
            # Register before checking admission: deletion will either see our lock,
            # or commit its fence before this check. Closed calls cannot restart.
            owners.add(owner)
            if not await _session_is_active(session_id):
                raise PermissionError("Voice session is closed")
            watcher = asyncio.create_task(
                _watch_session(session_id, owner), name="voice-session-fence"
            )
            try:
                yield
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
        finally:
            owners.discard(owner)
            if not owners:
                _owners.pop(session_id, None)
            # Session locks must be unlocked explicitly before returning to the pool.
            try:
                await connection.execute(
                    text("SELECT pg_advisory_unlock_shared(:key)"), {"key": key}
                )
                await connection.commit()
            except BaseException:
                await connection.invalidate()
                raise


async def session_stopped(session_id: UUID) -> bool:
    """Probe all workers; caller must commit the closed-session fence first."""
    async with engine.connect() as connection:
        stopped = await connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _lock_key(session_id)}
        )
        return bool(stopped)


async def cancel_session(session_id: UUID) -> bool:
    owners = {owner for owner in _owners.get(session_id, ()) if not owner.done()}
    owners.discard(asyncio.current_task())
    for owner in owners:
        owner.cancel()
    if owners:
        _, pending = await asyncio.wait(owners, timeout=_CANCEL_WAIT_SECONDS)
        if pending:
            return False
    return await session_stopped(session_id)
