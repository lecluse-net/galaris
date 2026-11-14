"""Calendar business API. All reads and commands operate on local persistence."""
from __future__ import annotations

import asyncio
from bisect import bisect_right
from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from sqlalchemy import and_, func, or_, select, true, tuple_, update
from sqlalchemy.orm import aliased

from app.agent import inspect_task_states
from app.agent.contracts import AgentTaskState
from app.tools import tool_service
from app.connection import Connection, connection_service
from core.database import get_db, get_db_session
from core.params import runtime_settings
from . import ical, store
from .crypto import decrypt, encrypt
from .models import CalendarAction, CalendarEvent, CalendarFeed, CalendarOccurrence, CalendarTrigger
from .schemas import (CalendarActionRead, CalendarActionWrite, CalendarAvailability, CalendarConnectionEvent,
    CalendarConnectionStatus, CalendarEventCreate, CalendarEventDelete, CalendarEventWindow, CalendarEventRead,
    CalendarEventUpdate, CalendarFeedCreate, CalendarFeedRead, CalendarFeedUpdate, CalendarFreeSlot,
    CalendarMutationReceipt, CalendarReminderPage, CalendarReminderRead, CalendarReminderState, CalendarEventDetail,
    CalendarEventHistoryRead, CalendarConflictRead, CalendarSyncRunRead, CalendarExecutionReceipt, CalendarAlarmRead,
    CalendarOccurrenceSelection, CalendarExecutionSummary)
from .transport import validate_calendar_url


async def _calendar_connection(connection_id: int, *, require_active: bool = False) -> Connection:
    connection = await connection_service.get_connection(connection_id)
    if connection is None:
        raise LookupError("Calendar connection not found")
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is None or (tool.calendar is None and tool.code != "agenda"):
        raise ValueError("Connection is not a Calendar connection")
    if require_active and not connection.active:
        raise PermissionError("Calendar connection is inactive")
    return connection


async def _ensure_native_feed(connection: Connection) -> CalendarFeed:
    await get_db().execute(select(Connection.id).where(Connection.id == connection.id).with_for_update())
    feed = await get_db().scalar(select(CalendarFeed).where(CalendarFeed.connection_id == connection.id, CalendarFeed.is_default.is_(True)))
    if feed is None:
        # Adopt the original personal calendar created before the default marker existed.
        feed = await get_db().scalar(select(CalendarFeed).where(CalendarFeed.connection_id == connection.id,
            CalendarFeed.source_kind == "internal").order_by(CalendarFeed.created_at, CalendarFeed.id).limit(1))
    if feed is not None:
        feed.is_default = True
        feed.active = True
    else:
        feed = CalendarFeed(connection_id=connection.id, label="Personal agenda", source_kind="internal", is_default=True,
                            writable=True, initialized=True, actions_enabled=True, sync_requested=False)
        get_db().add(feed)
    await get_db().commit()
    return feed


async def connection_for_calendar(agent_id: int, calendar_id: int) -> int:
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    if connection.agent_id != agent_id:
        raise PermissionError("Calendar belongs to another agent")
    return feed.connection_id


async def connection_options(agent_ids: frozenset[int] | None = None) -> list[dict[str, Any]]:
    external = await connection_service.tool_connection_options("calendar", agent_ids=agent_ids, protocol=True)
    native = await connection_service.tool_connection_options("agenda", agent_ids=agent_ids)
    return native + external


async def calendar_authorization_changed(connection_id: int) -> None:
    """Fence old credentials and request a fresh read after consent or removal."""
    await get_db().execute(update(CalendarFeed).where(CalendarFeed.connection_id == connection_id).values(
        source_revision=CalendarFeed.source_revision + 1, lease_token=None, lease_expires_at=None,
        next_sync_at=None, sync_requested=True))


async def active_connection_for_agent(agent_id: int) -> Connection:
    from app.tools import current_protocol_connection, resolve_protocol_connection
    identity = current_protocol_connection("calendar", agent_id)
    if identity is None:
        identity = await resolve_protocol_connection(agent_id, "calendar")
    connection = await _calendar_connection(identity, require_active=True)
    if connection.agent_id != agent_id:
        raise PermissionError("Calendar connection belongs to another agent")
    return connection


async def _refresh_parameter_feed(connection_id: int) -> None:
    """Connection configuration projection only. Never performs external I/O."""
    connection = await _calendar_connection(connection_id)
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is not None and tool.code == "agenda":
        await _ensure_native_feed(connection)
        return
    if tool is None or tool.calendar is None:
        return
    await get_db().execute(select(Connection.id).where(Connection.id == connection_id).with_for_update())
    _, params = await connection_service.get_params_as_dict(connection, decrypt_passwords=True)
    mapping = tool.calendar.param_map
    kind = tool.calendar.settings.get("source_kind", "caldav")
    if kind not in ("ical", "caldav", "google", "microsoft", "icloud"):
        raise ValueError("Unknown calendar source kind")
    roots = {"google": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
             "microsoft": "https://graph.microsoft.com/v1.0/me/calendars", "icloud": "https://caldav.icloud.com/"}
    if kind not in roots and not mapping.get("url"):
        return
    try:
        url = roots[kind] if kind in roots else validate_calendar_url(str(params.get(mapping["url"]) or ""))
    except (ValueError, LookupError) as exc:
        raise ValueError("Invalid Calendar connection parameters") from exc
    feed = await get_db().scalar(select(CalendarFeed).where(CalendarFeed.connection_id == connection_id,
        CalendarFeed.is_default.is_(True)).execution_options(populate_existing=True))
    if feed is None:
        feed = CalendarFeed(connection_id=connection_id, label=tool.label, is_default=True,
            source_kind=kind, url_encrypted=encrypt(url), source_root_encrypted=encrypt(url))
        get_db().add(feed)
        await get_db().flush()
    if decrypt(feed.source_root_encrypted or feed.url_encrypted) != url or feed.source_kind != kind:
        exists = await get_db().scalar(select(CalendarEvent.id).join(CalendarFeed, CalendarFeed.id == CalendarEvent.calendar_id)
            .where(CalendarFeed.connection_id == connection_id)
            .execution_options(include_historized=True).limit(1))
        if exists is not None:
            raise ValueError("Use a new calendar connection to change an existing source identity")
        feed.url_encrypted, feed.source_kind = encrypt(url), kind
        feed.writable = False
        feed.source_root_encrypted = encrypt(url)
        feed.source_revision += 1
        feed.next_sync_at, feed.sync_requested = None, True
        feed.sync_token_encrypted, feed.remote_etag, feed.initialized = None, None, False
    for name in ("label", "owner_label"):
        parameter = mapping.get(name)
        value = str(params.get(parameter) or "").strip() if parameter else ""
        if value:
            setattr(feed, name, value)
    for field, parameter in (("username_encrypted", "username"), ("password_encrypted", "password")):
        value = str(params.get(mapping.get(parameter, "")) or "")
        if decrypt(getattr(feed, field)) != value:
            setattr(feed, field, encrypt(value) if value else None)
            feed.source_revision += 1
            feed.next_sync_at, feed.sync_requested = None, True
    siblings = (await get_db().scalars(select(CalendarFeed).where(CalendarFeed.connection_id == connection_id, CalendarFeed.id != feed.id))).all()
    interval_parameter = mapping.get("sync_interval_hours")
    interval_hours = int(str(params.get(interval_parameter) or "2")) if interval_parameter else feed.sync_interval_hours
    if not 1 <= interval_hours <= 8760:
        raise ValueError("Calendar synchronization interval must be a whole number of hours between 1 and 8760")
    for calendar in (feed, *siblings):
        calendar.sync_interval_hours = interval_hours
        anchor = calendar.last_checked_at or calendar.last_synced_at
        if anchor is not None and calendar.next_sync_at is not None:
            # Preserve explicit manual requests (next_sync_at=None), and converge
            # a deadline written by a worker using an older connection interval.
            calendar.next_sync_at = anchor + timedelta(hours=interval_hours)
    for sibling in siblings:
        if decrypt(sibling.username_encrypted) != decrypt(feed.username_encrypted) or decrypt(sibling.password_encrypted) != decrypt(feed.password_encrypted):
            sibling.username_encrypted, sibling.password_encrypted = feed.username_encrypted, feed.password_encrypted
            sibling.source_revision += 1
            sibling.next_sync_at, sibling.sync_requested = None, True
    zone = tool.calendar.settings.get("timezone", feed.timezone)
    ZoneInfo(zone)
    if feed.timezone != zone:
        feed.timezone = zone
        # Floating events need rebuilding when the calendar timezone changes.
        events = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id))).all())
        await store.project_events(feed, events, agent_id=connection.agent_id)
    for sibling in siblings:
        if sibling.timezone != zone:
            sibling.timezone = zone
            events = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == sibling.id))).all())
            await store.project_events(sibling, events, agent_id=connection.agent_id)
    await get_db().commit()


async def get_feed(calendar_id: int) -> CalendarFeed | None:
    return await get_db().scalar(select(CalendarFeed).where(CalendarFeed.id == calendar_id))


async def feed_context(calendar_id: int, *, require_active_connection: bool = False) -> tuple[CalendarFeed, Connection]:
    feed = await get_feed(calendar_id)
    if feed is None:
        raise LookupError("Calendar not found")
    connection = await _calendar_connection(feed.connection_id, require_active=require_active_connection)
    return feed, connection


def _scheduled_sync_at(feed: CalendarFeed) -> datetime | None:
    if feed.next_sync_at is None:
        return None
    anchor = feed.last_checked_at or feed.last_synced_at
    if anchor is None:
        return feed.next_sync_at
    return max(feed.next_sync_at, anchor + timedelta(hours=feed.sync_interval_hours))


def serialize_feed(feed: CalendarFeed, agent_id: int, *, tool_label: str = "") -> CalendarFeedRead:
    return CalendarFeedRead(id=feed.id, connection_id=feed.connection_id, agent_id=agent_id, label=feed.label,
        tool_label=tool_label, owner_label=feed.owner_label, source_kind=cast(Literal["internal", "ical", "caldav", "google", "microsoft", "icloud"], feed.source_kind), is_default=feed.is_default and feed.source_kind == "internal",
        origin=urlsplit(decrypt(feed.url_encrypted)).netloc, url_configured=bool(feed.url_encrypted),
        username_configured=bool(feed.username_encrypted), password_configured=bool(feed.password_encrypted),
        active=feed.active, writable=feed.writable, initialized=feed.initialized, actions_enabled=feed.actions_enabled,
        timezone=feed.timezone, last_synced_at=feed.last_synced_at, last_checked_at=feed.last_checked_at,
        last_error=feed.last_error, sync_interval_hours=feed.sync_interval_hours,
        next_sync_at=_scheduled_sync_at(feed), created_at=feed.created_at, updated_at=feed.updated_at)


async def list_feeds(*, connection_id: int | None = None, agent_id: int | None = None) -> list[CalendarFeedRead]:
    if connection_id is not None:
        exists = await get_db().scalar(select(CalendarFeed.id).where(CalendarFeed.connection_id == connection_id).limit(1))
        if exists is None:
            await _refresh_parameter_feed(connection_id)
    statement = select(CalendarFeed, Connection.agent_id, Connection.tool_id).join(Connection, Connection.id == CalendarFeed.connection_id)
    if connection_id is not None:
        statement = statement.where(CalendarFeed.connection_id == connection_id)
    if agent_id is not None:
        statement = statement.where(Connection.agent_id == agent_id)
    rows = (await get_db().execute(statement.order_by(CalendarFeed.label, CalendarFeed.id))).all()
    tools = await tool_service.get_tools_by_ids({tool_id for _, _, tool_id in rows})
    return [serialize_feed(feed, owner, tool_label=tools[tool_id].label if tool_id in tools else "")
            for feed, owner, tool_id in rows]


async def create_feed(data: CalendarFeedCreate) -> CalendarFeedRead:
    await _calendar_connection(data.connection_id, require_active=True)
    raise ValueError("Each agent has one automatic personal agenda; additional calendars must come from external Tools")


async def update_feed(calendar_id: int, data: CalendarFeedUpdate) -> CalendarFeedRead:
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    if feed.source_kind == "internal" and feed.is_default and data.active is False:
        raise ValueError("The default personal agenda cannot be disabled")
    for name in ("label", "owner_label", "active", "actions_enabled"):
        if name in data.model_fields_set:
            setattr(feed, name, getattr(data, name))
    if data.actions_enabled is not None:
        events = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id))).all())
        await store.project_events(feed, events, agent_id=connection.agent_id)
    await get_db().commit()
    await get_db().refresh(feed)
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    return serialize_feed(feed, connection.agent_id, tool_label=tool.label if tool else "")


async def delete_feed(calendar_id: int) -> bool:
    feed = await get_feed(calendar_id)
    if feed is None:
        return False
    if feed.is_default and feed.source_kind == "internal":
        raise ValueError("The default personal agenda cannot be deleted")
    feed.soft_delete()
    await get_db().commit()
    return True


async def _feeds_for_agent(agent_id: int, calendar_ids: Sequence[int] | None = None) -> list[CalendarFeed]:
    from app.tools import current_protocol_connection
    statement = select(CalendarFeed).join(Connection, Connection.id == CalendarFeed.connection_id).where(
        Connection.agent_id == agent_id, Connection.active.is_(True), CalendarFeed.active.is_(True))
    selected = current_protocol_connection("calendar", agent_id)
    if selected is not None:
        statement = statement.where(Connection.id == selected)
    if calendar_ids is not None:
        statement = statement.where(CalendarFeed.id.in_(calendar_ids))
    return list((await get_db().scalars(statement.order_by(CalendarFeed.id))).all())


def _stale(feed: CalendarFeed) -> bool:
    return feed.source_kind != "internal" and (not feed.initialized or bool(feed.last_error) or feed.last_synced_at is None
        or feed.last_synced_at < datetime.now(timezone.utc) - timedelta(hours=feed.sync_interval_hours, minutes=5))


def date_window(period: Literal["month", "week", "day", "next30"], month: str | None = None,
                timezone_name: str = "Europe/Paris", *, now: datetime | None = None) -> tuple[datetime, datetime]:
    from .schemas import validate_timezone
    validate_timezone(timezone_name)
    zone = ZoneInfo(timezone_name)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    if period == "next30":
        return current.astimezone(timezone.utc), (current + timedelta(days=30)).astimezone(timezone.utc)
    if period in ("day", "week"):
        lower = current.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "week":
            lower -= timedelta(days=lower.weekday())
        upper = lower + timedelta(days=7 if period == "week" else 1)
        return lower.astimezone(timezone.utc), upper.astimezone(timezone.utc)
    try:
        lower = datetime.fromisoformat((month or current.strftime("%Y-%m")) + "-01").replace(tzinfo=zone)
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM") from exc
    upper = lower.replace(year=lower.year + 1, month=1) if lower.month == 12 else lower.replace(month=lower.month + 1)
    return lower.astimezone(timezone.utc), upper.astimezone(timezone.utc)


def _event_read(feed: CalendarFeed, event: CalendarEvent, occurrence: CalendarOccurrence) -> CalendarEventRead:
    parsed = store.decode_occurrence(occurrence)
    state: Literal["local", "synced", "pending", "conflict"] = "local" if feed.source_kind == "internal" else "conflict" if event.conflict else "synced" if event.synced_revision == event.revision else "pending"
    return CalendarEventRead(event_id=event.id, occurrence_id=occurrence.id, recurrence_key=occurrence.recurrence_key,
        contact_id=event.contact_id,
        revision=event.revision, recurring=event.recurring, sync_state=state, calendar_id=feed.id, calendar_label=feed.label,
        uid=event.uid, summary=parsed.summary, description=parsed.description, location=parsed.location,
        start=parsed.start, end=parsed.end, all_day=parsed.all_day, status=parsed.status, transparent=parsed.transparent,
        start_date=parsed.start_date, end_date=parsed.end_date, timezone_name=parsed.timezone_name)


async def event_window(agent_id: int, start: datetime, end: datetime, *, calendar_ids: Sequence[int] | None = None,
                     ) -> CalendarEventWindow:
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=32):
        raise ValueError("Calendar queries require a timezone-aware window of at most one month")
    feeds = await _feeds_for_agent(agent_id, calendar_ids)
    for feed in feeds:
        await store.ensure_coverage(feed, start, end, agent_id)
    # Keep one indexed event lookup per occurrence even before PostgreSQL has
    # analyzed a large first import. A reorderable join can otherwise scan the
    # entire event index for each occurrence when its row estimate is still 1.
    resource = (select(CalendarEvent).where(CalendarEvent.id == CalendarOccurrence.event_id)
        .correlate(CalendarOccurrence).limit(1).lateral())
    event_row = aliased(CalendarEvent, resource)
    statement = select(CalendarOccurrence, event_row).select_from(CalendarOccurrence).join(resource, true()).where(
        CalendarOccurrence.calendar_id.in_([feed.id for feed in feeds]), CalendarOccurrence.start_at < end,
        or_(CalendarOccurrence.end_at > start, (CalendarOccurrence.start_at == CalendarOccurrence.end_at) & (CalendarOccurrence.start_at >= start)))
    rows = (await get_db().execute(statement.order_by(CalendarOccurrence.start_at, CalendarOccurrence.id).limit(10001))).all()
    if len(rows) > 10000:
        raise ValueError("Calendar window exceeds 10000 occurrences; request a shorter date range")
    feeds_by_id = {feed.id: feed for feed in feeds}
    stale = [feed.id for feed in feeds if _stale(feed)]
    await get_db().commit()
    return CalendarEventWindow(items=[_event_read(feeds_by_id[occurrence.calendar_id], event, occurrence) for occurrence, event in rows],
                             total=len(rows), complete=not stale, stale_calendar_ids=stale)


async def upcoming_context_events(agent_id: int, now: datetime) -> tuple[list[CalendarEventRead], list[int], bool] | None:
    """Return preference-bounded agenda occurrences, stale sources and overflow.

    None means no enabled read source; an empty list means an enabled but empty
    agenda. Ask permissions never authorize automatic context reads.
    """
    from app.connection.facade import resolve_function

    feeds = await _feeds_for_agent(agent_id)
    allowed_connections: dict[int, bool] = {}
    for feed in feeds:
        if feed.connection_id not in allowed_connections:
            connection = await connection_service.get_connection(feed.connection_id)
            policy = await resolve_function(connection, "calendar_events") if connection is not None else {}
            allowed_connections[feed.connection_id] = policy.get("effective_state") == "enabled"
    feeds = [feed for feed in feeds if allowed_connections[feed.connection_id]]
    if not feeds:
        return None
    until = now + timedelta(days=runtime_settings.AGENDA_CONTEXT_DAYS)
    for feed in feeds:
        await store.ensure_coverage(feed, now, until, agent_id)
    resource = (select(CalendarEvent).where(CalendarEvent.id == CalendarOccurrence.event_id)
        .correlate(CalendarOccurrence).limit(1).lateral())
    event_row = aliased(CalendarEvent, resource)
    rows = (await get_db().execute(
        select(CalendarOccurrence, event_row).select_from(CalendarOccurrence).join(resource, true()).where(
            CalendarOccurrence.calendar_id.in_([feed.id for feed in feeds]),
            CalendarOccurrence.cancelled.is_(False),
            CalendarOccurrence.start_at < until,
            (CalendarOccurrence.end_at > now) | (CalendarOccurrence.start_at >= now),
        ).order_by(CalendarOccurrence.start_at, CalendarOccurrence.id).limit(runtime_settings.AGENDA_CONTEXT_MAX_EVENTS + 1)
    )).all()
    feeds_by_id = {feed.id: feed for feed in feeds}
    limit = runtime_settings.AGENDA_CONTEXT_MAX_EVENTS
    return ([_event_read(feeds_by_id[occurrence.calendar_id], event, occurrence) for occurrence, event in rows[:limit]],
            [feed.id for feed in feeds if _stale(feed)], len(rows) > limit)


async def events_for_agent(agent_id: int, start: datetime, end: datetime, *, limit: int | None = 100,
                           calendar_ids: Sequence[int] | None = None) -> list[CalendarEventRead]:
    page = await event_window(agent_id, start, end, calendar_ids=calendar_ids)
    result = list(page.items)
    return result if limit is None else result[:max(1, min(limit, 500))]


async def availability_for_agent(agent_id: int, start: datetime, end: datetime, *, calendar_ids: Sequence[int] | None = None) -> CalendarAvailability:
    feeds = await _feeds_for_agent(agent_id, calendar_ids)
    stale = not feeds or any(_stale(feed) for feed in feeds)
    unsent = await get_db().scalar(select(CalendarEvent.id).where(CalendarEvent.calendar_id.in_([
        feed.id for feed in feeds if feed.source_kind not in ("internal", "ical")]), CalendarEvent.synced_revision < CalendarEvent.revision)
        .execution_options(include_historized=True).limit(1))
    stale = stale or unsent is not None
    events = await events_for_agent(agent_id, start, end, limit=None, calendar_ids=calendar_ids)
    conflicts = [event for event in events if not event.transparent and event.status.upper() != "CANCELLED"]
    return CalendarAvailability(start=start, end=end, available=None if stale else not conflicts, complete=not stale, conflicts=conflicts)


def _clock(value: object, fallback: str, name: str) -> time:
    raw = str(value or fallback).strip()
    try:
        parsed = time.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{name} must be a local time without timezone")
    return parsed


def _positive_int(value: object, fallback: int, name: str, maximum: int) -> int:
    try:
        parsed = fallback if value in (None, "") else int(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return parsed


async def find_free_slots_for_agent(agent_id: int, start: datetime, end: datetime, *, duration_minutes: int,
    timezone_name: str | None = None, workday_start: str | None = None, workday_end: str | None = None,
    step_minutes: int | None = None, include_weekends: bool = False, calendar_ids: Sequence[int] | None = None,
    limit: int = 10) -> list[CalendarFreeSlot]:
    if end <= start or end - start > timedelta(days=31) or not 5 <= duration_minutes <= 1440:
        raise ValueError("Invalid free-slot search range or duration")
    availability = await availability_for_agent(agent_id, start, end, calendar_ids=calendar_ids)
    if not availability.complete:
        raise ValueError("Calendar freshness is insufficient; availability is unknown")
    connection = await active_connection_for_agent(agent_id)
    _, params = await connection_service.get_params_as_dict(connection, decrypt_passwords=False)
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is not None and tool.calendar is not None and tool.calendar.settings:
        params = tool.calendar.settings
    try:
        zone = ZoneInfo(timezone_name or str(params.get("timezone") or "Europe/Paris"))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Invalid IANA timezone") from exc
    day_start = _clock(workday_start or params.get("workday_start"), "09:00", "workday_start")
    day_end = _clock(workday_end or params.get("workday_end"), "18:00", "workday_end")
    if day_end <= day_start:
        raise ValueError("workday_end must be after workday_start")
    step = _positive_int(step_minutes or params.get("slot_step_minutes"), 15, "step_minutes", 1440)
    # Merge once, then use logarithmic conflict lookups for each candidate.
    intervals: list[tuple[datetime, datetime]] = []
    for event in sorted(availability.conflicts, key=lambda row: row.start):
        if intervals and event.start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], event.end))
        else:
            intervals.append((event.start, event.end))
    starts = [lower for lower, _ in intervals]
    day = start.astimezone(zone).date()
    slots: list[CalendarFreeSlot] = []
    while day <= end.astimezone(zone).date() and len(slots) < min(50, max(1, limit)):
        if include_weekends or day.weekday() < 5:
            candidate = datetime.combine(day, day_start, zone)
            local_end = datetime.combine(day, day_end, zone)
            while candidate + timedelta(minutes=duration_minutes) <= local_end:
                finish = candidate + timedelta(minutes=duration_minutes)
                lower, upper = candidate.astimezone(timezone.utc), finish.astimezone(timezone.utc)
                index = bisect_right(starts, upper - timedelta(microseconds=1)) - 1
                conflict = index >= 0 and intervals[index][1] > lower
                if lower >= start and upper <= end and not conflict:
                    slots.append(CalendarFreeSlot(start=candidate, end=finish, timezone=zone.key))
                    if len(slots) >= min(50, max(1, limit)):
                        break
                candidate += timedelta(minutes=step)
        day += timedelta(days=1)
    return slots


async def _writable_calendar(calendar_id: int, agent_id: int) -> CalendarFeed:
    from app.tools import current_protocol_connection
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    selected = current_protocol_connection("calendar", agent_id)
    if connection.agent_id != agent_id or selected is not None and selected != connection.id:
        raise PermissionError("Calendar belongs to another agent or connection")
    if not feed.active or not feed.writable or feed.source_kind == "ical":
        raise PermissionError("Calendar is not writable")
    return feed


async def create_calendar_event(calendar_id: int, agent_id: int, data: CalendarEventCreate) -> CalendarMutationReceipt:
    feed = await _writable_calendar(calendar_id, agent_id)
    if data.contact_id is not None:
        from app.contact.facade import require_contact_reference
        await require_contact_reference(agent_id, data.contact_id)
    await get_db().execute(select(CalendarFeed.id).where(CalendarFeed.id == calendar_id).with_for_update())
    content, uid = ical.create_event(ical.EMPTY_CALENDAR, data)
    resource = (await asyncio.to_thread(ical.split_resources, content, feed.timezone))[0]
    if feed.source_kind in ("google", "microsoft") and resource.recurring:
        raise ValueError("Edit recurring Google or Microsoft series in the provider calendar")
    existing = await get_db().scalar(select(CalendarEvent).where(CalendarEvent.calendar_id == calendar_id, CalendarEvent.uid == uid)
        .execution_options(include_historized=True))
    if existing is not None:
        if existing.deleted_at is not None or existing.content_hash != resource.digest or existing.contact_id != data.contact_id:
            raise store.CalendarConflictError("Event UID already exists with different content")
        return mutation_receipt(feed, existing, "created")
    event = await store.save_resource(feed, resource, local=True, known=True, contact_id=data.contact_id)
    await store.project_events(feed, [event], agent_id=agent_id)
    await get_db().commit()
    return mutation_receipt(feed, event, "created")


async def update_calendar_event(calendar_id: int, agent_id: int, uid: str, data: CalendarEventUpdate) -> CalendarMutationReceipt:
    feed = await _writable_calendar(calendar_id, agent_id)
    if data.contact_id is not None:
        from app.contact.facade import require_contact_reference
        await require_contact_reference(agent_id, data.contact_id)
    event = await store.event_by_uid(calendar_id, uid, lock=True)
    if event.revision != data.expected_revision or event.conflict:
        raise store.CalendarConflictError("Calendar event changed; reload before editing")
    if feed.source_kind in ("google", "microsoft") and (event.recurring or data.rrule):
        raise ValueError("Edit recurring Google or Microsoft series in the provider calendar")
    if data.clear_contact or "contact_id" in data.model_fields_set:
        contact_id = None if data.clear_contact else data.contact_id
        if data.scope != "series" and contact_id != event.contact_id:
            raise ValueError("The linked contact belongs to the whole event; edit the series to change it")
        event.contact_id = contact_id
    content = await store.resource_content(event)
    if data.scope == "following" and (data.rrule is not None or data.clear_recurrence):
        before, after = await asyncio.to_thread(ical.split_following, content, uid, data)
        if before is not None:
            older = (await asyncio.to_thread(ical.split_resources, before, feed.timezone))[0]
            await store.save_resource(feed, older, local=True, existing=event, known=True)
            await store.project_events(feed, [event], agent_id=agent_id)
            newer = (await asyncio.to_thread(ical.split_resources, after, feed.timezone))[0]
            following = await store.save_resource(feed, newer, local=True, known=True, contact_id=event.contact_id)
            following.parent_event_id = event.id
            await store.project_events(feed, [following], agent_id=agent_id)
            await get_db().commit()
            return mutation_receipt(feed, following, "updated")
        data = data.model_copy(update={"scope": "series", "recurrence_key": None})
    updated = await asyncio.to_thread(ical.update_event, content, uid, data)
    resource = (await asyncio.to_thread(ical.split_resources, updated, feed.timezone))[0]
    event = await store.save_resource(feed, resource, local=True, existing=event, known=True)
    await store.project_events(feed, [event], agent_id=agent_id)
    await get_db().commit()
    return mutation_receipt(feed, event, "updated")


async def delete_calendar_event(calendar_id: int, agent_id: int, uid: str, data: CalendarEventDelete) -> CalendarMutationReceipt:
    feed = await _writable_calendar(calendar_id, agent_id)
    event = await store.event_by_uid(calendar_id, uid, lock=True)
    if event.revision != data.expected_revision or event.conflict:
        raise store.CalendarConflictError("Calendar event changed; reload before deleting")
    if feed.source_kind in ("google", "microsoft") and event.recurring and data.scope != "series":
        raise ValueError("Edit recurring Google or Microsoft occurrences in the provider calendar")
    if data.scope != "series":
        # Cancellation is a recurrence exception; never remove the master UID.
        content = await store.resource_content(event)
        updated = await asyncio.to_thread(ical.cancel_occurrence, content, uid, data.recurrence_key or "", data.scope == "following")
        resource = (await asyncio.to_thread(ical.split_resources, updated, feed.timezone))[0]
        await store.save_resource(feed, resource, local=True, existing=event, known=True)
        await store.project_events(feed, [event], agent_id=agent_id)
    else:
        await store.delete_local_event(feed, event, local=True)
    await get_db().commit()
    return mutation_receipt(feed, event, "deleted")


async def write_action(calendar_id: int, agent_id: int, uid: str, data: CalendarActionWrite, action_id: UUID | None = None) -> CalendarActionRead:
    from app.tools import current_protocol_connection
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    selected = current_protocol_connection("calendar", agent_id)
    if connection.agent_id != agent_id or not feed.active or selected is not None and selected != connection.id:
        raise PermissionError("Calendar is unavailable")
    event = await store.event_by_uid(calendar_id, uid, lock=True)
    if action_id is None and data.request_key is not None:
        identity = uuid5(event.id, str(data.request_key))
        existing = await get_db().get(CalendarAction, identity)
        if existing is not None:
            current = CalendarActionRead(id=existing.id, event_id=event.id, revision=existing.revision,
                recurrence_key=existing.recurrence_key, anchor=cast(Literal["start", "end"], existing.anchor),
                offset_minutes=existing.offset_minutes, instructions=decrypt(existing.instructions_encrypted),
                active=existing.active, max_lateness_minutes=existing.max_lateness_minutes)
            fields = data.model_dump(exclude={"expected_revision", "request_key"})
            if current.model_dump(include=set(fields)) != fields:
                raise store.CalendarConflictError("This launch request was already saved with different instructions; reload actions")
            return current
    action = await get_db().scalar(select(CalendarAction).where(CalendarAction.id == action_id, CalendarAction.event_id == event.id)) if action_id else None
    if action_id is not None and action is None:
        raise LookupError("Calendar action not found")
    if action is None:
        action = CalendarAction(id=uuid5(event.id, str(data.request_key)) if data.request_key else uuid4(), event_id=event.id, revision=1)
        get_db().add(action)
    else:
        if data.expected_revision != action.revision:
            raise store.CalendarConflictError("Calendar action changed; reload before editing")
        action.revision += 1
    action.recurrence_key, action.anchor, action.offset_minutes = data.recurrence_key, data.anchor, data.offset_minutes
    action.instructions_encrypted, action.active = encrypt(data.instructions), data.active
    action.max_lateness_minutes = data.max_lateness_minutes
    event.has_actions = True
    await get_db().flush()
    await store.project_events(feed, [event], agent_id=agent_id)
    await get_db().commit()
    return CalendarActionRead(id=action.id, event_id=event.id, revision=action.revision, **data.model_dump(exclude={"expected_revision", "request_key"}))


async def list_actions(calendar_id: int, uid: str) -> list[CalendarActionRead]:
    event = await store.event_by_uid(calendar_id, uid)
    actions = (await get_db().scalars(select(CalendarAction).where(CalendarAction.event_id == event.id))).all()
    return [CalendarActionRead(id=row.id, event_id=event.id, revision=row.revision, recurrence_key=row.recurrence_key,
        anchor=cast(Literal["start", "end"], row.anchor), offset_minutes=row.offset_minutes,
        instructions=decrypt(row.instructions_encrypted), active=row.active, max_lateness_minutes=row.max_lateness_minutes) for row in actions]


def _execution_state(row: CalendarTrigger, task: AgentTaskState | None, agent_id: int) -> CalendarReminderState:
    if task is not None and task.agent_id == agent_id:
        states: dict[str, CalendarReminderState] = {"QUEUED": "queued", "RUNNING": "running", "WAITING": "waiting", "PAUSED": "paused"}
        return "done" if task.status == "SUCCESS" else "error" if task.status in ("ERROR", "CANCELLED") else states.get(task.operational_state, "queued")
    return cast(CalendarReminderState, row.status) if row.status in ("scheduled", "cancelled", "skipped", "pending") else "dispatch_error" if row.status == "error" else "unavailable"


async def execution_summaries(connection_id: int, occurrences: Sequence[CalendarOccurrenceSelection]) -> list[CalendarExecutionSummary]:
    """Current state per action's latest launch, with total history size per occurrence."""
    connection = await _calendar_connection(connection_id)
    identities = {(row.event_id, row.recurrence_key) for row in occurrences}
    if not identities:
        return []
    predicate = (CalendarFeed.connection_id == connection_id) & tuple_(CalendarTrigger.event_id, CalendarTrigger.recurrence_key).in_(identities)
    totals = (await get_db().execute(select(CalendarTrigger.event_id, CalendarTrigger.recurrence_key, func.count())
        .join(CalendarFeed, CalendarFeed.id == CalendarTrigger.calendar_id).where(predicate)
        .group_by(CalendarTrigger.event_id, CalendarTrigger.recurrence_key))).all()
    counts = {(event_id, key): total for event_id, key, total in totals}
    rows = (await get_db().scalars(select(CalendarTrigger).join(CalendarFeed, CalendarFeed.id == CalendarTrigger.calendar_id)
        .where(predicate).distinct(CalendarTrigger.event_id, CalendarTrigger.recurrence_key, CalendarTrigger.action_key)
        .order_by(CalendarTrigger.event_id, CalendarTrigger.recurrence_key, CalendarTrigger.action_key, CalendarTrigger.launch_number.desc()))).all()
    tasks = await inspect_task_states([row.task_id for row in rows if row.task_id])
    result = {identity: CalendarExecutionSummary(event_id=identity[0], recurrence_key=identity[1], total=counts.get(identity, 0)) for identity in identities}
    for row in rows:
        state = _execution_state(row, tasks.get(row.task_id) if row.task_id else None, connection.agent_id)
        summary = result[(row.event_id, row.recurrence_key)]
        summary.states[state] = summary.states.get(state, 0) + 1
    return list(result.values())


async def list_reminders(connection_id: int, *, skip: int = 0, limit: int = 50,
                         event_id: UUID | None = None, recurrence_key: str | None = None) -> CalendarReminderPage:
    if skip < 0 or not 1 <= limit <= 500:
        raise ValueError("Invalid reminder pagination")
    connection = await _calendar_connection(connection_id)
    query = select(CalendarTrigger, CalendarFeed.label).join(CalendarFeed, CalendarFeed.id == CalendarTrigger.calendar_id).where(CalendarFeed.connection_id == connection_id)
    if event_id is not None:
        query = query.where(CalendarTrigger.event_id == event_id)
    if recurrence_key is not None:
        query = query.where(CalendarTrigger.recurrence_key == recurrence_key)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await get_db().execute(query.order_by(CalendarTrigger.occurrence_at.desc(), CalendarTrigger.id).offset(skip).limit(limit))).all()
    tasks = await inspect_task_states([row.task_id for row, _ in rows if row.task_id])
    from .dispatch import DispatchSnapshot
    result: list[CalendarReminderRead] = []
    for row, label in rows:
        snapshot = DispatchSnapshot.model_validate_json(decrypt(row.dispatch_encrypted))
        event_data = snapshot.payload.get("event")
        summary = str(cast(dict[str, object], event_data).get("summary") or row.event_uid) if isinstance(event_data, dict) else row.event_uid
        task = tasks.get(row.task_id) if row.task_id else None
        state = _execution_state(row, task, connection.agent_id)
        task_uri, task_status = None, None
        if task is not None and task.agent_id == connection.agent_id:
            task_uri, task_status = f"galaris://task/{row.task_id}", task.status
        result.append(CalendarReminderRead(id=row.id, calendar_id=row.calendar_id, calendar_label=label,
            event_uid=row.event_uid, event_summary=summary, reminder_at=row.occurrence_at, dispatch_status=row.status,
            task_uri=task_uri, task_status=task_status, state=state, treated=state == "done", event_id=row.event_id,
            recurrence_key=row.recurrence_key, action_key=row.action_key, reason=row.error_message))
    return CalendarReminderPage(items=result, total=total)


async def test_feed(calendar_id: int) -> CalendarConnectionStatus:
    """Inspect the local replica and request an asynchronous refresh."""
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    if not feed.active:
        raise PermissionError("Calendar is inactive")
    from .models import CalendarSyncRun
    await get_db().execute(select(CalendarFeed.id).where(CalendarFeed.id == calendar_id).with_for_update())
    run = await get_db().scalar(select(CalendarSyncRun).where(CalendarSyncRun.calendar_id == calendar_id,
        CalendarSyncRun.state.in_(("queued", "running"))).order_by(CalendarSyncRun.started_at.desc()).limit(1))
    if run is None and feed.source_kind != "internal":
        run = CalendarSyncRun(calendar_id=calendar_id, source_revision=feed.source_revision, stage="queued", state="queued")
        get_db().add(run)
        await get_db().flush()
    feed.sync_requested = True
    feed.next_sync_at = None
    now = datetime.now(timezone.utc)
    window = await event_window(connection.agent_id, now, now + timedelta(days=30), calendar_ids=[feed.id])
    return CalendarConnectionStatus(calendar_id=calendar_id, ok=not _stale(feed), sync_run_id=run.id if run else None, events_seen=window.total, next_events=[
        CalendarConnectionEvent(uid=row.uid, summary=row.summary, start=row.start, end=row.end, all_day=row.all_day) for row in window.items[:3]])


async def sync_calendars(*, source_kind: Literal["internal", "ical", "caldav", "google", "microsoft", "icloud"] | None = None) -> int:
    from .synchronization import synchronize_calendar
    valid_connections: list[int] = []
    for option in await connection_options():
        try:
            await _refresh_parameter_feed(int(option["id"]))
            valid_connections.append(int(option["id"]))
        except (ValueError, LookupError, PermissionError) as exc:
            await get_db().rollback()
            from .models import CalendarSyncRun
            category = type(exc).__name__
            feeds = (await get_db().scalars(select(CalendarFeed).where(CalendarFeed.connection_id == int(option["id"])))).all()
            changed = not feeds
            for feed in feeds:
                message = f"configuration: {category}"
                queued = (await get_db().scalars(select(CalendarSyncRun).where(CalendarSyncRun.calendar_id == feed.id,
                    CalendarSyncRun.state == "queued").with_for_update())).all()
                if queued or feed.last_error != message:
                    changed = True
                    feed.last_error = message
                    if not queued:
                        record = CalendarSyncRun(calendar_id=feed.id, source_revision=feed.source_revision)
                        get_db().add(record)
                        queued = [record]
                    for record in queued:
                        record.stage, record.state, record.error_category = "configuration", "error", category
                        record.finished_at = datetime.now(timezone.utc)
            await get_db().commit()
            if changed:
                logger.warning("Calendar connection configuration invalid connection_id={} error_category={}", option["id"], category)
    statement = select(CalendarFeed, Connection.agent_id).join(Connection, Connection.id == CalendarFeed.connection_id).where(
        CalendarFeed.active.is_(True), Connection.active.is_(True), Connection.id.in_(valid_connections))
    if source_kind is not None:
        statement = statement.where(CalendarFeed.source_kind == source_kind)
    else:
        statement = statement.where(CalendarFeed.source_kind != "internal")
    now = datetime.now(timezone.utc)
    statement = statement.where(or_(CalendarFeed.next_sync_at.is_(None), CalendarFeed.next_sync_at <= now))
    candidates = (await get_db().execute(statement)).all()
    rows = [(feed.id, agent_id) for feed, agent_id in candidates
            if (due := _scheduled_sync_at(feed)) is None or due <= now]
    await get_db().commit()
    semaphore = asyncio.Semaphore(1)
    async def run(calendar_id: int, agent_id: int) -> int:
        async with semaphore, get_db_session():
            return await synchronize_calendar(calendar_id, agent_id=agent_id, automatic=True)
    results = await asyncio.gather(*(run(calendar_id, agent_id) for calendar_id, agent_id in rows), return_exceptions=True)
    count = 0
    for (calendar_id, _), result in zip(rows, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Calendar sync worker failed calendar_id={} error_category={}", calendar_id, type(result).__name__)
        else:
            count += result
    return count


async def sync_native_calendars() -> int:
    from .dispatch import dispatch_due
    # Keep the rolling projection ahead of the scheduler without remote reads.
    horizon = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    feeds = (await get_db().execute(select(CalendarFeed, Connection.agent_id).join(Connection, Connection.id == CalendarFeed.connection_id)
        .where(CalendarFeed.active.is_(True), Connection.active.is_(True)))).all()
    for feed, agent_id in feeds:
        if not feed.actions_enabled:
            continue
        events = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id,
            or_(CalendarEvent.has_actions.is_(False), and_(CalendarEvent.recurring.is_(True),
                or_(CalendarEvent.actions_planned_until.is_(None), CalendarEvent.actions_planned_until < horizon + timedelta(days=365)))))
            .with_for_update())).all())
        await store.project_events(feed, events, agent_id=agent_id, start=horizon - timedelta(days=7), end=horizon + timedelta(days=366))
    await get_db().commit()
    return await dispatch_due()


async def sync_external_calendars() -> int:
    return await sync_calendars()


async def event_detail(calendar_id: int, uid: str, recurrence_key: str | None = None) -> CalendarEventDetail:
    feed, _ = await feed_context(calendar_id)
    event = await store.event_by_uid(calendar_id, uid, deleted=True)
    content = await store.resource_content(event)
    if recurrence_key is not None:
        occurrence = await get_db().scalar(select(CalendarOccurrence).where(CalendarOccurrence.event_id == event.id,
            CalendarOccurrence.recurrence_key == recurrence_key))
        parsed = await asyncio.to_thread(ical.event_for_occurrence, content, recurrence_key, feed.timezone, around=occurrence.start_at if occurrence else None)
    else:
        parsed = await asyncio.to_thread(ical.master_event, content, feed.timezone)
    rule, dates, excluded = await asyncio.to_thread(ical.recurrence_definition, content)
    return CalendarEventDetail(event_id=event.id, calendar_id=calendar_id, uid=event.uid, revision=event.revision,
        contact_id=event.contact_id,
        timezone=parsed.timezone_name, summary=parsed.summary, description=parsed.description, location=parsed.location,
        start=parsed.start, end=parsed.end, all_day=parsed.all_day, recurring=event.recurring,
        deleted=event.deleted_at is not None, parent_event_id=event.parent_event_id,
        start_date=parsed.start_date, end_date=parsed.end_date, rrule=rule, rdates=dates, exdates=excluded,
        alarms=[CalendarAlarmRead(key=row.key, at=row.at, anchor=row.anchor, offset_seconds=row.offset_seconds) for row in parsed.alarms],
        sync_state=mutation_receipt(feed, event, "updated").sync_state,
        ical=content.decode())


async def resolve_conflict(calendar_id: int, agent_id: int, uid: str, expected_revision: int,
                           choice: Literal["local", "remote"]) -> CalendarMutationReceipt:
    from .models import CalendarSyncOperation, CalendarEventRevision
    if choice == "local":
        feed = await _writable_calendar(calendar_id, agent_id)
    else:
        feed, connection = await feed_context(calendar_id, require_active_connection=True)
        if connection.agent_id != agent_id:
            raise PermissionError("Calendar belongs to another agent")
    event = await store.event_by_uid(calendar_id, uid, lock=True, deleted=True)
    if event.revision != expected_revision or not event.conflict:
        raise store.CalendarConflictError("Conflict version changed")
    if choice == "remote":
        content = decrypt(event.remote_content_encrypted)
        if content:
            resources = await asyncio.to_thread(ical.split_resources, content.encode(), feed.timezone)
            if len(resources) != 1 or resources[0].uid != event.uid:
                raise ValueError("Remote event identity changed")
            event = await store.save_resource(feed, resources[0], local=False, existing=event, known=True)
            await store.project_events(feed, [event], agent_id=agent_id)
        elif event.deleted_at is None:
            await store.delete_local_event(feed, event, local=False)
            event.synced_revision = event.revision
    else:
        event.revision += 1
        content = (await store.resource_content(event)).decode()
        get_db().add(CalendarEventRevision(event_id=event.id, revision=event.revision, contact_id=event.contact_id,
            content_encrypted=encrypt(content), deleting=event.deleted_at is not None))
        get_db().add(CalendarSyncOperation(calendar_id=calendar_id, event_id=event.id, revision=event.revision,
            deleting=event.deleted_at is not None, content_encrypted=encrypt(content), content_hash=event.content_hash))
        feed.sync_requested = True
        if event.deleted_at is None:
            await store.project_events(feed, [event], agent_id=agent_id)
    event.conflict = False
    await get_db().commit()
    return mutation_receipt(feed, event, "updated")


def mutation_receipt(feed: CalendarFeed, event: CalendarEvent, state: Literal["created", "updated", "deleted"]) -> CalendarMutationReceipt:
    sync_state: Literal["local", "pending", "synced", "conflict"] = "local" if feed.source_kind == "internal" else "conflict" if event.conflict else "synced" if event.synced_revision == event.revision else "pending"
    return CalendarMutationReceipt(calendar_id=feed.id, uid=event.uid, event_id=event.id, revision=event.revision,
                                   contact_id=event.contact_id,
                                   state=state, sync_state=sync_state)


async def event_history(calendar_id: int, uid: str, *, skip: int = 0, limit: int = 50) -> list[CalendarEventHistoryRead]:
    from .models import CalendarEventRevision
    event = await store.event_by_uid(calendar_id, uid, deleted=True)
    rows = (await get_db().scalars(select(CalendarEventRevision).where(CalendarEventRevision.event_id == event.id)
        .order_by(CalendarEventRevision.revision.desc()).offset(skip).limit(limit))).all()
    return [CalendarEventHistoryRead(revision=row.revision, contact_id=row.contact_id, deleted=row.deleting, created_at=row.created_at,
                                     ical=decrypt(row.content_encrypted)) for row in rows]


async def list_conflicts(calendar_id: int, *, skip: int = 0, limit: int = 50) -> list[CalendarConflictRead]:
    rows = (await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == calendar_id,
        CalendarEvent.conflict.is_(True)).execution_options(include_historized=True)
        .order_by(CalendarEvent.id).offset(skip).limit(limit))).all()
    return [CalendarConflictRead(event_id=row.id, uid=row.uid, revision=row.revision, local_deleted=row.deleted_at is not None,
        remote_deleted=row.remote_content_encrypted is None, local_ical=(await store.resource_content(row)).decode(),
        remote_ical=decrypt(row.remote_content_encrypted) if row.remote_content_encrypted else None) for row in rows]


async def sync_runs(calendar_id: int, *, skip: int = 0, limit: int = 50, run_id: UUID | None = None) -> list[CalendarSyncRunRead]:
    from .models import CalendarSyncRun
    query = select(CalendarSyncRun).where(CalendarSyncRun.calendar_id == calendar_id)
    if run_id is not None:
        query = query.where(CalendarSyncRun.id == run_id)
    rows = (await get_db().scalars(query
        .order_by(CalendarSyncRun.started_at.desc()).offset(skip).limit(limit))).all()
    result = [CalendarSyncRunRead.model_validate(row, from_attributes=True) for row in rows]
    for row in result:
        if row.state not in {"queued", "running"}:
            row.progress.steps = []
            row.progress.network_phase = None
            row.progress.transfer_completed, row.progress.transfer_total = 0, None
    return result


async def relaunch_execution(calendar_id: int, trigger_id: UUID, agent_id: int, request_key: UUID,
                             expected_event_revision: int) -> CalendarExecutionReceipt:
    from uuid import uuid5
    from .crypto import digest
    from .dispatch import DispatchSnapshot
    from app.agent import find_background_tasks
    feed, connection = await feed_context(calendar_id, require_active_connection=True)
    if connection.agent_id != agent_id or not feed.active or not feed.actions_enabled:
        raise PermissionError("Calendar actions are unavailable")
    original = await get_db().scalar(select(CalendarTrigger).where(CalendarTrigger.id == trigger_id, CalendarTrigger.calendar_id == calendar_id))
    if original is None:
        raise LookupError("Calendar execution not found")
    event = await get_db().scalar(select(CalendarEvent).where(CalendarEvent.id == original.event_id).with_for_update())
    if event is None or event.revision != expected_event_revision:
        raise store.CalendarConflictError("Calendar event changed")
    identity = uuid5(trigger_id, str(request_key))
    existing = await get_db().scalar(select(CalendarTrigger).where(CalendarTrigger.id == identity))
    if existing is not None:
        return CalendarExecutionReceipt(id=identity, task_uri=f"galaris://task/{existing.task_id}" if existing.task_id else None, state=existing.status)
    recovered = await find_background_tasks(agent_id, [f"calendar:{original.id}"])
    task_id = original.task_id or recovered.get(f"calendar:{original.id}")
    if task_id:
        task = (await inspect_task_states([task_id])).get(task_id)
        if task is None or task.operational_state != "TERMINAL":
            raise store.CalendarConflictError("The previous task is active or unavailable")
    elif original.status not in ("error", "cancelled", "skipped"):
        raise store.CalendarConflictError("The original execution has not finished")
    content = await store.resource_content(event)
    parsed = await asyncio.to_thread(ical.event_for_occurrence, content, original.recurrence_key, feed.timezone)
    action_revision = None
    if original.action_key.startswith("ical:"):
        if original.action_key not in {alarm.key for alarm in parsed.alarms}:
            raise store.CalendarConflictError("The calendar alarm no longer exists")
    elif original.action_key != store.EVENT_START_ACTION_KEY:
        action = await get_db().scalar(select(CalendarAction).where(CalendarAction.id == UUID(original.action_key),
            CalendarAction.event_id == event.id, CalendarAction.active.is_(True)))
        if action is None:
            raise store.CalendarConflictError("The calendar action no longer exists")
        action_revision = action.revision
    number = (await get_db().scalar(select(func.max(CalendarTrigger.launch_number)).where(CalendarTrigger.event_id == event.id,
        CalendarTrigger.recurrence_key == original.recurrence_key, CalendarTrigger.action_key == original.action_key)) or 0) + 1
    snapshot = DispatchSnapshot.model_validate_json(decrypt(original.dispatch_encrypted))
    snapshot.payload["triggered_at"] = datetime.now(timezone.utc).isoformat()
    row = CalendarTrigger(id=identity, calendar_id=calendar_id, event_id=event.id, recurrence_key=original.recurrence_key,
        action_key=original.action_key, action_revision=action_revision, launch_number=number, event_revision=event.revision,
        fingerprint=digest(f"{event.id}:{original.recurrence_key}:{original.action_key}:{number}"), event_uid=event.uid,
        occurrence_at=datetime.now(timezone.utc), dispatch_encrypted=encrypt(snapshot.model_dump_json()), status="scheduled")
    get_db().add(row)
    await get_db().commit()
    return CalendarExecutionReceipt(id=identity, task_uri=None, state="scheduled")
