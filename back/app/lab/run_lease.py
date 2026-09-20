"""Keep an inference claim alive without holding its database transaction open."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from sqlalchemy import update
from core.database import AsyncSessionLocal
from .models import LabEvaluationRun
from .run_contracts import RunClaim


async def renew(work: RunClaim) -> bool:
    # This background coroutine owns its short independent session.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(LabEvaluationRun)
            .where(
                LabEvaluationRun.id == work.run_id,
                LabEvaluationRun.lease_token == work.token,
                LabEvaluationRun.status == "running",
            )
            .values(lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=900))
            .returning(LabEvaluationRun.id)
        )
        owned = result.scalar_one_or_none() is not None
        await session.commit()
        return owned


@asynccontextmanager
async def keep_lease(work: RunClaim) -> AsyncGenerator[None]:
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(30)
            if not await renew(work):
                return

    task = asyncio.create_task(heartbeat())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
