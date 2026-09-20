"""Read-only public HTTPS transport with bounded SSRF checks."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download

from .resource_uri import ResourceUriError, parse_resource_uri
from .file_contracts import FileEntry


_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
_MAX_REDIRECTS = 5
_MAX_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PublicHttpsContent:
    """One bounded public HTTPS response after validating every redirect."""

    url: str
    content: bytes
    media_type: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class _ResolvedHttpsTarget:
    """A canonical URL and the public addresses approved for this connection."""

    url: str
    hostname: str
    host_header: str
    addresses: tuple[str, ...]


def _public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global and not parsed.is_multicast


async def _resolve_public_https(value: str) -> _ResolvedHttpsTarget:
    reference = parse_resource_uri(value)
    if reference.scheme != "https":
        raise ResourceUriError("Only public https:// resources are readable.")
    url = str(reference)
    parsed = urlsplit(url)
    hostname = parsed.hostname
    assert hostname is not None
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.getaddrinfo(
            hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ResourceUriError("The HTTPS resource hostname cannot be resolved.") from exc
    resolved = tuple(dict.fromkeys(str(entry[4][0]) for entry in addresses))
    if not resolved or not all(_public_address(address) for address in resolved):
        raise ResourceUriError(
            "The HTTPS resource resolves to a non-public network. "
            "Pass the original canonical file URI returned by the authorized provider "
            "directly to this tool. Use file_list or file_search to retrieve that URI; "
            "do not invent a URI or retry the blocked HTTPS URL."
        )
    return _ResolvedHttpsTarget(
        url=url,
        hostname=hostname,
        host_header=parsed.netloc,
        addresses=resolved,
    )


def _pinned_url(target: _ResolvedHttpsTarget, address: str) -> str:
    """Replace only the TCP destination while preserving the canonical URL path."""

    parsed = urlsplit(target.url)
    host = f"[{address}]" if ":" in address else address
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))


def _new_client() -> httpx.AsyncClient:
    # Environment proxies would resolve the hostname outside this process and undo
    # the DNS pin. A future proxy integration needs an equally strict resolution policy.
    return httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=False,
        trust_env=False,
    )


class PublicHttpsFileTransport:
    """Download public HTTPS resources after validating every redirect target."""

    async def _request(
        self,
        method: str,
        url: str,
        *,
        stream: bool,
    ) -> tuple[httpx.AsyncClient, httpx.Response, str]:
        current = url
        for _attempt in range(_MAX_REDIRECTS + 1):
            target = await _resolve_public_https(current)
            last_connect_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
            redirect: str | None = None
            for address in target.addresses:
                client = _new_client()
                request = client.build_request(
                    method,
                    _pinned_url(target, address),
                    headers={"Host": target.host_header},
                    extensions={"sni_hostname": target.hostname},
                )
                try:
                    response = await client.send(request, stream=stream)
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_connect_error = exc
                    await client.aclose()
                    continue
                except BaseException:
                    await client.aclose()
                    raise
                if response.status_code not in {301, 302, 303, 307, 308}:
                    try:
                        response.raise_for_status()
                    except BaseException:
                        await response.aclose()
                        await client.aclose()
                        raise
                    return client, response, target.url
                location = response.headers.get("location")
                await response.aclose()
                await client.aclose()
                if not location:
                    raise RuntimeError("HTTPS redirect has no location.")
                redirect = urljoin(target.url, location)
                break
            if redirect is not None:
                current = redirect
                continue
            if last_connect_error is not None:
                raise last_connect_error
            raise RuntimeError("HTTPS resource has no usable public address.")
        raise RuntimeError("HTTPS resource exceeded the redirect limit.")

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        del target
        limit = min(max_bytes, _MAX_BYTES)
        client, response, _final_url = await self._request("GET", remote, stream=True)
        total = 0
        try:
            declared = response.headers.get("content-length")
            if declared and int(declared) > limit:
                raise ValueError("HTTPS resource exceeds the maximum file size.")
            total = await copy_download(response.aiter_bytes(min(64 * 1024, limit + 1)), dest, max_bytes=limit)
        finally:
            await response.aclose()
            await client.aclose()
        return total

    async def read_bytes(
        self,
        remote: str,
        *,
        max_bytes: int,
        truncate: bool = False,
    ) -> PublicHttpsContent:
        """Read a small public HTTPS resource without relaxing the file transport SSRF policy."""

        limit = max(1, min(max_bytes, _MAX_BYTES))
        client, response, final_url = await self._request("GET", remote, stream=True)
        chunks: list[bytes] = []
        total = 0
        truncated = False
        try:
            declared = response.headers.get("content-length")
            if declared and int(declared) > limit and not truncate:
                raise ValueError("HTTPS resource exceeds the requested preview size.")
            async for chunk in response.aiter_bytes(64 * 1024):
                remaining = limit - total
                if len(chunk) > remaining:
                    if not truncate:
                        raise ValueError("HTTPS resource exceeds the requested preview size.")
                    if remaining:
                        chunks.append(chunk[:remaining])
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
        finally:
            await response.aclose()
            await client.aclose()
        return PublicHttpsContent(
            url=final_url,
            content=b"".join(chunks),
            media_type=response.headers.get(
                "content-type", "application/octet-stream"
            ).partition(";")[0].strip().lower(),
            truncated=truncated,
        )

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        del src, filename, target
        raise PermissionError("https:// resources are read-only.")

    async def resource_info(
        self, path: str, *, include_sha256: bool = False
    ) -> FileEntry:
        del include_sha256
        client, response, _final_url = await self._request("HEAD", path, stream=True)
        try:
            length = response.headers.get("content-length")
            return FileEntry(
                path=path,
                is_dir=False,
                size=int(length) if length and length.isdigit() else 0,
                modified_at=response.headers.get("last-modified", ""),
                mime_type=response.headers.get(
                    "content-type", "application/octet-stream"
                ).partition(";")[0],
                sha256="",
            )
        finally:
            await response.aclose()
            await client.aclose()


async def read_public_https_bytes(
    remote: str,
    *,
    max_bytes: int,
    truncate: bool = False,
) -> PublicHttpsContent:
    """Public facade for bounded HTTPS reads with redirect-by-redirect SSRF validation."""

    return await PublicHttpsFileTransport().read_bytes(
        remote,
        max_bytes=max_bytes,
        truncate=truncate,
    )


__all__ = ["PublicHttpsContent", "PublicHttpsFileTransport", "read_public_https_bytes"]
