"""RFC 5545 parsing and mutation isolated from persistence and dispatch."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Iterator
from typing import Any, Literal
from uuid import uuid4

import icalendar
import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    uid: str
    summary: str
    description: str
    location: str
    start: datetime
    end: datetime
    all_day: bool
    status: str
    transparent: bool


@dataclass(frozen=True, slots=True)
class DueCalendarAction:
    kind: Literal["start", "alarm"]
    occurrence_at: datetime
    event: ParsedEvent

    @property
    def fingerprint(self) -> str:
        raw = f"{self.kind}\0{self.event.uid}\0{self.event.start.isoformat()}\0{self.occurrence_at.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()


def _utc(value: datetime | date) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc), False
    return datetime.combine(value, time.min, tzinfo=timezone.utc), True


def _decoded(component: Any, name: str, default: object = None) -> object:
    try:
        return component.decoded(name, default)
    except (KeyError, ValueError, TypeError):
        return default


def _text(component: Any, name: str, limit: int) -> str:
    value = component.get(name)
    if value is None:
        return ""
    return str(value).replace("\x00", "")[:limit]


def _add(component: Any, name: str, value: object) -> None:
    """Keep the dynamically typed icalendar property encoder at one boundary."""

    component.add(name, value)


def _event(component: Any) -> ParsedEvent:
    raw_start = _decoded(component, "DTSTART")
    if not isinstance(raw_start, (datetime, date)):
        raise ValueError("Calendar event has no valid DTSTART")
    start, all_day = _utc(raw_start)
    raw_end = _decoded(component, "DTEND", raw_start)
    end, _ = _utc(raw_end if isinstance(raw_end, (datetime, date)) else raw_start)
    if end < start:
        end = start
    uid = _text(component, "UID", 255) or hashlib.sha256(
        f"{start.isoformat()}:{_text(component, 'SUMMARY', 500)}".encode()
    ).hexdigest()
    return ParsedEvent(
        uid=uid,
        summary=_text(component, "SUMMARY", 500),
        description=_text(component, "DESCRIPTION", 20_000),
        location=_text(component, "LOCATION", 1_000),
        start=start,
        end=end,
        all_day=all_day,
        status=_text(component, "STATUS", 50),
        transparent=_text(component, "TRANSP", 20).upper() == "TRANSPARENT",
    )


def parse_calendar(content: bytes) -> Any:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Calendar resource exceeds 5 MiB")
    try:
        return icalendar.Calendar.from_ical(content)
    except (ValueError, TypeError) as exc:
        raise ValueError("The resource is not a valid iCalendar document") from exc


def _bounded_components(calendar: Any, start: datetime, end: datetime, *, alarms: bool = False) -> Iterator[Any]:
    if end < start or end - start > timedelta(days=366):
        raise ValueError("Calendar range must be within 366 days")
    for alarm in calendar.walk("VALARM"):
        if int(alarm.get("REPEAT", 0)) > 1_000:
            raise ValueError("Calendar exceeds 1000 alarm repetitions")
    query = recurring_ical_events.of(calendar, components=["VALARM"] if alarms else ["VEVENT"], skip_bad_series=True)
    count = 0
    # query.between/after/paginate materialize a whole span internally. The
    # underlying series iterator permits stopping before converting occurrences.
    for series in query.series:
        for occurrence in series.between(start, end):
            count += 1
            if count > 1_000:
                raise ValueError("Calendar range exceeds 1000 occurrences; request a smaller range")
            yield occurrence.as_component(query.keep_recurrence_attributes)


def events_between(content: bytes, start: datetime, end: datetime) -> list[ParsedEvent]:
    calendar = parse_calendar(content)
    components = _bounded_components(calendar, start, end)
    result: dict[tuple[str, datetime], ParsedEvent] = {}
    for component in components:
        event = _event(component)
        if event.start < end and event.end >= start:
            result[(event.uid, event.start)] = event
    return sorted(result.values(), key=lambda item: (item.start, item.uid))


def due_actions(
    content: bytes,
    start: datetime,
    end: datetime,
    *,
    trigger_on_start: bool,
    trigger_on_alarm: bool,
) -> list[DueCalendarAction]:
    calendar = parse_calendar(content)
    due: dict[str, DueCalendarAction] = {}
    if trigger_on_start:
        components = _bounded_components(calendar, start, end)
        for component in components:
            event = _event(component)
            if start <= event.start < end:
                action = DueCalendarAction("start", event.start, event)
                due[action.fingerprint] = action
    if trigger_on_alarm:
        components = _bounded_components(calendar, start, end, alarms=True)
        for component in components:
            event = _event(component)
            alarms = getattr(getattr(component, "alarms", None), "times", ())
            for alarm in alarms:
                raw_trigger = getattr(alarm, "trigger", None)
                if isinstance(raw_trigger, (datetime, date)):
                    trigger, _ = _utc(raw_trigger)
                    if start <= trigger < end:
                        action = DueCalendarAction("alarm", trigger, event)
                        due[action.fingerprint] = action
    return sorted(due.values(), key=lambda item: (item.occurrence_at, item.fingerprint))


def create_event(content: bytes, data: Any) -> tuple[bytes, str]:
    calendar = parse_calendar(content)
    uid = (data.uid or f"{uuid4()}@galaris.local").strip()
    event = icalendar.Event()
    _add(event, "uid", uid)
    _add(event, "dtstamp", datetime.now(timezone.utc))
    _add(event, "summary", data.summary)
    _add(event, "description", data.description)
    _add(event, "location", data.location)
    _add(event, "dtstart", data.start)
    _add(event, "dtend", data.end)
    calendar.add_component(event)
    return calendar.to_ical(), uid


def update_event(content: bytes, uid: str, data: Any) -> bytes:
    calendar = parse_calendar(content)
    matches = [item for item in calendar.walk("VEVENT") if _text(item, "UID", 255) == uid]
    if not matches:
        raise LookupError("Calendar event not found")
    for event in matches:
        current_start = _decoded(event, "DTSTART")
        current_end = _decoded(event, "DTEND")
        next_start = data.start if data.start is not None else current_start
        next_end = data.end if data.end is not None else current_end
        if not isinstance(next_start, (datetime, date)) or not isinstance(next_end, (datetime, date)):
            raise ValueError("Calendar event has no valid start and end")
        next_start_is_datetime = isinstance(next_start, datetime)
        next_end_is_datetime = isinstance(next_end, datetime)
        if next_start_is_datetime != next_end_is_datetime or next_end <= next_start:
            raise ValueError("Updated event end must follow start with the same temporal type")
        for field, name in (
            (data.summary, "SUMMARY"),
            (data.description, "DESCRIPTION"),
            (data.location, "LOCATION"),
            (data.start, "DTSTART"),
            (data.end, "DTEND"),
        ):
            if field is not None:
                if name in event:
                    del event[name]
                _add(event, name.lower(), field)
        sequence = _decoded(event, "SEQUENCE", 0)
        event["SEQUENCE"] = int(sequence) + 1 if isinstance(sequence, int) else 1
        event["DTSTAMP"] = icalendar.vDatetime(datetime.now(timezone.utc))
    return calendar.to_ical()


def delete_event(content: bytes, uid: str) -> bytes:
    calendar = parse_calendar(content)
    retained: list[Any] = []
    found = False
    for component in calendar.subcomponents:
        if component.name == "VEVENT" and _text(component, "UID", 255) == uid:
            found = True
            continue
        retained.append(component)
    if not found:
        raise LookupError("Calendar event not found")
    calendar.subcomponents = retained
    return calendar.to_ical()


__all__ = [
    "DueCalendarAction",
    "ParsedEvent",
    "create_event",
    "delete_event",
    "due_actions",
    "events_between",
    "parse_calendar",
    "update_event",
]
