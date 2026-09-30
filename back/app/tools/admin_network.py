"""Pinned, origin-bound HTTP transport for delegated MCP diagnostics."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import cast
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx


def origin(url: str, *, allow_query: bool = False) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("An HTTP/S URL without embedded credentials is required")
    if parsed.query and not allow_query:
        raise ValueError("MCP authentication in the URL is not allowed")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


async def resolve_destination(url: str, *, allow_private: bool) -> str:
    scheme, host, port = origin(url)
    del scheme
    addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM,
    ), timeout=5)
    if not addresses:
        raise ValueError("MCP destination has no address")
    for item in addresses:
        address = ipaddress.ip_address(str(item[4][0]))
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_unspecified or address.is_multicast or address.is_link_local or str(address) in {
            "100.100.100.200", "168.63.129.16",
        }:
            raise ValueError("MCP destination is prohibited")
        if not allow_private and not address.is_global:
            raise ValueError("A private destination requires a human-prepared candidate")
    return str(addresses[0][4][0])


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream) -> None:
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ValueError("MCP response exceeds the byte limit")
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


class PinnedMcpTransport(httpx.AsyncBaseTransport):
    def __init__(self, url: str, address: str) -> None:
        self.destination = origin(url)
        self.address = address
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Applies to every request, including an SSE server-supplied POST endpoint.
        if origin(str(request.url), allow_query=True) != self.destination:
            raise ValueError("A cross-origin MCP endpoint is prohibited")
        host = request.url.host
        request.headers["Host"] = request.url.netloc.decode()
        request.headers["Accept-Encoding"] = "identity"
        request.extensions["sni_hostname"] = host
        request.url = request.url.copy_with(host=self.address)
        response = await self.transport.handle_async_request(request)
        if response.headers.get("Content-Encoding", "identity").strip().lower() not in {"", "identity"}:
            await response.aclose()
            raise ValueError("MCP response compression is prohibited by the byte budget")
        if response.is_redirect:
            await response.aclose()
            raise ValueError("MCP redirects are prohibited")
        response.stream = _BoundedStream(cast(httpx.AsyncByteStream, response.stream))
        return response

    async def aclose(self) -> None:
        await self.transport.aclose()


async def diagnostic_client(url: str, *, allow_private: bool) -> httpx.AsyncClient:
    address = await resolve_destination(url, allow_private=allow_private)
    return httpx.AsyncClient(
        transport=PinnedMcpTransport(url, address), follow_redirects=False,
        timeout=15, trust_env=False,
    )
