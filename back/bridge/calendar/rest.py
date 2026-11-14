"""Bounded Google Calendar / Microsoft Graph adapters for canonical resources."""
from __future__ import annotations

import json
import re
from typing import Any, cast
from urllib.parse import quote, urlencode, urlsplit

from app.calendar.contracts import CalendarHttpResponse, RemoteCalendar, RemoteChange, RemoteChanges, RemoteConflictError, report_calendar_sync
from .rest_codec import GRAPH_PROPERTY, decode, encode, projection
from .transport import request_calendar

GOOGLE_ROOT = "https://www.googleapis.com/calendar/v3/"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0/me/"
LOCAL_PROPERTY = "String {9b889a18-a508-4b2c-983a-0fe0de5a6f45} Name GalarisLocalKey"
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_GRAPH_SELECT = "id,iCalUId,subject,body,location,start,end,isAllDay,isCancelled,showAs,isReminderOn,reminderMinutesBeforeStart,type,recurrence,originalStart,cancelledOccurrences,singleValueExtendedProperties"


class RestCalendarProvider:
    def __init__(self, kind: str, bearer: str) -> None:
        self.google = kind == "google"
        self.root = GOOGLE_ROOT if self.google else GRAPH_ROOT
        self.bearer = bearer

    def _validate(self, url: str) -> str:
        parsed, expected = urlsplit(url), urlsplit(self.root)
        if parsed.netloc != expected.netloc or parsed.scheme != "https" or parsed.fragment or not parsed.path.startswith(expected.path):
            raise ValueError("Calendar API resource escaped its configured provider")
        return url

    async def _request(self, method: str, url: str, *, payload: dict[str, Any] | None = None,
                       etag: str | None = None) -> CalendarHttpResponse:
        self._validate(url)
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json", "Content-Type": "application/json"}
        if not self.google:
            headers["Prefer"] = 'IdType="ImmutableId", outlook.body-content-type="text"'
        if etag:
            headers["If-Match"] = etag
        response = await request_calendar(method, url, content=json.dumps(payload).encode() if payload is not None else None,
                                          extra_headers=headers, accepted_statuses=(404, 409, 410, 412), allow_redirects=False)
        if response.status_code in (409, 412):
            raise RemoteConflictError("Calendar resource changed remotely")
        if response.status_code in (301, 302, 303, 307, 308):
            raise ValueError("Calendar API cannot redirect")
        return response

    async def _pages(self, url: str) -> list[dict[str, Any]]:
        origin = urlsplit(url)
        values: list[dict[str, Any]] = []
        received = 0
        seen: set[str] = set()
        for _ in range(1000):
            if url in seen:
                raise ValueError("Calendar API repeated a continuation page")
            seen.add(url)
            response = await self._request("GET", url)
            received += len(response.content)
            if received > _MAX_SNAPSHOT_BYTES:
                raise ValueError("Calendar API snapshot exceeds 64 MiB")
            if response.status_code != 200:
                raise ValueError("Calendar API collection is unavailable")
            data: dict[str, Any] = json.loads(response.content)
            items = data.get("items" if self.google else "value")
            if not isinstance(items, list):
                raise ValueError("Incomplete calendar API collection")
            typed = cast(list[object], items)
            if any(not isinstance(item, dict) for item in typed):
                raise ValueError("Incomplete calendar API collection")
            values.extend(cast(list[dict[str, Any]], typed))
            if len(values) > 100000:
                raise ValueError("Calendar API exceeds 100000 resources")
            if self.google:
                continuation = data.get("nextPageToken")
                if not continuation:
                    return values
                from urllib.parse import parse_qsl, urlunsplit
                query = dict(parse_qsl(origin.query))
                query["pageToken"] = str(continuation)
                url = urlunsplit((origin.scheme, origin.netloc, origin.path, urlencode(query), ""))
            else:
                continuation = data.get("@odata.nextLink")
                if not continuation:
                    return values
                url = self._validate(str(continuation))
                if urlsplit(url).path != origin.path:
                    raise ValueError("Calendar continuation changed collection")
        raise ValueError("Calendar API exceeded its continuation limit")

    async def discover(self, url: str, *, username: str | None, password: str | None) -> list[RemoteCalendar]:
        self._validate(url)
        # An individual feed still validates its current permissions against the
        # account list; it must never become writable from a stale local flag.
        collection = GOOGLE_ROOT + "users/me/calendarList" if self.google else GRAPH_ROOT + "calendars"
        items = await self._pages(collection)
        calendars: list[RemoteCalendar] = []
        for item in items:
            identity = quote(str(item["id"]), safe="")
            if self.google:
                if item.get("accessRole") == "freeBusyReader" or item.get("deleted"):
                    continue
                href = GOOGLE_ROOT + "calendars/" + identity + "/events"
                calendars.append(RemoteCalendar(href, str(item.get("summary") or "Google Calendar"), item.get("accessRole") in ("owner", "writer")))
            else:
                href = GRAPH_ROOT + "calendars/" + identity + "/events"
                calendars.append(RemoteCalendar(href, str(item.get("name") or "Outlook"), item.get("canEdit") is True))
        await report_calendar_sync("discover", len(calendars), len(calendars))
        if not calendars:
            raise ValueError("No readable calendars discovered")
        return calendars

    def _graph_query(self) -> str:
        return "?" + urlencode({"$select": _GRAPH_SELECT, "$expand": f"singleValueExtendedProperties($filter=id eq '{GRAPH_PROPERTY}')"})

    async def _graph_master(self, url: str) -> dict[str, Any]:
        query = {"$select": _GRAPH_SELECT, "$expand": f"exceptionOccurrences,singleValueExtendedProperties($filter=id eq '{GRAPH_PROPERTY}')"}
        response = await self._request("GET", url + "?" + urlencode(query))
        if response.status_code != 200:
            raise ValueError("Incomplete Microsoft recurring series")
        data: dict[str, Any] = json.loads(response.content)
        if "cancelledOccurrences" not in data or "exceptionOccurrences" not in data:
            raise ValueError("Microsoft recurring series omitted its exceptions")
        if data.get("exceptionOccurrences@odata.nextLink"):
            raise ValueError("Microsoft recurring series exceptions are truncated")
        return data

    async def changes(self, url: str, *, token: str | None, username: str | None, password: str | None) -> RemoteChanges:
        # Snapshots are intentionally unbounded in time: a calendarView window
        # cannot be interpreted as a full calendar without deleting older events.
        query = "?" + urlencode({"maxResults": 2500, "singleEvents": "false", "showDeleted": "true"}) if self.google else self._graph_query() + "&$top=1000"
        items = await self._pages(url + query)
        changes: list[RemoteChange] = []
        received = 0
        exceptions: dict[str, list[dict[str, Any]]] = {}
        if self.google:
            for item in items:
                if item.get("recurringEventId"):
                    exceptions.setdefault(str(item["recurringEventId"]), []).append(item)
        for item in items:
            if self.google and (item.get("recurringEventId") or item.get("status") == "cancelled"):
                continue
            href = url.rstrip('/') + '/' + quote(str(item["id"]), safe="")
            if not self.google and item.get("type") == "seriesMaster":
                item = await self._graph_master(href)
            related = exceptions.get(str(item["id"]), []) if self.google else item.get("exceptionOccurrences", [])
            content = decode(item, self.google, related)
            received += len(content)
            if received > _MAX_SNAPSHOT_BYTES:
                raise ValueError("Decoded calendar snapshot exceeds 64 MiB")
            etag = str(item.get("etag" if self.google else "@odata.etag") or "")
            if not etag:
                raise ValueError("Calendar API omitted an event ETag")
            changes.append(RemoteChange(href, etag, content))
            await report_calendar_sync("download", len(changes), None)
        await report_calendar_sync("download", len(changes), len(changes))
        return RemoteChanges(tuple(changes), None, True)

    async def _resolve_local(self, url: str) -> tuple[str | None, str | None]:
        self._validate(url)
        base, key = url.rsplit('/', 1)
        if not re.fullmatch(r"[a-f0-9-]{36}\.ics", key):
            return url, None
        identity = key[:-4].replace('-', '')
        if self.google:
            return base + '/' + identity, identity
        query = {"$filter": f"singleValueExtendedProperties/Any(ep: ep/id eq '{LOCAL_PROPERTY}' and ep/value eq '{identity}')", "$select": "id"}
        items = await self._pages(base + '?' + urlencode(query))
        if len(items) > 1:
            raise RemoteConflictError("Duplicate remote transaction identity")
        return (base + '/' + quote(str(items[0]["id"]), safe="") if items else None), identity

    async def fetch(self, url: str, *, username: str | None, password: str | None) -> CalendarHttpResponse | None:
        resolved, _ = await self._resolve_local(url)
        if resolved is None:
            return None
        response = await self._request("GET", resolved + ("" if self.google else self._graph_query()))
        if response.status_code in (404, 410):
            return None
        data: dict[str, Any] = json.loads(response.content)
        if self.google and data.get("status") == "cancelled":
            return None
        if not self.google and data.get("type") == "seriesMaster":
            data = await self._graph_master(resolved)
        if self.google and data.get("recurrence"):
            # Include every exception, including cancellations, without expanding
            # an infinite recurrence into a bounded and misleading snapshot.
            base = resolved.rsplit('/', 1)[0]
            uid = str(data["iCalUID"])
            related = await self._pages(base + '?' + urlencode({"iCalUID": uid, "showDeleted": "true", "singleEvents": "false", "maxResults": 2500}))
            exceptions = [item for item in related if item.get("recurringEventId") == data["id"]]
        else:
            exceptions = data.get("exceptionOccurrences", [])
        etag = str(data.get("etag" if self.google else "@odata.etag") or "")
        if not etag:
            raise ValueError("Calendar API omitted an event ETag")
        return CalendarHttpResponse(decode(data, self.google, exceptions), resolved, {"etag": etag})

    async def put(self, url: str, content: bytes, *, etag: str | None, username: str | None, password: str | None) -> CalendarHttpResponse:
        payload = encode(content, self.google)  # Validate before the first write.
        resolved, identity = await self._resolve_local(url)
        if etag is None:
            if identity is None:
                raise RemoteConflictError("A remote update requires an ETag")
            if not self.google and resolved is not None:
                raise RemoteConflictError("A prior creation must be reconciled")
            if self.google:
                payload["id"] = identity
            else:
                payload["transactionId"] = identity
                payload["singleValueExtendedProperties"].append({"id": LOCAL_PROPERTY, "value": identity})
            response = await self._request("POST", url.rsplit('/', 1)[0], payload=payload)
        else:
            if resolved is None:
                raise RemoteConflictError("Remote event disappeared")
            current = await self._request("GET", resolved)
            if current.status_code in (404, 410):
                raise RemoteConflictError("Remote event disappeared")
            current_data: dict[str, Any] = json.loads(current.content)
            if current_data.get("etag" if self.google else "@odata.etag") != etag:
                raise RemoteConflictError("Remote event changed")
            if current_data.get("recurrence"):
                raise ValueError("Recurring series must currently be edited in the provider calendar")
            before, after = projection(current_data, self.google), projection(payload, self.google)
            before["reminders"] = projection(encode(decode(current_data, self.google), self.google), self.google)["reminders"]
            fields = {"summary": ("summary",) if self.google else ("subject",),
                "description": ("description",) if self.google else ("body",), "location": ("location",),
                "start": ("start",), "end": ("end",), "free": ("transparency",) if self.google else ("showAs",),
                "status": ("status",) if self.google else (), "reminders": ("reminders",) if self.google else ("isReminderOn", "reminderMinutesBeforeStart")}
            for name, keys in fields.items():
                if before[name] == after[name]:
                    for key in keys:
                        payload.pop(key, None)
            # Keep provider-owned rich HTML when only title/time/location changed.
            # Conditional PATCH still fences any change after this comparison.
            response = await self._request("PATCH", resolved, payload=payload, etag=etag)
        if response.status_code in (404, 410):
            raise RemoteConflictError("Remote event disappeared")
        data: dict[str, Any] = json.loads(response.content)
        final_url = url.rsplit('/', 1)[0] + '/' + quote(str(data["id"]), safe="")
        return CalendarHttpResponse(b"", final_url, response.headers, response.status_code)

    async def remove(self, url: str, *, etag: str, username: str | None, password: str | None) -> None:
        resolved, _ = await self._resolve_local(url)
        if resolved is not None:
            await self._request("DELETE", resolved, etag=etag)
