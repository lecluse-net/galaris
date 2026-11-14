"""One temporal read composition for agent context and calendar tools."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.connection.facade import has_active_tool_function
from app.memory.facade import MemoryAgendaOccurrence, memory_agenda

from .schemas import CalendarEventRead, CalendarEventWindow


def memory_event(item: MemoryAgendaOccurrence) -> CalendarEventRead:
    zone = ZoneInfo(item.timezone)
    return CalendarEventRead(source_kind="memory", source_uri=item.uri, informational=True,
        temporal=item.temporal.model_dump(), event_id=item.id, occurrence_id=item.id,
        recurrence_key=item.start.isoformat(), calendar_id=-1, calendar_label="Memory",
        uid=str(item.id), summary=item.title, description=item.excerpt, revision=item.revision,
        start=item.start, end=item.end, all_day=item.all_day, timezone_name=item.timezone,
        start_date=item.start.astimezone(zone).date() if item.all_day else None,
        end_date=item.end.astimezone(zone).date() if item.all_day else None, transparent=True)


async def memory_read_enabled(agent_id: int) -> bool:
    return await has_active_tool_function(agent_id, "memory", "memory_upcoming")


async def with_memory_events(
    page: CalendarEventWindow, agent_id: int, start: datetime, end: datetime, *,
    contact_item_id: UUID | None = None, include_memory: bool = True, limit: int = 10_000,
) -> CalendarEventWindow:
    if not include_memory or not await memory_read_enabled(agent_id):
        return page
    memories = await memory_agenda(agent_id, start, end, contact_item_id=contact_item_id, limit=limit)
    items = [*page.items, *(memory_event(item) for item in memories.items)]
    items.sort(key=lambda item: (item.start, item.source_kind, item.uid))
    return page.model_copy(update={"items": items, "total": len(items), "complete": page.complete and memories.complete})
