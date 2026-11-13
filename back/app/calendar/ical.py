"""iCalendar codec. Dynamic library objects never escape this module."""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, TYPE_CHECKING, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]
if TYPE_CHECKING:
    from .schemas import CalendarEventCreate, CalendarEventUpdate


@dataclass(frozen=True, slots=True)
class ParsedAlarm:
    key: str
    at: datetime
    anchor: Literal["start", "end", "absolute"] = "start"
    offset_seconds: int | None = None


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
    recurrence_key: str = ""
    alarms: tuple[ParsedAlarm, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    timezone_name: str = "UTC"


@dataclass(frozen=True, slots=True)
class EventResource:
    uid: str
    master: str
    exceptions: tuple[tuple[str, str], ...]
    start: datetime
    end: datetime
    recurring: bool
    digest: str
    has_alarms: bool = False


@dataclass(frozen=True, slots=True)
class DueCalendarAction:
    kind: Literal["start", "alarm"]
    occurrence_at: datetime
    event: ParsedEvent
    action_key: str = "ical:0"

    @property
    def fingerprint(self) -> str:
        raw = f"{self.event.uid}\0{self.event.recurrence_key}\0{self.action_key}"
        return hashlib.sha256(raw.encode()).hexdigest()


def temporal_key(value: datetime | date, zone: str = "UTC") -> str:
    return "T:" + _utc(value, zone)[0].isoformat() if isinstance(value, datetime) else "D:" + value.isoformat()


def key_value(key: str, original: datetime | date, zone: str) -> datetime | date:
    if key.startswith("D:") and not isinstance(original, datetime):
        return date.fromisoformat(key[2:])
    if key.startswith("T:") and isinstance(original, datetime):
        value = datetime.fromisoformat(key[2:])
        return value.astimezone(original.tzinfo or ZoneInfo(zone))
    raise ValueError("Occurrence identity does not match the event temporal type")


def _utc(value: datetime | date, zone: str = "UTC") -> tuple[datetime, bool]:
    local_zone = ZoneInfo(zone)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=local_zone)).astimezone(timezone.utc), False
    return datetime.combine(value, time.min, tzinfo=local_zone).astimezone(timezone.utc), True


def _decoded(component: Any, name: str, default: object = None) -> Any:
    try:
        return component.decoded(name, default)
    except (KeyError, ValueError, TypeError):
        return default


def _text(component: Any, name: str, limit: int) -> str:
    return str(component.get(name, "")).replace("\x00", "")[:limit]


def _add(component: Any, name: str, value: object) -> None:
    component.add(name, value)


def _event(component: Any, zone: str = "UTC", *, compact: bool = False) -> ParsedEvent:
    raw_start = _decoded(component, "DTSTART")
    if not isinstance(raw_start, (datetime, date)):
        raise ValueError("Calendar event has no valid DTSTART")
    start, all_day = _utc(raw_start, zone)
    raw_end = _decoded(component, "DTEND")
    if raw_end is None:
        duration = _decoded(component, "DURATION")
        raw_end = raw_start + (duration if isinstance(duration, timedelta) else timedelta(days=1) if all_day else timedelta())
    if not isinstance(raw_end, (datetime, date)):
        raise ValueError("Calendar event has no valid end")
    end, _ = _utc(raw_end, zone)
    if end < start:
        raise ValueError("Calendar event end precedes start")
    uid = _text(component, "UID", 255)
    if not uid:
        raise ValueError("Calendar event requires a UID")
    recurrence = _decoded(component, "RECURRENCE-ID", raw_start)
    if not isinstance(recurrence, (datetime, date)):
        raise ValueError("Invalid RECURRENCE-ID")
    alarms: list[ParsedAlarm] = []
    if _text(component, "STATUS", 50).upper() != "CANCELLED":
        for alarm in component.walk("VALARM"):
            trigger = _decoded(alarm, "TRIGGER")
            if isinstance(trigger, timedelta):
                anchor_name: Literal["start", "end", "absolute"] = "end" if str(alarm["TRIGGER"].params.get("RELATED", "START")).upper() == "END" else "start"
                at = (end if anchor_name == "end" else start) + trigger
                offset_seconds = int(trigger.total_seconds())
            elif isinstance(trigger, (datetime, date)):
                at = _utc(trigger, zone)[0]
                anchor_name, offset_seconds = "absolute", None
            else:
                raise ValueError("Invalid calendar alarm trigger")
            uid_value = _text(alarm, "UID", 1000)
            semantic_key = uid_value or f"{alarm.get('ACTION')}:{trigger}:{anchor_name}:{alarm.get('REPEAT', 0)}:{_decoded(alarm, 'DURATION')}"
            identity = hashlib.sha256(semantic_key.encode()).hexdigest()[:48]
            alarms.append(ParsedAlarm(f"ical:{identity}:0", at, anchor_name, offset_seconds))
            repeats = int(alarm.get("REPEAT", 0))
            interval = _decoded(alarm, "DURATION")
            if repeats < 0 or repeats > 1000 or repeats and (not isinstance(interval, timedelta) or interval <= timedelta()):
                raise ValueError("Invalid or excessive alarm repetition")
            if isinstance(interval, timedelta):
                alarms.extend(ParsedAlarm(f"ical:{identity}:{i}", at + interval * i, anchor_name,
                    offset_seconds + int(interval.total_seconds()) * i if offset_seconds is not None else None) for i in range(1, repeats + 1))
    return ParsedEvent(uid, _text(component, "SUMMARY", 500), "" if compact else _text(component, "DESCRIPTION", 20000),
        _text(component, "LOCATION", 1000), start, end, all_day, _text(component, "STATUS", 50),
        _text(component, "TRANSP", 20).upper() == "TRANSPARENT", temporal_key(recurrence, zone), tuple(alarms),
        raw_start if all_day and not isinstance(raw_start, datetime) else None,
        raw_end if all_day and not isinstance(raw_end, datetime) else None,
        str(getattr(raw_start.tzinfo, "key", None) or component["DTSTART"].params.get("TZID")
            or ("UTC" if raw_start.tzinfo is not None and raw_start.utcoffset() == timedelta() else zone)) if isinstance(raw_start, datetime) else zone)


def parse_calendar(content: bytes) -> Any:
    if len(content) > 64 * 1024 * 1024:
        raise ValueError("Calendar resource exceeds 64 MiB")
    try:
        result = icalendar.Calendar.from_ical(content)
        if result.name != "VCALENDAR":
            raise ValueError("Expected VCALENDAR")
        return result
    except (ValueError, TypeError) as exc:
        raise ValueError("The resource is not a valid iCalendar document") from exc


def _calendar(parts: Sequence[Any], zones: Sequence[Any] = ()) -> bytes:
    calendar = icalendar.Calendar()
    _add(calendar, "version", "2.0")
    _add(calendar, "prodid", "-//Galaris Agenda//EN")
    for component in (*zones, *parts):
        # This helper serializes immediately and never mutates its components.
        calendar.add_component(component)
    return calendar.to_ical()


def resource_digest(content: bytes) -> str:
    calendar = parse_calendar(content)
    return _digest_parts(calendar.walk("VEVENT"))


def _digest_parts(events: Sequence[Any]) -> str:
    normalized: list[bytes] = []
    for event in events:
        item: Any = icalendar.Event()
        for key, value in event.items():
            if key not in ("DTSTAMP", "LAST-MODIFIED", "CREATED"):
                item[key] = value
        item.subcomponents = list(event.subcomponents)
        normalized.append(item.to_ical(sorted=True))
    return hashlib.sha256(b"\0".join(sorted(normalized))).hexdigest()


def split_resources(content: bytes, zone: str = "UTC") -> list[EventResource]:
    calendar = parse_calendar(content)
    zones = {str(zone.get("TZID")): zone for zone in calendar.walk("VTIMEZONE")}
    groups: dict[str, list[Any]] = {}
    for component in calendar.walk("VEVENT"):
        uid = _text(component, "UID", 255)
        if not uid:
            raise ValueError("Calendar event requires a UID")
        groups.setdefault(uid, []).append(component)
        if len(groups) > 100000:
            raise ValueError("Calendar exceeds 100000 resources")
    result: list[EventResource] = []
    for uid, parts in groups.items():
        masters = [part for part in parts if "RECURRENCE-ID" not in part]
        if len(masters) != 1:
            raise ValueError("A series must have exactly one master event")
        master = masters[0]
        parsed = _event(master, zone)
        zone_names = {str(value.params["TZID"]) for part in parts for _, value in part.property_items()
                      if hasattr(value, "params") and "TZID" in value.params}
        relevant_zones = [zone for name, zone in zones.items() if name in zone_names]
        master_content = _calendar([master], relevant_zones).decode()
        exceptions: list[tuple[str, str]] = []
        for part in parts:
            if "RECURRENCE-ID" in part:
                exceptions.append((_event(part, zone).recurrence_key, _calendar([part], relevant_zones).decode()))
        if len({key for key, _ in exceptions}) != len(exceptions):
            raise ValueError("Duplicate recurrence exceptions")
        if len(master_content.encode()) + sum(len(value.encode()) for _, value in exceptions) > 5 * 1024 * 1024:
            raise ValueError("An individual calendar event resource exceeds 5 MiB")
        result.append(EventResource(uid, master_content, tuple(exceptions), parsed.start, parsed.end,
            any(name in master for name in ("RRULE", "RDATE")) or bool(exceptions), _digest_parts(parts),
            any(bool(part.walk("VALARM")) for part in parts)))
    return result


def join_resource(master: str, exceptions: Sequence[str]) -> bytes:
    base = parse_calendar(master.encode())
    for value in exceptions:
        for component in parse_calendar(value.encode()).walk("VEVENT"):
            base.add_component(component)
    return base.to_ical()


def combine_resources(contents: Sequence[bytes]) -> bytes:
    parts: list[Any] = []
    zones: dict[str, Any] = {}
    for content in contents:
        calendar = parse_calendar(content)
        parts.extend(calendar.walk("VEVENT"))
        for zone in calendar.walk("VTIMEZONE"):
            zones[str(zone.get("TZID"))] = zone
    return _calendar(parts, list(zones.values()))


def master_event(content: bytes, zone: str = "UTC") -> ParsedEvent:
    parts = [part for part in parse_calendar(content).walk("VEVENT") if "RECURRENCE-ID" not in part]
    if len(parts) != 1:
        raise ValueError("Expected exactly one master event")
    return _event(parts[0], zone)


def _bounded_components(calendar: Any, start: datetime, end: datetime, *, alarms: bool = False) -> Iterator[Any]:
    if end <= start or end - start > timedelta(days=3660):
        raise ValueError("Calendar range must be positive and within 3660 days")
    query = recurring_ical_events.of(calendar, components=["VEVENT"], skip_bad_series=False)
    for series in query.series:
        count = 0
        for occurrence in series.between(start, end):
            count += 1
            if count > 1000:
                raise ValueError("One series exceeds 1000 occurrences; request a smaller range")
            yield occurrence.as_component(True)


def events_between(content: bytes, start: datetime, end: datetime, zone: str = "UTC", *, compact: bool = False) -> list[ParsedEvent]:
    calendar = parse_calendar(content)
    result: dict[tuple[str, str], ParsedEvent] = {}
    for component in _bounded_components(calendar, start, end):
        event = _event(component, zone, compact=compact)
        if event.start < end and (event.end > start or event.end == event.start and event.start >= start):
            result[(event.uid, event.recurrence_key)] = event
    return sorted(result.values(), key=lambda item: (item.start, item.uid))


def due_actions(content: bytes, start: datetime, end: datetime) -> list[DueCalendarAction]:
    # Compatibility for codec callers; production dispatch reads indexed deadlines.
    result: dict[str, DueCalendarAction] = {}
    for event in events_between(content, start - timedelta(days=366), end + timedelta(days=366)):
        for alarm in event.alarms:
            if start <= alarm.at < end:
                action = DueCalendarAction("alarm", alarm.at, event, alarm.key)
                result[action.fingerprint] = action
    return sorted(result.values(), key=lambda item: (item.occurrence_at, item.fingerprint))


def create_event(content: bytes, data: CalendarEventCreate) -> tuple[bytes, str]:
    calendar = parse_calendar(content)
    uid = (data.uid or f"{uuid4()}@galaris.local").strip()
    if any(_text(part, "UID", 255) == uid for part in calendar.walk("VEVENT")):
        raise ValueError("Event UID already exists")
    event = icalendar.Event()
    for name, value in (("uid", uid), ("dtstamp", datetime.now(timezone.utc)), ("summary", data.summary),
                        ("description", data.description), ("location", data.location),
                        ("dtstart", data.start.astimezone(ZoneInfo(data.timezone)) if isinstance(data.start, datetime) else data.start),
                        ("dtend", data.end.astimezone(ZoneInfo(data.timezone)) if isinstance(data.end, datetime) else data.end)):
        _add(event, name, value)
    if data.rrule:
        _add(event, "rrule", icalendar.vRecur.from_ical(data.rrule))
    for name, dates in (("rdate", data.rdates), ("exdate", data.exdates)):
        if dates:
            _add(event, name, dates)
    _set_reminder(event, data.reminder_minutes_before, data.summary)
    calendar.add_component(event)
    return calendar.to_ical(), uid


def _set_reminder(event: Any, minutes: int | None, summary: str) -> None:
    if minutes is None:
        return
    event.subcomponents = [part for part in event.subcomponents if part.name != "VALARM"]
    alarm = icalendar.Alarm()
    for name, value in (("action", "DISPLAY"), ("description", summary), ("trigger", -timedelta(minutes=minutes))):
        _add(alarm, name, value)
    event.add_component(alarm)


def update_event(content: bytes, uid: str, data: CalendarEventUpdate) -> bytes:
    calendar = parse_calendar(content)
    matches = [part for part in calendar.walk("VEVENT") if _text(part, "UID", 255) == uid]
    master = next((part for part in matches if "RECURRENCE-ID" not in part), None)
    if master is None:
        raise LookupError("Calendar event not found")
    target = master
    if data.scope != "series":
        original = _decoded(master, "DTSTART")
        recurrence = key_value(data.recurrence_key or "", original, "UTC")
        target = next((part for part in matches if "RECURRENCE-ID" in part and temporal_key(_decoded(part, "RECURRENCE-ID")) == data.recurrence_key), None)
        if target is None:
            instant = _utc(recurrence)[0]
            candidates = list(_bounded_components(calendar, instant - timedelta(days=1), instant + timedelta(days=1)))
            candidate = next((part for part in candidates if _event(part).recurrence_key == data.recurrence_key), None)
            if candidate is None:
                raise LookupError("Calendar occurrence not found")
            target = copy.deepcopy(candidate)
            for name in ("RRULE", "RDATE", "EXDATE"):
                target.pop(name, None)
            target.pop("RECURRENCE-ID", None)
            target.add("recurrence-id", recurrence)
            calendar.add_component(target)
        if data.scope == "following":
            target["RECURRENCE-ID"].params["RANGE"] = "THISANDFUTURE"
            if data.rrule is not None or data.clear_recurrence:
                raise ValueError("Changing the repetition rule for following instances requires splitting the series")
    if data.start is not None or data.end is not None:
        next_start = data.start if data.start is not None else _decoded(target, "DTSTART")
        next_end = data.end if data.end is not None else _decoded(target, "DTEND")
        if not isinstance(next_start, (date, datetime)) or not isinstance(next_end, (date, datetime)) or isinstance(next_start, datetime) != isinstance(next_end, datetime) or next_end <= next_start:
            raise ValueError("Updated event end must follow start with the same temporal type")
    raw_start = _decoded(target, "DTSTART")
    zone = data.timezone or (str(getattr(raw_start.tzinfo, "key", None) or "UTC") if isinstance(raw_start, datetime) else "UTC")
    for value, name in ((data.summary, "SUMMARY"), (data.description, "DESCRIPTION"), (data.location, "LOCATION"), (data.start, "DTSTART"), (data.end, "DTEND")):
        if value is not None:
            target.pop(name, None)
            target.add(name.lower(), value.astimezone(ZoneInfo(zone)) if isinstance(value, datetime) else value)
    if data.clear_recurrence:
        for name in ("RRULE", "RDATE", "EXDATE"):
            target.pop(name, None)
    elif data.rrule is not None:
        target.pop("RRULE", None)
        target.add("rrule", icalendar.vRecur.from_ical(data.rrule))
    target["SEQUENCE"] = int(target.get("SEQUENCE", 0)) + 1
    target["DTSTAMP"] = icalendar.vDatetime(datetime.now(timezone.utc))
    if data.clear_reminder:
        target.subcomponents = [part for part in target.subcomponents if part.name != "VALARM"]
    _set_reminder(target, data.reminder_minutes_before, _text(target, "SUMMARY", 500))
    return calendar.to_ical()


def delete_event(content: bytes, uid: str) -> bytes:
    calendar = parse_calendar(content)
    retained = [part for part in calendar.subcomponents if part.name != "VEVENT" or _text(part, "UID", 255) != uid]
    if len(retained) == len(calendar.subcomponents):
        raise LookupError("Calendar event not found")
    calendar.subcomponents = retained
    return calendar.to_ical()


EMPTY_CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Galaris Agenda//EN\r\nEND:VCALENDAR\r\n"


def cancel_occurrence(content: bytes, uid: str, recurrence_key: str, following: bool = False) -> bytes:
    from .schemas import CalendarEventUpdate
    data = CalendarEventUpdate(expected_revision=1, scope="following" if following else "occurrence", recurrence_key=recurrence_key)
    updated = update_event(content, uid, data)
    calendar = parse_calendar(updated)
    target = next((part for part in calendar.walk("VEVENT") if "RECURRENCE-ID" in part and temporal_key(_decoded(part, "RECURRENCE-ID")) == recurrence_key), None)
    if target is None:
        raise LookupError("Calendar occurrence not found")
    target["STATUS"] = "CANCELLED"
    return calendar.to_ical()


def _date_properties(component: Any, name: str) -> list[datetime | date]:
    properties: Any = component.get(name, [])
    values: list[datetime | date] = []
    for prop in cast(list[Any], properties) if isinstance(properties, list) else [properties]:
        for item in getattr(prop, "dts", ()):
            if isinstance(item.dt, (datetime, date)):
                values.append(item.dt)
    return values


def split_following(content: bytes, uid: str, data: CalendarEventUpdate) -> tuple[bytes | None, bytes]:
    """Split a repetition-rule change without generating one override per date."""
    from uuid import NAMESPACE_URL, uuid5
    calendar = parse_calendar(content)
    parts = calendar.walk("VEVENT")
    master = next(part for part in parts if "RECURRENCE-ID" not in part)
    original = _decoded(master, "DTSTART")
    recurrence = key_value(data.recurrence_key or "", original, "UTC")
    if temporal_key(original) == data.recurrence_key:
        return None, update_event(content, uid, data.model_copy(update={"scope": "series", "recurrence_key": None}))
    instant = _utc(recurrence)[0]
    target = next((part for part in parts if "RECURRENCE-ID" in part and temporal_key(_decoded(part, "RECURRENCE-ID")) == data.recurrence_key), None)
    if target is None:
        target = next((part for part in _bounded_components(calendar, instant - timedelta(days=1), instant + timedelta(days=1))
            if _event(part).recurrence_key == data.recurrence_key), None)
    if target is None:
        raise LookupError("Calendar occurrence not found")
    before = copy.deepcopy(master)
    after = copy.deepcopy(target)
    new_uid = f"{uuid5(NAMESPACE_URL, uid + ':' + (data.recurrence_key or ''))}@galaris.local"
    for name in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"):
        after.pop(name, None)
    after["UID"] = new_uid
    rule = before.get("RRULE")
    if rule is not None:
        rule.pop("COUNT", None)
        rule["UNTIL"] = [_utc(recurrence)[0] - timedelta(seconds=1) if isinstance(recurrence, datetime) else recurrence - timedelta(days=1)]
    for name in ("RDATE", "EXDATE"):
        values = _date_properties(master, name)
        before.pop(name, None)
        older = [value for value in values if _utc(value)[0] < instant]
        newer = [value for value in values if _utc(value)[0] >= instant]
        if older:
            before.add(name, older)
        if newer:
            after.add(name, newer)
    older_exceptions: list[Any] = []
    newer_exceptions: list[Any] = []
    for part in parts:
        if "RECURRENCE-ID" not in part:
            continue
        value = _decoded(part, "RECURRENCE-ID")
        if _utc(value)[0] < instant:
            older_exceptions.append(part)
        else:
            moved = copy.deepcopy(part)
            moved["UID"] = new_uid
            newer_exceptions.append(moved)
            # Preserve an explicitly edited future occurrence even when its
            # original date no longer belongs to the replacement recurrence.
            after.add("rdate", value)
    zones = calendar.walk("VTIMEZONE")
    replacement = _calendar([after, *newer_exceptions], zones)
    replacement = update_event(replacement, new_uid, data.model_copy(update={"scope": "series", "recurrence_key": None}))
    return _calendar([before, *older_exceptions], zones), replacement


def event_for_occurrence(content: bytes, recurrence_key: str, zone: str = "UTC", *, around: datetime | None = None) -> ParsedEvent:
    calendar = parse_calendar(content)
    master = next(part for part in calendar.walk("VEVENT") if "RECURRENCE-ID" not in part)
    if not any(name in master for name in ("RRULE", "RDATE")):
        parsed = _event(master, zone)
        if parsed.recurrence_key == recurrence_key:
            return parsed
    for part in calendar.walk("VEVENT"):
        if "RECURRENCE-ID" in part and temporal_key(_decoded(part, "RECURRENCE-ID"), zone) == recurrence_key:
            return _event(part, zone)
    point = around or _utc(key_value(recurrence_key, _decoded(master, "DTSTART"), zone), zone)[0]
    parsed = next((row for row in events_between(content, point - timedelta(days=1), point + timedelta(days=1), zone)
        if row.recurrence_key == recurrence_key), None)
    if parsed is None:
        raise LookupError("Calendar occurrence not found")
    return parsed


def recurrence_definition(content: bytes) -> tuple[str | None, list[datetime | date], list[datetime | date]]:
    master = next(part for part in parse_calendar(content).walk("VEVENT") if "RECURRENCE-ID" not in part)
    rule = master.get("RRULE")
    return rule.to_ical().decode() if rule is not None else None, _date_properties(master, "RDATE"), _date_properties(master, "EXDATE")
