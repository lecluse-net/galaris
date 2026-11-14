"""JSON/iCalendar boundary for Google Calendar and Microsoft Graph.

Dynamic provider and icalendar objects are confined to this codec. A private
provider property retains the original resource and stable UID across round trips.
"""
from __future__ import annotations

import base64
import copy
import json
import zlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

import icalendar
from babel.core import get_global

GRAPH_PROPERTY = "String {9b889a18-a508-4b2c-983a-0fe0de5a6f45} Name GalarisCalendar"
_DAYS = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU"}


def _zone(value: str) -> ZoneInfo:
    windows = get_global("windows_zone_mapping")
    return ZoneInfo(windows.get(value, value))


def _dt(value: dict[str, Any], google: bool, all_day: bool = False) -> datetime | date:
    if "date" in value:
        return date.fromisoformat(str(value["date"]))
    result = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
    if all_day:
        return result.date()
    zone = _zone(str(value.get("timeZone") or "UTC"))
    return result.replace(tzinfo=zone) if result.tzinfo is None else result.astimezone(zone) if value.get("timeZone") else result


def _rrule(data: dict[str, Any], start: datetime | date) -> dict[str, Any]:
    pattern, span = data["pattern"], data["range"]
    kind = pattern["type"]
    frequencies = {"daily": "DAILY", "weekly": "WEEKLY", "absoluteMonthly": "MONTHLY", "relativeMonthly": "MONTHLY", "absoluteYearly": "YEARLY", "relativeYearly": "YEARLY"}
    rule: dict[str, Any] = {"FREQ": frequencies[kind], "INTERVAL": pattern["interval"]}
    if pattern.get("daysOfWeek"):
        rule["BYDAY"] = [_DAYS[day] for day in pattern["daysOfWeek"]]
    if kind.startswith("relative"):
        rule["BYSETPOS"] = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}[pattern["index"]]
    if kind.startswith("absolute"):
        rule["BYMONTHDAY"] = pattern["dayOfMonth"]
    if kind.endswith("Yearly"):
        rule["BYMONTH"] = pattern["month"]
    if kind == "weekly":
        rule["WKST"] = _DAYS[pattern.get("firstDayOfWeek", "sunday")]
    if span["type"] == "numbered":
        rule["COUNT"] = span["numberOfOccurrences"]
    elif span["type"] == "endDate":
        end = date.fromisoformat(span["endDate"])
        rule["UNTIL"] = datetime.combine(end, time.max, tzinfo=start.tzinfo).astimezone(timezone.utc) if isinstance(start, datetime) else end
    return rule


def _event(data: dict[str, Any], google: bool, uid: str, base: Any = None) -> Any:
    event: Any = copy.deepcopy(base) if base is not None else icalendar.Event()
    for name in ("UID", "SUMMARY", "DESCRIPTION", "LOCATION", "DTSTART", "DTEND", "STATUS", "TRANSP", "RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"):
        event.pop(name, None)
    event.add("uid", uid)
    event.add("summary", data.get("summary" if google else "subject", ""))
    description = data.get("description", "") if google else data.get("body", {}).get("content", "")
    event.add("description", description)
    location = data.get("location", "") if google else data.get("location", {}).get("displayName", "")
    event.add("location", location)
    start = _dt(data["start"], google, bool(data.get("isAllDay")))
    event.add("dtstart", start)
    event.add("dtend", _dt(data["end"], google, bool(data.get("isAllDay"))))
    status = "CANCELLED" if data.get("status") == "cancelled" or data.get("isCancelled") else "TENTATIVE" if data.get("status") == "tentative" else "CONFIRMED"
    event.add("status", status)
    event.add("transp", "TRANSPARENT" if data.get("transparency") == "transparent" or data.get("showAs") == "free" else "OPAQUE")
    if google:
        for line in data.get("recurrence", []):
            parsed: Any = icalendar.Calendar.from_ical(("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x\r\n" + line + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode())
            item = parsed.walk("VEVENT")[0]
            for key, value in item.items():
                if key in ("RRULE", "RDATE", "EXDATE"):
                    event.add(key, value)
    elif data.get("recurrence"):
        event.add("rrule", _rrule(data["recurrence"], start))
    event.subcomponents = [item for item in event.subcomponents if item.name != "VALARM"]
    reminders = data.get("reminders", {}).get("overrides", []) if google else ([{"minutes": data.get("reminderMinutesBeforeStart", 15)}] if data.get("isReminderOn") else [])
    for reminder in reminders:
        alarm: Any = icalendar.Alarm()
        alarm.add("action", "EMAIL" if google and reminder.get("method") == "email" else "DISPLAY")
        alarm.add("description", str(data.get("summary" if google else "subject", "Reminder")))
        alarm.add("trigger", -timedelta(minutes=int(reminder["minutes"])))
        event.add_component(alarm)
    return event


def _decoded_envelope(data: dict[str, Any], google: bool) -> dict[str, Any] | None:
    if google:
        properties = data.get("extendedProperties", {}).get("private", {})
        value = "".join(str(properties[key]) for key in sorted(properties) if key.startswith("galaris_ics_") and len(key) == 15 and properties[key])
    else:
        value = next((str(prop["value"]) for prop in data.get("singleValueExtendedProperties", []) if prop.get("id") == GRAPH_PROPERTY), "")
    if not value:
        return None
    try:
        # Decompression is bounded even for a malicious provider property.
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(value, validate=True), 256 * 1024 + 1)
        if len(raw) > 256 * 1024 or not decoder.eof:
            raise ValueError("Oversized calendar extension")
        result: object = json.loads(raw)
        return cast(dict[str, Any], result) if isinstance(result, dict) else None
    except (ValueError, zlib.error, TypeError):
        return None


def projection(data: dict[str, Any], google: bool) -> dict[str, Any]:
    """Fields written by this adapter; provider-owned fields are never replaced."""
    start, end = _dt(data["start"], google, bool(data.get("isAllDay"))), _dt(data["end"], google, bool(data.get("isAllDay")))
    def temporal(value: datetime | date) -> str:
        return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value.isoformat()
    reminders: dict[str, Any] = data.get("reminders") or {}
    overrides: list[dict[str, Any]] = reminders.get("overrides") or []
    normalized_reminders = {"useDefault": bool(reminders.get("useDefault")), "overrides": sorted(
        overrides, key=lambda item: (item.get("minutes", 0), item.get("method", "")))} if google else {
        "on": bool(data.get("isReminderOn")), "minutes": data.get("reminderMinutesBeforeStart", 0) if data.get("isReminderOn") else 0}
    return {"summary": data.get("summary" if google else "subject", ""),
            "description": data.get("description", "") if google else data.get("body", {}).get("content", ""),
            "location": data.get("location", "") if google else data.get("location", {}).get("displayName", ""),
            "start": temporal(start), "end": temporal(end),
            "free": data.get("transparency") == "transparent" if google else data.get("showAs") == "free",
            "cancelled": data.get("status") == "cancelled" if google else bool(data.get("isCancelled")),
            "status": data.get("status", "confirmed") if google else "confirmed",
            "reminders": normalized_reminders,
            "recurrence": data.get("recurrence") or None}


def decode(data: dict[str, Any], google: bool, exceptions: list[dict[str, Any]] | None = None) -> bytes:
    envelope = _decoded_envelope(data, google)
    uid = str(envelope["uid"]) if envelope else str(data.get("iCalUID" if google else "iCalUId") or data["id"])
    original: Any = icalendar.Calendar.from_ical(envelope["ics"]) if envelope else None
    original_events: list[Any] = original.walk("VEVENT") if original else []
    if envelope and not data.get("recurrence") and envelope.get("projection") == projection(data, google):
        return str(envelope["ics"]).encode()
    event = _event(data, google, uid, original_events[0] if original_events else None)
    calendar: Any = icalendar.Calendar()
    calendar.add("version", "2.0")
    calendar.add("prodid", "-//Galaris Agenda//EN")
    calendar.add_component(event)
    start = event.decoded("DTSTART")
    for exception in exceptions or []:
        if google:
            recurrence = _dt(exception["originalStartTime"], True)
        else:
            recurrence = datetime.fromisoformat(str(exception["originalStart"]).replace("Z", "+00:00")).astimezone(start.tzinfo) if isinstance(start, datetime) else date.fromisoformat(str(exception["originalStart"])[:10])
        if exception.get("status") == "cancelled" or exception.get("isCancelled"):
            event.add("exdate", recurrence)
        else:
            item = _event(exception, google, uid)
            item.add("recurrence-id", recurrence)
            calendar.add_component(item)
    if not google:
        for occurrence in data.get("cancelledOccurrences", []):
            day = date.fromisoformat(str(occurrence).rsplit(".", 1)[-1])
            event.add("exdate", datetime.combine(day, start.timetz()) if isinstance(start, datetime) else day)
    return calendar.to_ical()


def encode(content: bytes, google: bool) -> dict[str, Any]:
    calendar: Any = icalendar.Calendar.from_ical(content)
    events: list[Any] = calendar.walk("VEVENT")
    if len(events) != 1 or any(key in events[0] for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
        # A series spans multiple independent API objects. Do not partially
        # publish it or lose exceptions by pretending the operation is atomic.
        raise ValueError("Recurring series must currently be edited in the provider calendar")
    event = events[0]
    start, end = event.decoded("DTSTART"), event.decoded("DTEND")
    def temporal(value: datetime | date) -> dict[str, str]:
        if not isinstance(value, datetime):
            return {"date": value.isoformat()} if google else {"dateTime": value.isoformat() + "T00:00:00", "timeZone": "UTC"}
        if value.tzinfo is None:
            raise ValueError("Native calendar APIs require an explicit event timezone")
        return {"dateTime": value.isoformat(), **({"timeZone": str(getattr(value.tzinfo, "key", "UTC"))} if google else {})} if google else {
            "dateTime": value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(), "timeZone": "UTC"}
    summary, description, location = (str(event.get(name, "")) for name in ("SUMMARY", "DESCRIPTION", "LOCATION"))
    free = str(event.get("TRANSP", "OPAQUE")) == "TRANSPARENT"
    payload: dict[str, Any] = {"start": temporal(start), "end": temporal(end)}
    reminders: list[dict[str, Any]] = []
    for alarm in event.subcomponents:
        if alarm.name != "VALARM":
            continue
        trigger = alarm.decoded("TRIGGER")
        if not isinstance(trigger, timedelta) or trigger.total_seconds() > 0 or trigger.total_seconds() % 60 or str(alarm.get("TRIGGER").params.get("RELATED", "START")) != "START":
            raise ValueError("Native calendar reminders require whole minutes before the event start")
        reminders.append({"method": "email" if google and str(alarm.get("ACTION")) == "EMAIL" else "popup", "minutes": int(-trigger.total_seconds() / 60)})
    if len(reminders) > (5 if google else 1):
        raise ValueError("Event exceeds the provider reminder limit")
    if google:
        payload.update(summary=summary, description=description, location=location, transparency="transparent" if free else "opaque",
                       status=str(event.get("STATUS", "CONFIRMED")).lower())
        payload["reminders"] = {"useDefault": False, "overrides": reminders}
    else:
        if str(event.get("STATUS", "CONFIRMED")) != "CONFIRMED":
            raise ValueError("Microsoft event cancellation must be performed in Outlook")
        payload.update(subject=summary, body={"contentType": "text", "content": description}, location={"displayName": location},
                       showAs="free" if free else "busy", isAllDay=not isinstance(start, datetime))
        payload.update(isReminderOn=bool(reminders), reminderMinutesBeforeStart=reminders[0]["minutes"] if reminders else 0)
    envelope = {"uid": str(event["UID"]), "ics": content.decode(), "projection": projection(payload, google)}
    packed = base64.b64encode(zlib.compress(json.dumps(envelope).encode())).decode()
    if google:
        if len(packed) > 20000:
            raise ValueError("Calendar event exceeds the provider extension limit")
        # PATCH merges private properties. Explicit nulls remove obsolete chunks
        # when the resource shrinks, while leaving other clients' keys intact.
        payload["extendedProperties"] = {"private": {f"galaris_ics_{index:03}": packed[index * 1000:(index + 1) * 1000] or None for index in range(20)}}
    else:
        if len(packed) > 30000:
            raise ValueError("Calendar event exceeds the provider extension limit")
        payload["singleValueExtendedProperties"] = [{"id": GRAPH_PROPERTY, "value": packed}]
    return payload
