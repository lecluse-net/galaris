"""PostgreSQL admission at the physical transport boundary."""

import asyncio
from contextvars import Context
from contextlib import ExitStack
from datetime import timedelta
from random import uniform
from uuid import UUID

from loguru import logger
from sqlalchemy import String, cast, delete, func, insert, select, update
from sqlalchemy.sql.dml import Delete
from sqlalchemy.ext.asyncio import AsyncSession
from .capacity_notifications import CHANNEL, subscribe
from .models import LLMCall, LLMProviderPermit
from .provider_models import LLMProvider
from .provider_scheduler import active_call_ids, provider_has_capacity
from core.database import get_db, get_db_session


_LEASE = timedelta(minutes=3)
_renewal: asyncio.Task[None] | None = None


async def lock_capacity(provider_id: int, priority: int) -> LLMProvider:
    """Keep the provider row locked until the caller commits the call and its permit together."""
    db = get_db()
    with ExitStack() as subscriptions:
        event: asyncio.Event | None = None
        while True:
            if event is not None:
                event.clear()
            provider = await db.scalar(select(LLMProvider).where(LLMProvider.id == provider_id, LLMProvider.deleted_at.is_(None))
                                       .with_for_update(key_share=True).execution_options(populate_existing=True))
            if provider is None or not provider.is_active:
                raise LookupError("LLM provider is unavailable.")
            limit = provider.effective_max_concurrent_calls
            if not limit:
                return provider
            counts = (await db.execute(select(
                func.count(), func.count().filter(LLMProviderPermit.priority == 2),
                func.count().filter(LLMProviderPermit.priority == priority),
            ).where(LLMProviderPermit.provider_id == provider_id))).one()
            if provider_has_capacity(limit, priority, counts[0], counts[1], counts[2]):
                return provider
            await db.commit()
            if event is None:
                event = subscriptions.enter_context(subscribe(db.get_bind().engine, provider_id))
                continue
            try:
                async with asyncio.timeout(uniform(1.5, 2.5)):
                    await event.wait()
            except TimeoutError:
                pass


async def insert_permit(call_id: UUID, provider_id: int, priority: int) -> None:
    await get_db().execute(insert(LLMProviderPermit).values(
        call_id=call_id, provider_id=provider_id, priority=priority, expires_at=func.clock_timestamp() + _LEASE))


def start_renewal() -> None:
    """Calls also originate in standalone workers that don't run Task maintenance."""
    global _renewal
    if _renewal is None or _renewal.done() or _renewal.get_loop() != asyncio.get_running_loop():
        _renewal = asyncio.create_task(_renew_while_active(), name="llm-provider-permit-renewal", context=Context())


async def _renew_while_active() -> None:
    while active_call_ids():
        await asyncio.sleep(20)
        active = active_call_ids()
        if active:
            try:
                async with get_db_session() as db:
                    await db.execute(update(LLMProviderPermit).where(LLMProviderPermit.call_id.in_(active))
                                     .values(expires_at=func.clock_timestamp() + _LEASE))
            except Exception:
                logger.exception("Could not renew provider reservations")


async def discard_expired_permits() -> None:
    # A delayed heartbeat alone doesn't prove the upstream request has ended.
    # Reuse a lost worker's slot only after the durable call lifecycle settles it.
    terminal = select(LLMCall.id).where(LLMCall.id == LLMProviderPermit.call_id, LLMCall.status != "running").exists()
    expired = delete(LLMProviderPermit).where(LLMProviderPermit.expires_at <= func.clock_timestamp(), terminal)
    await _release(get_db(), expired)


async def release_permit(db: AsyncSession, call_id: UUID) -> None:
    await _release(db, delete(LLMProviderPermit).where(LLMProviderPermit.call_id == call_id))


async def _release(db: AsyncSession, statement: Delete) -> None:
    released = statement.returning(LLMProviderPermit.provider_id).cte("released")
    providers = select(released.c.provider_id).distinct().subquery()
    await db.execute(select(func.pg_notify(CHANNEL, cast(providers.c.provider_id, String)))
                     .execution_options(include_historized=True))
