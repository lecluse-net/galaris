"""CalDAV discovery, differential reads and conditional per-resource writes."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit, unquote
from posixpath import normpath
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from app.calendar.contracts import (CalendarHttpResponse, InvalidSyncTokenError, RemoteCalendar,
    RemoteChange, RemoteChanges, RemoteConflictError)
from .transport import request_calendar, validate_calendar_url

DAV = "{DAV:}"
CAL = "{urn:ietf:params:xml:ns:caldav}"


def _xml(content: bytes) -> ET.Element:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("XML entity declarations are forbidden")
    return ET.fromstring(content)


def _multistatus(content: bytes) -> ET.Element:
    root = _xml(content)
    if root.tag != DAV + "multistatus":
        raise ValueError("Expected a complete DAV multistatus response")
    return root


def _href(base: str, value: str) -> str:
    resolved = validate_calendar_url(urljoin(base, value))
    if urlsplit(base).netloc != urlsplit(resolved).netloc:
        raise ValueError("CalDAV resources must remain on their configured origin")
    return resolved


def resource_href(base: str, value: str) -> str:
    resolved = _href(base, value)
    prefix = normpath(unquote(urlsplit(base).path)).rstrip('/') + '/'
    path = normpath(unquote(urlsplit(resolved).path))
    if not path.startswith(prefix) or '/' in path[len(prefix):] or path == prefix.rstrip('/'):
        raise ValueError("CalDAV event is outside its calendar collection")
    return resolved


def _properties(response: ET.Element) -> ET.Element:
    result = ET.Element("properties")
    for propstat in response.findall(DAV + "propstat"):
        if " 200 " in (propstat.findtext(DAV + "status") or ""):
            prop = propstat.find(DAV + "prop")
            if prop is not None:
                result.extend(list(prop))
    return result


async def _dav(method: str, url: str, body: str, *, username: str | None, password: str | None,
               statuses: tuple[int, ...] = (), depth: str = "1") -> CalendarHttpResponse:
    return await request_calendar(method, url, username=username, password=password, content=body.encode(),
        extra_headers={"Content-Type": "application/xml; charset=utf-8", "Depth": depth}, accepted_statuses=statuses)


async def discover(url: str, *, username: str | None, password: str | None) -> list[RemoteCalendar]:
    body = '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:resourcetype/><d:displayname/><d:current-user-principal/><c:calendar-home-set/><d:current-user-privilege-set/></d:prop></d:propfind>'
    current = url
    visited: set[str] = set()
    for _ in range(4):
        if current in visited:
            break
        visited.add(current)
        response = await _dav("PROPFIND", current, body, username=username, password=password)
        root = _multistatus(response.content)
        calendars: list[RemoteCalendar] = []
        next_url: str | None = None
        for entry in root.findall(DAV + "response"):
            prop = _properties(entry)
            types = prop.find(DAV + "resourcetype")
            if types is not None and types.find(CAL + "calendar") is not None:
                privileges = prop.find(DAV + "current-user-privilege-set")
                writable = privileges is not None and any(privileges.find('.//' + DAV + key) is not None for key in ("all", "write"))
                calendars.append(RemoteCalendar(_href(current, entry.findtext(DAV + "href") or ""),
                    prop.findtext(DAV + "displayname") or "Calendar", writable))
            home = prop.findtext(CAL + "calendar-home-set/" + DAV + "href")
            principal = prop.findtext(DAV + "current-user-principal/" + DAV + "href")
            if home:
                next_url = _href(current, home)
            elif principal and next_url is None:
                next_url = _href(current, principal)
        if calendars:
            return calendars
        if next_url is None:
            break
        current = next_url
    raise ValueError("No readable CalDAV calendars discovered")


async def _changes_page(url: str, *, token: str | None, username: str | None, password: str | None) -> tuple[RemoteChanges, bool]:
    body = '<d:sync-collection xmlns:d="DAV:"><d:sync-token>' + escape(token or "") + '</d:sync-token><d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>'
    response = await _dav("REPORT", url, body, username=username, password=password, statuses=(403, 405, 501))
    if response.status_code == 403:
        root = _xml(response.content)
        if root.find('.//' + DAV + 'valid-sync-token') is not None:
            raise InvalidSyncTokenError("Expired CalDAV synchronization token")
        raise PermissionError("CalDAV synchronization forbidden")
    full = token is None
    if response.status_code in (405, 501):
        body = '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>'
        response = await _dav("REPORT", url, body, username=username, password=password)
        full = True
    root = _multistatus(response.content)
    result: list[RemoteChange] = []
    truncated = False
    for entry in root.findall(DAV + "response"):
        href = _href(url, entry.findtext(DAV + "href") or "")
        status = entry.findtext(DAV + "status") or ""
        if href.rstrip('/') == url.rstrip('/'):
            if " 507 " in status:
                truncated = True
            elif status and " 200 " not in status:
                raise ValueError("Incomplete CalDAV collection response")
            continue
        href = resource_href(url, href)
        if " 404 " in status:
            result.append(RemoteChange(href, None, None, True))
            continue
        if status and " 200 " not in status:
            raise ValueError("Incomplete CalDAV synchronization response")
        prop = _properties(entry)
        etag = prop.findtext(DAV + "getetag")
        data = prop.findtext(CAL + "calendar-data")
        result.append(RemoteChange(href, etag, data.encode() if data is not None else None))
    missing = [change.href for change in result if not change.deleted and change.content is None]
    fetched: dict[str, RemoteChange] = {}
    for index in range(0, len(missing), 100):
        fetched.update(await _multiget(url, missing[index:index + 100], username=username, password=password))
    result = [fetched[change.href] if not change.deleted and change.content is None else change for change in result]
    return RemoteChanges(tuple(result), root.findtext(DAV + "sync-token"), full), truncated


async def _multiget(url: str, hrefs: list[str], *, username: str | None, password: str | None) -> dict[str, RemoteChange]:
    body = '<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
    body += ''.join('<d:href>' + escape(urlsplit(href).path) + '</d:href>' for href in hrefs)
    body += '</c:calendar-multiget>'
    response = await _dav("REPORT", url, body, username=username, password=password)
    result: dict[str, RemoteChange] = {}
    for entry in _multistatus(response.content).findall(DAV + "response"):
        href = resource_href(url, entry.findtext(DAV + "href") or "")
        if href not in hrefs:
            raise ValueError("CalDAV multiget returned an unrequested resource")
        prop = _properties(entry)
        data = prop.findtext(CAL + "calendar-data")
        if data is None:
            raise ValueError("Incomplete CalDAV multiget response")
        result[href] = RemoteChange(href, prop.findtext(DAV + "getetag"), data.encode())
    if set(result) != set(hrefs):
        raise ValueError("CalDAV multiget omitted a requested resource")
    return result


async def changes(url: str, *, token: str | None, username: str | None, password: str | None) -> RemoteChanges:
    initial = token
    combined: dict[str, RemoteChange] = {}
    for _ in range(100):
        batch, truncated = await _changes_page(url, token=token, username=username, password=password)
        combined.update((change.href, change) for change in batch.changes)
        if len(combined) > 100000:
            raise ValueError("CalDAV synchronization exceeds 100000 resources")
        if not truncated:
            return RemoteChanges(tuple(combined.values()), batch.token, initial is None or batch.full)
        if not batch.token or batch.token == token:
            raise ValueError("Truncated CalDAV synchronization has no continuation token")
        token = batch.token
    raise ValueError("CalDAV synchronization exceeded its continuation limit")


async def fetch(url: str, *, username: str | None, password: str | None) -> CalendarHttpResponse | None:
    response = await request_calendar("GET", url, username=username, password=password, accepted_statuses=(404,))
    return None if response.status_code == 404 else response


def _strong_etag(value: str) -> str:
    if value.startswith('W/') or not value.startswith('"') or not value.endswith('"'):
        raise RemoteConflictError("A strong ETag is required for safe calendar writes")
    return value


async def put(url: str, content: bytes, *, etag: str | None, username: str | None, password: str | None) -> CalendarHttpResponse:
    headers = {"If-Match": _strong_etag(etag)} if etag else {"If-None-Match": "*"}
    response = await request_calendar("PUT", url, username=username, password=password, content=content,
        extra_headers=headers, accepted_statuses=(409, 412))
    if response.status_code in (409, 412):
        raise RemoteConflictError("Calendar resource changed remotely")
    return response


async def remove(url: str, *, etag: str, username: str | None, password: str | None) -> None:
    response = await request_calendar("DELETE", url, username=username, password=password,
        extra_headers={"If-Match": _strong_etag(etag)}, accepted_statuses=(404, 409, 412))
    if response.status_code in (409, 412):
        raise RemoteConflictError("Calendar resource changed remotely")
