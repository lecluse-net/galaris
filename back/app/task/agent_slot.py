"""Shared transaction-level serialization for work owned by one agent."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


AGENT_SLOT_LOCK_NAMESPACE = 0x47414C  # "GAL"


async def try_lock_agent(db: AsyncSession, agent_id: int) -> bool:
    """Reserve an agent until the current transaction ends.

    Task claims and Goal cycle creation use the same PostgreSQL advisory lock, preventing two
    workers from assigning concurrent work to one agent across processes.
    """

    locked = await db.scalar(
        select(func.pg_try_advisory_xact_lock(AGENT_SLOT_LOCK_NAMESPACE, agent_id))
    )
    return bool(locked)
