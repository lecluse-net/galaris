"""Local contact associations never enter provider iCalendar payloads."""

from uuid import UUID
from sqlalchemy import update
from core.database import get_db
from .models import CalendarEvent, CalendarEventRevision


async def update_contact_references(source: UUID, target: UUID | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, statement in (
        ("calendar_events", update(CalendarEvent).where(CalendarEvent.contact_id == source)
            .values(contact_id=target).execution_options(include_historized=True)),
        ("calendar_event_revisions", update(CalendarEventRevision).where(CalendarEventRevision.contact_id == source)
            .values(contact_id=target)),
    ):
        result = await get_db().execute(statement)
        count: object = getattr(result, "rowcount", 0)
        counts[key] = count if isinstance(count, int) else 0
    return counts
