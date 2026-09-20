"""Paged diagnostic export before retention; never export callback credentials."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from .models import ProcessRun, ProcessRunEvent
from .sanitizer import sanitize
from .schemas import ProcessRunRead, ProcessRunEventRead


async def export_run(
    run_id: UUID,
    *,
    after_event: int = 0,
    page_size: int = 50,
) -> dict[str, Any]:
    db = get_db()
    run = await db.scalar(
        select(ProcessRun).where(ProcessRun.id == run_id).execution_options(populate_existing=True)
    )
    if run is None:
        raise LookupError("Process run not found")
    limit = max(1, min(page_size, 500))
    events = list(
        await db.scalars(
            select(ProcessRunEvent)
            .where(ProcessRunEvent.run_id == run_id, ProcessRunEvent.id > after_event)
            .order_by(ProcessRunEvent.id)
            .limit(limit + 1)
        )
    )
    page = events[:limit]
    return {
        "version": 1,
        "run": sanitize(ProcessRunRead.model_validate(run).model_dump(mode="json")),
        "raw_snapshot": sanitize(run.raw_snapshot),
        # Launch file URLs contain capabilities; omit them even in admin exports.
        "launch_snapshot": sanitize(run.launch_snapshot, deny_keys={"download_url"}),
        "events": [
            sanitize(ProcessRunEventRead.model_validate(event).model_dump(mode="json"))
            for event in page
        ],
        "next_event": page[-1].id if len(events) > limit else None,
    }
