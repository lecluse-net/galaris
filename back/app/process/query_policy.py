"""Transaction-local planner policy for interactive Process ACL queries."""

from sqlalchemy import text
from core.database import get_db


async def prepare_process_read() -> None:
    # Preserve the existing bounded-list policy without a dependency on Documents.
    # A commit or rollback restores the connection's ordinary JIT setting.
    await get_db().execute(text("SET LOCAL jit = off"))
