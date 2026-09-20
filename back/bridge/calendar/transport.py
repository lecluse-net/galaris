"""Bounded HTTPS transport for complete iCalendar resources."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.file_share import ResourceUriError, parse_resource_uri


_MAX_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 5
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


@dataclass(frozen=True, slots=True)
class CalendarHttpResponse:
    content: bytes
    final_url: str
    headers: dict[str, str]


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
        raise ValueError("Calendar URLs must use public HTTPS")
    return str(reference)


def _is_public(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global and not parsed.is_multicast


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
    if not addresses or not all(_is_public(address) for address in addresses):
        raise ResourceUriError("The calendar URL resolves to a non-public network")
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


async def _request(
    method: str,
    url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    content: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> CalendarHttpResponse:
    current = url
    original_origin = urlsplit(validate_calendar_url(url)).netloc
    for _attempt in range(_MAX_REDIRECTS + 1):
        target = await _resolve(current)
        request_headers = {
            "Host": target.host_header,
            "Accept": "text/calendar, application/ics;q=0.9, */*;q=0.1",
            "User-Agent": "Galaris-Calendar/1",
        }
        authorization = _authorization(username, password)
        if authorization and urlsplit(target.url).netloc == original_origin:
            request_headers["Authorization"] = authorization
        if content is not None:
            request_headers["Content-Type"] = "text/calendar; charset=utf-8"
        if extra_headers:
            request_headers.update(extra_headers)

        last_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
        redirect: str | None = None
        for address in target.addresses:
            client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, trust_env=False)
            request = client.build_request(
                method,
                _pinned_url(target, address),
                headers=request_headers,
                content=content,
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
                if response.status_code in {301, 302, 303, 307, 308}:
                    if method not in {"GET", "HEAD", "OPTIONS"}:
                        raise ValueError("Calendar writes cannot follow redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Calendar redirect has no location")
                    redirect = urljoin(target.url, location)
                    break
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared and int(declared) > _MAX_BYTES:
                    raise ValueError("Calendar resource exceeds 5 MiB")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        raise ValueError("Calendar resource exceeds 5 MiB")
                    chunks.append(chunk)
                return CalendarHttpResponse(
                    content=b"".join(chunks),
                    final_url=target.url,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
            finally:
                await response.aclose()
                await client.aclose()
        if redirect is not None:
            current = redirect
            continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("Calendar resource has no usable public address")
    raise RuntimeError("Calendar resource exceeded the redirect limit")


async def read_calendar(
    url: str, *, username: str | None = None, password: str | None = None
) -> CalendarHttpResponse:
    return await _request("GET", url, username=username, password=password)


async def inspect_calendar(
    url: str, *, username: str | None = None, password: str | None = None
) -> CalendarHttpResponse:
    return await _request("OPTIONS", url, username=username, password=password)


async def write_calendar(
    url: str,
    content: bytes,
    *,
    username: str | None = None,
    password: str | None = None,
    etag: str | None = None,
) -> None:
    await _request(
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
