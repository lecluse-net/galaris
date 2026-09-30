"""Parent-level transaction locks shared by all configuration writers."""

from collections.abc import Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

from .models import Tool


async def lock_tools(tool_ids: Iterable[int], *, db: AsyncSession | None = None) -> None:
    db = db if db is not None else get_db()
    for tool_id in sorted(set(tool_ids)):
        await db.execute(text("SELECT pg_advisory_xact_lock(147, :tool_id)"), {"tool_id": tool_id})
        # Refresh any stale ORM identity after waiting, and block FK insertions during deletion.
        await db.execute(select(Tool).where(Tool.id == tool_id).with_for_update().execution_options(populate_existing=True))


async def finish_write(*, commit: bool, db: AsyncSession | None = None) -> None:
    db = db if db is not None else get_db()
    if commit:
        await db.commit()
    else:
        await db.flush()
