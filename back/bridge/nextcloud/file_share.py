"""
Nextcloud file upload/download over WebDAV and sharing through the OCS API.

This client uses ``httpx`` consistently with ``bridge.nextcloud.client``
and authenticates with a Nextcloud login and password over Basic Auth.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download
from typing import Any, Optional
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx
from loguru import logger

from app.file_share import (
    FileShareBridge,
    FileShareParamInfo,
    FileEntry,
    FileListing,
    FileMutation,
)
from core.i18n import render_prompt, t

_SHARES = "/ocs/v2.php/apps/files_sharing/api/v1"
_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=None, pool=10.0)
_CHUNK = 1 << 20


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}"), **values)


def _operation_error(operation: str, status: int, detail: Any) -> str:
    return _error(
        "operation_failed",
        service="Nextcloud",
        operation=t(f"file_share.operations.{operation}"),
        status=status,
        detail=detail,
    )


class NextcloudFileClient:
    """WebDAV and OCS sharing client for a Nextcloud account."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._dav_root = f"remote.php/dav/files/{username}"

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _encode_path(path: str) -> str:
        """Encode each path segment while preserving ``/`` separators."""
        return "/".join(quote(seg) for seg in path.split("/") if seg)

    def _webdav_url(self, remote_path: str) -> str:
        root = self._encode_path(self._dav_root)
        rel = self._encode_path(remote_path)
        return f"{self.base_url}/{root}" + (f"/{rel}" if rel else "")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=(self.username, self.password),
            timeout=_TIMEOUT,
            follow_redirects=True,
        )

    async def _ensure_dirs(self, http: httpx.AsyncClient, remote_dir: str) -> None:
        """Recursively create parent collections with idempotent MKCOL calls."""
        parts = [p for p in remote_dir.split("/") if p]
        acc = ""
        for part in parts:
            acc = f"{acc}/{part}" if acc else part
            resp = await http.request("MKCOL", self._webdav_url(acc))
            # 201 means created; 405 means already present.
            if resp.status_code not in (201, 405):
                raise RuntimeError(_error(
                    "folder_creation_failed",
                    path=acc,
                    status=resp.status_code,
                    detail=resp.text[:200],
                ))

    # -- Public API -------------------------------------------------------------

    async def upload(self, data: bytes, filename: str, target: str = "") -> str:
        """Upload ``data`` as ``filename`` in the ``target`` directory.

        Return the created remote path.
        """
        folder = target.strip("/")
        remote_path = f"{folder}/{filename}" if folder else filename.strip("/")
        async with self._client() as http:
            if folder:
                await self._ensure_dirs(http, folder)
            resp = await http.put(
                self._webdav_url(remote_path),
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
        if resp.status_code not in (201, 204):
            raise RuntimeError(_operation_error(
                "webdav_upload", resp.status_code, resp.text[:200]
            ))
        logger.info("Nextcloud: uploaded file to {}", remote_path)
        return remote_path

    async def download(self, remote: str) -> bytes:
        """Download a file from a relative path or complete WebDAV URL."""
        url = remote if remote.startswith(("http://", "https://")) else self._webdav_url(remote.strip("/"))
        async with self._client() as http:
            resp = await http.get(url)
        if resp.status_code != 200:
            raise RuntimeError(_operation_error(
                "webdav_download", resp.status_code, resp.text[:200]
            ))
        return resp.content

    # -- Standard FileTransport interface (streaming with bounded memory) --------

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        """Stream a WebDAV file to local ``dest``; ``target`` is ignored."""
        url = remote if remote.startswith(("http://", "https://")) else self._webdav_url(remote.strip("/"))
        total = 0
        async with self._client() as http:
            async with http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:200]
                    raise RuntimeError(_operation_error(
                        "webdav_download", resp.status_code, repr(body)
                    ))
                total = await copy_download(resp.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)
        return total

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Stream local ``src`` into ``target`` and return the remote path."""
        folder = target.strip("/")
        remote_path = f"{folder}/{filename}" if folder else filename.strip("/")
        size = src.stat().st_size

        async def _body():
            with src.open("rb") as fh:
                while True:
                    chunk = await asyncio.to_thread(fh.read, _CHUNK)
                    if not chunk:
                        break
                    yield chunk

        async with self._client() as http:
            if folder:
                await self._ensure_dirs(http, folder)
            resp = await http.put(
                self._webdav_url(remote_path),
                content=_body(),
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)},
            )
        if resp.status_code not in (201, 204):
            raise RuntimeError(_operation_error(
                "webdav_upload", resp.status_code, resp.text[:200]
            ))
        logger.info("Nextcloud: streamed file to {} ({} bytes)", remote_path, size)
        return remote_path

    async def share(
        self,
        remote: str,
        permissions: int = 1,
        share_with: Optional[str] = None,
    ) -> str:
        """Create a Nextcloud share and return its URL.

        An empty ``share_with`` creates a public link (shareType 3); otherwise it
        creates a user share (shareType 0). Permissions: 1=read, 15=all.
        """
        endpoint = f"{self.base_url}{_SHARES}/shares"
        payload = {
            "path": f"/{remote.strip('/')}",
            "shareType": "0" if share_with else "3",
            "permissions": str(permissions),
        }
        if share_with:
            payload["shareWith"] = share_with

        async with self._client() as http:
            resp = await http.post(
                endpoint,
                data=payload,
                headers={"OCS-APIRequest": "true", "Accept": "application/json"},
            )
        if resp.status_code not in (200, 201):
            raise RuntimeError(_operation_error(
                "share_creation", resp.status_code, resp.text[:200]
            ))

        url = ""
        try:
            body = json.loads(resp.text)
            data = body.get("ocs", {}).get("data", {})
            url = data.get("url") or ""
            if not url and data.get("token"):
                url = f"{self.base_url}/s/{data['token']}"
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Nextcloud: share response is not JSON: {}", resp.text[:200])
        logger.info("Nextcloud: created share for {}", remote)
        return url

    async def _propfind(self, remote: str, *, depth: str) -> list[FileEntry]:
        """Return bounded WebDAV metadata without exposing credentials."""

        headers = {
            "Depth": depth,
            "Content-Type": "application/xml; charset=utf-8",
        }
        body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/>
<d:getlastmodified/><d:getcontenttype/><d:getetag/></d:prop></d:propfind>"""
        async with self._client() as http:
            response = await http.request(
                "PROPFIND",
                self._webdav_url(remote.strip("/")),
                headers=headers,
                content=body,
            )
        if response.status_code == 404:
            raise FileNotFoundError(remote)
        if response.status_code != 207:
            raise RuntimeError(
                _operation_error("webdav_download", response.status_code, response.text[:200])
            )
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise RuntimeError(_error("invalid_response", service="Nextcloud")) from exc
        dav_prefix = f"/{self._dav_root.strip('/')}"
        entries: list[FileEntry] = []
        for item in root.findall("{DAV:}response"):
            href = item.findtext("{DAV:}href") or ""
            decoded_path = unquote(urlsplit(href).path)
            marker = decoded_path.find(dav_prefix)
            if marker < 0:
                continue
            path = decoded_path[marker + len(dav_prefix) :].strip("/")
            prop = item.find("{DAV:}propstat/{DAV:}prop")
            if prop is None:
                continue
            resource_type = prop.find("{DAV:}resourcetype")
            is_dir = (
                resource_type is not None
                and resource_type.find("{DAV:}collection") is not None
            )
            size_text = prop.findtext("{DAV:}getcontentlength") or "0"
            mime_type = prop.findtext("{DAV:}getcontenttype") or (
                mimetypes.guess_type(path)[0] or "application/octet-stream"
            )
            entries.append(
                FileEntry(
                    path=path or ".",
                    is_dir=is_dir,
                    size=0 if is_dir else int(size_text or 0),
                    modified_at=prop.findtext("{DAV:}getlastmodified") or "",
                    mime_type=mime_type,
                    sha256="",
                )
            )
        return entries

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        """Return WebDAV metadata for one resource."""

        del include_sha256
        entries = await self._propfind(path, depth="0")
        if not entries:
            raise FileNotFoundError(path)
        return entries[0]

    async def resource_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing:
        """List one WebDAV collection, using a server-bounded result slice."""

        entries = await self._propfind(path, depth="infinity" if recursive else "1")
        normalized = path.strip("/") or "."
        children = [entry for entry in entries if entry.path != normalized]
        return FileListing(
            path=normalized,
            entries=tuple(children[:limit]),
            truncated=len(children) > limit,
        )

    async def resource_delete(self, path: str) -> FileMutation:
        """Delete one WebDAV file or empty collection."""

        info = await self.resource_info(path)
        async with self._client() as http:
            response = await http.request("DELETE", self._webdav_url(path.strip("/")))
        if response.status_code not in {200, 204}:
            raise RuntimeError(
                _operation_error("webdav_upload", response.status_code, response.text[:200])
            )
        return FileMutation(path=path.strip("/"), size=info.size or 0, state="deleted")

    async def _resource_relocate(
        self,
        method: str,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        folder = destination.strip("/").rpartition("/")[0]
        async with self._client() as http:
            if folder:
                await self._ensure_dirs(http, folder)
            response = await http.request(
                method,
                self._webdav_url(source.strip("/")),
                headers={
                    "Destination": self._webdav_url(destination.strip("/")),
                    "Overwrite": "T" if overwrite else "F",
                },
            )
        if response.status_code not in {201, 204}:
            if response.status_code == 412:
                raise FileExistsError(destination)
            raise RuntimeError(
                _operation_error("webdav_upload", response.status_code, response.text[:200])
            )
        info = await self.resource_info(destination)
        return FileMutation(
            path=destination.strip("/"),
            source=source.strip("/"),
            size=info.size or 0,
            state="moved" if method == "MOVE" else "copied",
        )

    async def resource_copy(
        self,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        return await self._resource_relocate(
            "COPY", source, destination, overwrite=overwrite
        )

    async def resource_move(
        self,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        return await self._resource_relocate(
            "MOVE", source, destination, overwrite=overwrite
        )


def build_file_transport(
    base_url: str,
    params: dict[str, str],
) -> NextcloudFileClient:
    """Build the Nextcloud file facade from resolved connection parameters."""
    return NextcloudFileClient(
        base_url=base_url,
        username=params["login"],
        password=params["password"],
    )


NEXTCLOUD_FILE_SHARE_BRIDGE = FileShareBridge(
    service="nextcloud",
    label="Nextcloud (WebDAV + sharing)",
    supports_share=True,
    params=(
        FileShareParamInfo(key="login", label="Login", type="string"),
        FileShareParamInfo(
            key="password",
            label="Password",
            type="password",
        ),
    ),
    build=build_file_transport,
)
