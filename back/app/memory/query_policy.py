"""Planner policy for bounded Memory reads with extensive permission checks."""

from sqlalchemy import text

from core.database import get_db


async def prepare_memory_read() -> None:
    """Keep JIT compilation out of interactive reads, for this transaction only.

    Synthetic plans spend seconds compiling source/structural predicates whose
    execution takes milliseconds. SET LOCAL preserves the connection's default
    for its next transaction, including after rollback.
    """
    await get_db().execute(text("SET LOCAL jit = off"))
