"""Isolated, fair Process admission branches for each registered engine."""

import asyncio
from collections.abc import Awaitable, Callable, Collection
from uuid import UUID

from sqlalchemy import func, or_, select

from core.database import get_db, get_db_session
from .models import ProcessRun, ProcessStartJob
from . import process_service, registry
from .engine import IntegratedProcessEngine
from core.params import runtime_settings
from datetime import datetime, timedelta, timezone
from loguru import logger


class EffectSlots:
    """A slow effect occupies only its own slot, across scheduler ticks."""

    def __init__(self, discover: Callable[[int, Collection[UUID]], Awaitable[list[UUID]]],
                 execute: Callable[[UUID], Awaitable[None]], *, capacity: int = 4) -> None:
        self.discover = discover
        self.execute = execute
        self.capacity = capacity
        self.active: dict[UUID, asyncio.Task[None]] = {}
        self.stopping = False

    async def tick(self) -> None:
        slots = self.capacity - len(self.active)
        if slots <= 0 or self.stopping:
            return
        identities = await self.discover(slots, self.active.keys())
        await get_db().commit()
        if self.stopping:
            return
        for identity in identities:
            if identity not in self.active:
                self.active[identity] = asyncio.create_task(self._run(identity), name=f"process-effect-{identity}")

    async def _run(self, identity: UUID) -> None:
        try:
            async with asyncio.timeout(360), get_db_session():
                await self.execute(identity)
        except Exception as error:
            # The durable intent remains in the attempt if dispatch was possible.
            logger.warning("Process effect job {} failed ({})", identity, type(error).__name__)
        finally:
            self.active.pop(identity, None)

    async def stop(self) -> None:
        self.stopping = True
        if self.active:
            _, pending = await asyncio.wait(tuple(self.active.values()), timeout=6)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


class ProcessEffectWorkers:
    def __init__(self) -> None:
        from .activity_jobs import discover_external_activities, execute_external_activity
        from .code_broker import discover_code_capability_calls, execute_code_capability

        self.external = EffectSlots(discover_external_activities, execute_external_activity)
        self.python = EffectSlots(discover_code_capability_calls, execute_code_capability)

    async def stop(self) -> None:
        await asyncio.gather(self.external.stop(), self.python.stop())


async def start_engine_jobs(engine_code: str) -> int:
    engine = registry.get(engine_code)
    timeout = (
        engine.start_timeout_seconds
        if isinstance(engine, IntegratedProcessEngine)
        else runtime_settings.PROCESS_START_TIMEOUT_SECONDS
    )
    now = datetime.now(timezone.utc)
    # Interleave owners before limiting the batch; one owner's backlog must not
    # crowd every slot. Each engine has its own periodic job and bounded slots.
    ranked = (
        select(
            ProcessStartJob.id,
            ProcessStartJob.available_at,
            func.row_number()
            .over(
                partition_by=ProcessRun.launcher_agent_id,
                order_by=(ProcessStartJob.available_at, ProcessStartJob.id),
            )
            .label("owner_position"),
        )
        .join(ProcessRun, ProcessRun.id == ProcessStartJob.run_id)
        .where(
            ProcessRun.engine_code == engine_code,
            ProcessStartJob.status == "pending",
            ProcessStartJob.available_at <= now,
            or_(
                ProcessStartJob.locked_at.is_(None),
                ProcessStartJob.locked_at < now - timedelta(seconds=max(30, timeout * 2)),
            ),
        )
        .subquery()
    )
    ids = list(
        await get_db().scalars(
            select(ranked.c.id)
            .order_by(ranked.c.owner_position, ranked.c.available_at, ranked.c.id)
            .limit(4)
        )
    )
    await get_db().commit()

    async def start(identifier: int) -> int:
        async with get_db_session():
            try:
                return await process_service.process_start_jobs(
                    batch_size=1, engine_code=engine_code, job_id=identifier
                )
            except Exception:
                await get_db().rollback()
                logger.exception(
                    "Process admission failed for job {} on {}", identifier, engine_code
                )
                return 0

    async with asyncio.TaskGroup() as group:
        pending = [group.create_task(start(identifier)) for identifier in ids]
    return sum(task.result() for task in pending)


async def refresh_runs(identifiers: list[UUID]) -> int:
    """Each concurrent refresh owns its transaction; the caller released theirs."""
    slots = asyncio.Semaphore(4)

    async def refresh(identifier: UUID) -> int:
        async with slots, get_db_session():
            try:
                await process_service.refresh_run(identifier)
                return 1
            except Exception:
                await get_db().rollback()
                logger.exception("Automatic process refresh failed for {}", identifier)
                return 0

    return sum(await asyncio.gather(*(refresh(identifier) for identifier in identifiers)))
