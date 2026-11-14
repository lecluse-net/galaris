"""Parent-level transaction locks shared by all configuration writers."""

from collections.abc import Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

from .models import Service


async def lock_services(service_ids: Iterable[int], *, db: AsyncSession | None = None) -> None:
    db = db if db is not None else get_db()
    for service_id in sorted(set(service_ids)):
        await db.execute(text("SELECT pg_advisory_xact_lock(147, :service_id)"), {"service_id": service_id})
        # Refresh any stale ORM identity after waiting, and block FK insertions during deletion.
        await db.execute(select(Service).where(Service.id == service_id).with_for_update().execution_options(populate_existing=True))


async def finish_write(*, commit: bool, db: AsyncSession | None = None) -> None:
    db = db if db is not None else get_db()
    if commit:
        await db.commit()
    else:
        await db.flush()
