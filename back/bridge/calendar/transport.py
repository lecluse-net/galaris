"""Bounded HTTPS transport for complete iCalendar resources."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import socket
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from collections.abc import AsyncIterator, Generator
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.file_share import ResourceUriError, parse_resource_uri
from app.calendar import CalendarHttpResponse
from app.calendar.contracts import report_calendar_sync


_MAX_BYTES = 64 * 1024 * 1024
_MAX_REDIRECTS = 5
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))
_bearer: ContextVar[str | None] = ContextVar("calendar_bearer", default=None)
_icloud: ContextVar[bool] = ContextVar("calendar_icloud", default=False)


@contextmanager
def calendar_authorization(bearer: str | None, icloud: bool = False) -> Generator[None]:
    token, apple = _bearer.set(bearer), _icloud.set(icloud)
    try:
        yield
    finally:
        _bearer.reset(token)
        _icloud.reset(apple)


def same_calendar_origin(base: str, target: str) -> bool:
    first, second = urlsplit(base), urlsplit(target)
    if first.scheme != "https" or second.scheme != "https":
        return False
    if first.netloc == second.netloc:
        return True
    return _icloud.get() and all(parsed.port in (None, 443) and bool(re.fullmatch(
        r"(?:p\d+-)?caldav\.icloud\.com", parsed.hostname or "")) for parsed in (first, second))


@dataclass(frozen=True, slots=True)
class _Target:
    url: str
    hostname: str
    host_header: str
    addresses: tuple[str, ...]


def validate_calendar_url(value: str) -> str:
    """Return a canonical credential-free HTTPS URL."""

    reference = parse_resource_uri(value.strip())
    if reference.scheme != "https":
        raise ValueError("Calendar URLs must use HTTPS")
    return str(reference)


def _is_allowed_address(address: str) -> bool:
    """Allow public and enterprise networks, excluding special-purpose endpoints."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return (parsed.is_global and not parsed.is_multicast) or any(
        parsed in network for network in _PRIVATE_NETWORKS
    )


async def _resolve(value: str) -> _Target:
    url = validate_calendar_url(value)
    parsed = urlsplit(url)
    hostname = parsed.hostname
    assert hostname is not None
    try:
        entries = await asyncio.get_running_loop().getaddrinfo(
            hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise ResourceUriError("The calendar hostname cannot be resolved") from exc
    addresses = tuple(dict.fromkeys(str(entry[4][0]) for entry in entries))
    if not addresses or not all(_is_allowed_address(address) for address in addresses):
        raise ResourceUriError("The calendar URL resolves to an unsupported network address")
    return _Target(url, hostname, parsed.netloc, addresses)


def _pinned_url(target: _Target, address: str) -> str:
    parsed = urlsplit(target.url)
    host = f"[{address}]" if ":" in address else address
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))


def _authorization(username: str | None, password: str | None) -> str | None:
    if not username:
        return None
    token = base64.b64encode(f"{username}:{password or ''}".encode()).decode("ascii")
    return f"Basic {token}"


async def _upload_chunks(content: bytes) -> AsyncIterator[bytes]:
    await report_calendar_sync("transmitting", 0, len(content))
    for offset in range(0, len(content), 64 * 1024):
        chunk = content[offset:offset + 64 * 1024]
        yield chunk
        await report_calendar_sync("transmitting", offset + len(chunk), len(content))


async def request_calendar(
    method: str,
    url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    content: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
    accepted_statuses: tuple[int, ...] = (),
    allow_redirects: bool = True,
) -> CalendarHttpResponse:
    current = url
    validate_calendar_url(url)
    for _attempt in range(_MAX_REDIRECTS + 1):
        await report_calendar_sync("resolving")
        target = await _resolve(current)
        request_headers = {
            "Host": target.host_header,
            "Accept": "text/calendar, application/ics;q=0.9, */*;q=0.1",
            "User-Agent": "Galaris-Calendar/1",
        }
        authorization = f"Bearer {_bearer.get()}" if _bearer.get() else _authorization(username, password)
        if authorization and same_calendar_origin(url, target.url):
            request_headers["Authorization"] = authorization
        if content is not None:
            request_headers["Content-Type"] = "text/calendar; charset=utf-8"
        if extra_headers:
            request_headers.update(extra_headers)
            if not same_calendar_origin(url, target.url):
                request_headers.pop("Authorization", None)
        if method == "PUT" and content is not None:
            request_headers["Content-Length"] = str(len(content))

        last_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
        redirect: str | None = None
        for address in target.addresses:
            await report_calendar_sync("connecting")
            client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, trust_env=False)
            request = client.build_request(
                method,
                _pinned_url(target, address),
                headers=request_headers,
                content=_upload_chunks(content) if method == "PUT" and content is not None else content,
                extensions={"sni_hostname": target.hostname},
            )
            try:
                response = await client.send(request, stream=True)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_error = exc
                await client.aclose()
                continue
            except BaseException:
                await client.aclose()
                raise
            try:
                await report_calendar_sync("server_reached", http_status=response.status_code)
                if response.status_code in {301, 302, 303, 307, 308}:
                    if not allow_redirects:
                        raise ValueError("Calendar API cannot redirect")
                    if method not in {"GET", "HEAD", "OPTIONS", "PROPFIND", "REPORT"}:
                        raise ValueError("Calendar writes cannot follow redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Calendar redirect has no location")
                    redirect = urljoin(target.url, location)
                    if method in {"PROPFIND", "REPORT"} and not same_calendar_origin(url, redirect):
                        raise ValueError("CalDAV discovery cannot redirect to another origin")
                    break
                if response.status_code not in accepted_statuses:
                    response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared and int(declared) > _MAX_BYTES:
                    raise ValueError("Calendar resource exceeds 64 MiB")
                chunks: list[bytes] = []
                size = 0
                total = int(declared) if declared and not response.headers.get("content-encoding") else None
                await report_calendar_sync("receiving", 0, total)
                async for chunk in response.aiter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        raise ValueError("Calendar resource exceeds 64 MiB")
                    chunks.append(chunk)
                    await report_calendar_sync("receiving", size, total)
                await report_calendar_sync("receiving", size, size)
                return CalendarHttpResponse(
                    content=b"".join(chunks),
                    final_url=target.url,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    status_code=response.status_code,
                )
            finally:
                await response.aclose()
                await client.aclose()
        if redirect is not None:
            current = redirect
            continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("Calendar resource has no usable network address")
    raise RuntimeError("Calendar resource exceeded the redirect limit")


async def read_calendar(
    url: str, *, username: str | None = None, password: str | None = None, etag: str | None = None
) -> CalendarHttpResponse:
    return await request_calendar("GET", url, username=username, password=password,
                          extra_headers={"If-None-Match": etag} if etag else None, accepted_statuses=(304,))


async def inspect_calendar(
    url: str, *, username: str | None = None, password: str | None = None
) -> CalendarHttpResponse:
    return await request_calendar("OPTIONS", url, username=username, password=password)


async def write_calendar(
    url: str,
    content: bytes,
    *,
    username: str | None = None,
    password: str | None = None,
    etag: str | None = None,
) -> None:
    await request_calendar(
        "PUT",
        url,
        username=username,
        password=password,
        content=content,
        extra_headers={"If-Match": etag} if etag else None,
    )


__all__ = [
    "CalendarHttpResponse",
    "inspect_calendar",
    "read_calendar",
    "validate_calendar_url",
    "write_calendar",
]
