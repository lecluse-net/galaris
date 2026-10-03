"""
Nextcloud file upload/download over WebDAV and sharing through the OCS API.

This client uses ``httpx`` consistently with ``bridge.nextcloud.client``
and authenticates with a Nextcloud login and password over Basic Auth.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from core.util import DEFAULT_DOWNLOAD_BYTES, complete_io, copy_download
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from loguru import logger

from app.file_share import (
    FileShareBridge,
    FileShareParamInfo,
    FileEntry,
    FileListing,
    FileMutation,
    ResourceRevisionConflict,
    ResourceValidationError,
)
from core.i18n import render_prompt, t

_SHARES = "/ocs/v2.php/apps/files_sharing/api/v1"
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
_CHUNK = 1 << 20
_METADATA_LIMIT = 8 * 1024 * 1024
_REQUEST_SECONDS = 300


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)
    offset: int = Field(default=0, ge=0)
    fingerprint: str = ""


class _Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    frames: list[_Frame] = Field(max_length=64)


class _ShareData(BaseModel):
    url: str | None = None
    token: str | None = None
    file_source: int | None = Field(default=None, gt=0)


class _ShareMeta(BaseModel):
    status: Literal["ok"]
    statuscode: Literal[100, 200]


class _ShareResult(BaseModel):
    meta: _ShareMeta
    data: _ShareData


class _ShareEnvelope(BaseModel):
    ocs: _ShareResult


def _strong_etag(value: str | None) -> str:
    if (
        not value
        or not value.startswith('"')
        or not value.endswith('"')
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ResourceValidationError(
            "Nextcloud did not provide a strong ETag; reload before modifying the file."
        )
    return value


def _check_status(response: httpx.Response, allowed: set[int], path: str) -> None:
    status = response.status_code
    if status in allowed:
        return
    if status == 404:
        raise FileNotFoundError(path)
    if status in {401, 403}:
        raise PermissionError(f"Nextcloud denied the file operation (HTTP {status}).")
    if status == 412:
        raise ResourceRevisionConflict("The Nextcloud file changed; read it again before retrying.")
    # Do not echo remote bodies, credentials or signed URLs into tool errors.
    raise RuntimeError(f"Nextcloud file operation failed (HTTP {status}).")


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}"), **values)


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
        if any(part in {".", ".."} for part in remote_path.split("/")) or any(
            ord(c) < 32 for c in remote_path
        ):
            raise ValueError("Invalid Nextcloud path")
        root = self._encode_path(self._dav_root)
        rel = self._encode_path(remote_path)
        return f"{self.base_url}/{root}" + (f"/{rel}" if rel else "")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=(self.username, self.password),
            timeout=_TIMEOUT,
            follow_redirects=False,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: str | None = None,
        data: dict[str, str] | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        """Bound both the time and bytes of DAV control responses."""
        if http is None:
            async with self._client() as client:
                return await self._request(method, url, headers=headers, content=content, data=data, http=client)
        async with asyncio.timeout(_REQUEST_SECONDS):
            async with http.stream(
                method, url, headers=headers, content=content, data=data
            ) as response:
                received = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(received) + len(chunk) > _METADATA_LIMIT:
                        raise ResourceValidationError(
                            "Nextcloud metadata exceeds the bounded response limit; use a smaller folder."
                        )
                    received.extend(chunk)
                # aiter_bytes() has already decompressed the wire response.
                # Reconstructing it with Content-Encoding would decode it twice.
                decoded_headers = response.headers.copy()
                decoded_headers.pop("content-encoding", None)
                decoded_headers.pop("content-length", None)
                return httpx.Response(
                    response.status_code, headers=decoded_headers, content=bytes(received)
                )

    async def _ensure_dirs(self, http: httpx.AsyncClient, remote_dir: str) -> None:
        """Recursively create parent collections with idempotent MKCOL calls."""
        parts = [p for p in remote_dir.split("/") if p]
        acc = ""
        for part in parts:
            acc = f"{acc}/{part}" if acc else part
            async with http.stream("MKCOL", self._webdav_url(acc)) as resp:
                status = resp.status_code
            # 201 means created; 405 means already present.
            if status == 405:
                if not (await self.resource_info(acc)).is_dir:
                    raise NotADirectoryError(acc)
            else:
                _check_status(resp, {201}, acc)

    # -- Public API -------------------------------------------------------------

    async def upload(self, data: bytes, filename: str, target: str = "") -> str:
        """Upload ``data`` as ``filename`` in the ``target`` directory.

        Return the created remote path.
        """
        with tempfile.TemporaryDirectory(prefix="galaris_nextcloud_upload_") as folder:
            temporary = Path(folder) / "content"
            await complete_io(temporary.write_bytes, data)
            return await self.upload_from(temporary, filename, target=target)

    async def download(self, remote: str) -> bytes:
        """Download a file from a relative path or complete WebDAV URL."""
        with tempfile.TemporaryDirectory(prefix="galaris_nextcloud_download_") as folder:
            temporary = Path(folder) / "content"
            await self.download_to(remote, temporary)
            return await complete_io(temporary.read_bytes)

    # -- Standard FileTransport interface (streaming with bounded memory) --------

    async def download_to(
        self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES
    ) -> int:
        """Stream a WebDAV file to local ``dest``; ``target`` is ignored."""
        del target
        return (await self.download_versioned(remote, dest, max_bytes=max_bytes)).size or 0

    async def download_versioned(
        self, remote: str, dest: Path, *, max_bytes: int = DEFAULT_DOWNLOAD_BYTES
    ) -> FileEntry:
        if remote.startswith(("http://", "https://")):
            # File tools use account-relative paths. Never forward Basic Auth to
            # an arbitrary URL, even when called through a legacy consumer.
            root = self._webdav_url("").rstrip("/") + "/"
            if not remote.startswith(root):
                raise ValueError("Download URL is outside the configured Nextcloud account")
            remote = unquote(urlsplit(remote).path[len(urlsplit(root).path) :])
        try:
            async with asyncio.timeout(_REQUEST_SECONDS), self._client() as http:
                async with http.stream("GET", self._webdav_url(remote)) as resp:
                    _check_status(resp, {200}, remote)
                    size = await copy_download(
                        resp.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes
                    )
                    return FileEntry(
                        path=remote,
                        is_dir=False,
                        size=size,
                        mime_type=resp.headers.get(
                            "content-type", "application/octet-stream"
                        ).split(";")[0],
                        etag=resp.headers.get("etag"),
                    )
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Stream local ``src`` into ``target`` and return the remote path."""
        return await self.upload_conditional(src, filename, target=target, overwrite=True)

    async def upload_conditional(
        self,
        src: Path,
        filename: str,
        *,
        target: str = "",
        overwrite: bool,
        expected_etag: str | None = None,
    ) -> str:
        folder = target.strip("/")
        remote_path = f"{folder}/{filename}" if folder else filename.strip("/")
        size = src.stat().st_size

        if overwrite and expected_etag is None:
            try:
                current = await self.resource_info(remote_path)
            except FileNotFoundError:
                overwrite = False
            else:
                if current.is_dir:
                    raise IsADirectoryError(remote_path)
                expected_etag = _strong_etag(current.etag)
        headers = {"Content-Type": "application/octet-stream", "Content-Length": str(size)}
        if overwrite:
            headers["If-Match"] = _strong_etag(expected_etag)
        else:
            headers["If-None-Match"] = "*"

        async def _body() -> AsyncIterator[bytes]:
            with src.open("rb") as fh:
                while True:
                    chunk = await complete_io(fh.read, _CHUNK)
                    if not chunk:
                        break
                    yield chunk

        async with asyncio.timeout(_REQUEST_SECONDS), self._client() as http:
            if folder:
                await self._ensure_dirs(http, folder)
            async with http.stream(
                "PUT",
                self._webdav_url(remote_path),
                content=_body(),
                headers=headers,
            ) as resp:
                if resp.status_code == 412 and not overwrite:
                    raise FileExistsError(remote_path)
                _check_status(resp, {201, 204}, remote_path)
        logger.info("Nextcloud: streamed file to {} ({} bytes)", remote_path, size)
        return remote_path

    async def share(
        self,
        remote: str,
        permissions: int = 1,
        share_with: str | None = None,
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

        resp = await self._request(
            "POST",
            endpoint,
            data=payload,
            headers={"OCS-APIRequest": "true", "Accept": "application/json"},
        )
        _check_status(resp, {200, 201}, remote)
        try:
            data = _ShareEnvelope.model_validate_json(resp.content).ocs.data
            url = data.url
            if not url and not share_with and data.token:
                url = f"{self.base_url}/s/{quote(data.token, safe='')}"
            if not url and share_with and data.file_source is not None:
                url = f"{self.base_url}/index.php/f/{data.file_source}"
            if not isinstance(url, str):
                raise ValueError("Missing share link")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Invalid share link")
        except ValueError, KeyError, TypeError, AttributeError:
            raise RuntimeError(
                "Nextcloud returned no confirmed usable share; verify its state before retrying."
            ) from None
        logger.info("Nextcloud: created share for {}", remote)
        return url

    async def _propfind(self, remote: str, *, depth: str, http: httpx.AsyncClient | None = None) -> list[FileEntry]:
        """Return bounded WebDAV metadata without exposing credentials."""

        headers = {
            "Depth": depth,
            "Content-Type": "application/xml; charset=utf-8",
        }
        body = """<?xml version="1.0" encoding="utf-8" ?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/>
<d:getlastmodified/><d:getcontenttype/><d:getetag/></d:prop></d:propfind>"""
        response = await self._request(
            "PROPFIND", self._webdav_url(remote.strip("/")), headers=headers, content=body, http=http
        )
        _check_status(response, {207}, remote)
        if b"<!DOCTYPE" in response.content.upper() or b"<!ENTITY" in response.content.upper():
            raise ResourceValidationError("Nextcloud returned unsupported XML declarations.")
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise RuntimeError(_error("invalid_response", service="Nextcloud")) from exc
        if root.tag != "{DAV:}multistatus":
            raise ResourceValidationError("Nextcloud returned an invalid DAV envelope.")
        dav_prefix = unquote(urlsplit(self._webdav_url("")).path).rstrip("/")
        entries: list[FileEntry] = []
        seen: set[str] = set()
        for item in root.findall("{DAV:}response"):
            href = item.findtext("{DAV:}href") or ""
            decoded_path = unquote(urlsplit(href).path)
            if decoded_path.rstrip("/") != dav_prefix and not decoded_path.startswith(
                dav_prefix + "/"
            ):
                raise ResourceValidationError("Nextcloud returned a path outside the account.")
            path = decoded_path[len(dav_prefix) :].strip("/")
            if path in seen:
                raise ResourceValidationError("Nextcloud returned duplicate paths.")
            seen.add(path)
            self._webdav_url(path)
            normalized = remote.strip("/")
            if path != normalized and (depth == "0" or path.rpartition("/")[0] != normalized):
                raise ResourceValidationError(
                    "Nextcloud returned a path outside the requested folder."
                )
            prop = None
            for propstat in item.findall("{DAV:}propstat"):
                status = (propstat.findtext("{DAV:}status") or "").split()
                if len(status) >= 2 and status[1] == "200":
                    prop = propstat.find("{DAV:}prop")
                    break
            if prop is None:
                raise PermissionError(
                    "Nextcloud did not return readable properties for a resource."
                )
            resource_type = prop.find("{DAV:}resourcetype")
            if resource_type is None:
                raise ResourceValidationError("Nextcloud did not identify the resource type.")
            is_dir = resource_type.find("{DAV:}collection") is not None
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
                    etag=prop.findtext("{DAV:}getetag"),
                )
            )
        return entries

    async def resource_infos(self, paths: Sequence[str]) -> dict[str, FileEntry]:
        """Check siblings in one bounded DAV response, falling back to exact reads.

        Only successful per-resource properties authorize a requested path. A
        denied, oversized or incomplete listing falls back to Depth: 0, so an
        unreadable parent never hides a directly readable child.
        """
        requested = dict.fromkeys(paths)
        folders: dict[str, list[str]] = {}
        for path in requested:
            normalized = path.strip("/")
            folders.setdefault(normalized.rpartition("/")[0], []).append(path)
        pending: asyncio.Queue[tuple[str, list[str]] | None] = asyncio.Queue()
        for folder, children in folders.items():
            pending.put_nowait((folder, children))
        readable: dict[str, FileEntry] = {}
        async with self._client() as http:
            async def worker() -> None:
                while True:
                    job = await pending.get()
                    try:
                        if job is None:
                            return
                        folder, children = job
                        if len(children) == 1:
                            path = children[0]
                            try:
                                entries = await self._propfind(path, depth="0", http=http)
                            except Exception:
                                continue
                            if len(entries) == 1:
                                readable[path] = entries[0]
                            continue
                        entries_by_path: dict[str, FileEntry] = {}
                        try:
                            entries = await self._propfind(folder, depth="1", http=http)
                            entries_by_path = {entry.path.strip("/") if entry.path != "." else "": entry for entry in entries}
                        except Exception:
                            pass
                        for path in children:
                            entry = entries_by_path.get(path.strip("/"))
                            if entry is None:
                                pending.put_nowait((path, [path]))
                            else:
                                readable[path] = entry
                    finally:
                        pending.task_done()
            async with asyncio.TaskGroup() as group:
                workers = min(8, len(requested))
                for _ in range(workers):
                    group.create_task(worker())
                await pending.join()
                for _ in range(workers):
                    pending.put_nowait(None)
        return readable

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        """Return WebDAV metadata for one resource."""

        entries = await self._propfind(path, depth="0")
        if len(entries) != 1:
            raise FileNotFoundError(path)
        entry = entries[0]
        if include_sha256 and not entry.is_dir:
            from dataclasses import replace

            with tempfile.TemporaryDirectory(prefix="galaris_nextcloud_checksum_") as folder:
                temporary = Path(folder) / "content"
                downloaded = await self.download_versioned(path, temporary)
                if entry.etag != downloaded.etag:
                    raise ResourceRevisionConflict(
                        "Nextcloud changed during checksum calculation; retry."
                    )

                def digest() -> str:
                    with temporary.open("rb") as stream:
                        return hashlib.file_digest(stream, "sha256").hexdigest()

                entry = replace(entry, sha256=await complete_io(digest))
        return entry

    async def resource_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing:
        """List a bounded page; continue with resource_list_page and its cursor."""

        return await self.resource_list_page(path, recursive=recursive, limit=limit)

    async def resource_list_page(
        self, path: str, *, recursive: bool, limit: int, cursor: str | None = None
    ) -> FileListing:
        root = path.strip("/")
        scope = hashlib.sha256(
            json.dumps([self.base_url, self.username, root, recursive]).encode()
        ).hexdigest()
        state = _Cursor(scope=scope, frames=[_Frame(path=root)])
        if cursor:
            if len(cursor) > 65536:
                raise ResourceValidationError("Invalid Nextcloud listing cursor")
            try:
                state = _Cursor.model_validate_json(base64.urlsafe_b64decode(cursor.encode()))
            except (ValueError, ValidationError) as exc:
                raise ResourceValidationError("Invalid Nextcloud listing cursor") from exc
            if state.scope != scope or not state.frames or state.frames[0].path != root:
                raise ResourceValidationError(
                    "Nextcloud cursor belongs to a different account or listing"
                )
            for parent, child in zip(state.frames, state.frames[1:]):
                if not recursive or child.path.rpartition("/")[0] != parent.path:
                    raise ResourceValidationError("Invalid Nextcloud traversal cursor")
        result: list[FileEntry] = []
        requests = 0
        async with asyncio.timeout(_REQUEST_SECONDS):
            while state.frames and len(result) < min(max(limit, 1), 500) and requests < 64:
                frame = state.frames[-1]
                entries = await self._propfind(frame.path, depth="1")
                requests += 1
                own = next(
                    (
                        item
                        for item in entries
                        if (item.path if item.path != "." else "") == frame.path
                    ),
                    None,
                )
                if own is None or not own.is_dir:
                    raise NotADirectoryError(frame.path)
                children = sorted(
                    (item for item in entries if item is not own), key=lambda item: item.path
                )
                fingerprint = hashlib.sha256(
                    json.dumps([(e.path, e.is_dir, e.etag) for e in children]).encode()
                ).hexdigest()
                if frame.fingerprint and frame.fingerprint != fingerprint:
                    raise ResourceRevisionConflict(
                        "Nextcloud folder changed during pagination; restart the listing."
                    )
                frame.fingerprint = fingerprint
                while frame.offset < len(children) and len(result) < min(max(limit, 1), 500):
                    child = children[frame.offset]
                    frame.offset += 1
                    result.append(child)
                    if recursive and child.is_dir:
                        if len(state.frames) >= 64:
                            raise ResourceValidationError(
                                "Nextcloud folder depth exceeds 64 levels"
                            )
                        state.frames.append(_Frame(path=child.path))
                        break
                if state.frames[-1] is frame and frame.offset >= len(children):
                    state.frames.pop()
        token = (
            base64.urlsafe_b64encode(state.model_dump_json().encode()).decode()
            if state.frames
            else None
        )
        if token and len(token) > 65536:
            raise ResourceValidationError("Nextcloud traversal cursor exceeds its size limit")
        return FileListing(
            path=root or ".", entries=tuple(result), truncated=bool(token), next_cursor=token
        )

    async def resource_delete(self, path: str) -> FileMutation:
        """Delete one file conditionally; never recursively delete a collection."""

        info = await self.resource_info(path)
        if info.is_dir:
            raise IsADirectoryError(
                "Nextcloud folder deletion is not exposed by file_delete; delete individual files explicitly."
            )
        return await self.resource_delete_conditional(path, expected_etag=_strong_etag(info.etag))

    async def resource_delete_conditional(self, path: str, *, expected_etag: str) -> FileMutation:
        info = await self.resource_info(path)
        if info.is_dir:
            raise IsADirectoryError(
                "Nextcloud folder deletion is not exposed by file_delete; delete individual files explicitly."
            )
        if info.etag != expected_etag:
            raise ResourceRevisionConflict(
                "The Nextcloud file changed before deletion; its new version was preserved."
            )
        response = await self._request(
            "DELETE",
            self._webdav_url(path.strip("/")),
            headers={"If-Match": _strong_etag(expected_etag)},
        )
        _check_status(response, {200, 204}, path)
        return FileMutation(path=path.strip("/"), size=info.size or 0, state="deleted")

    async def _resource_relocate(
        self,
        method: str,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        source_info = await self.resource_info(source)
        if source_info.is_dir:
            raise IsADirectoryError(
                "Use explicit file operations; collection relocation is not supported."
            )
        folder = destination.strip("/").rpartition("/")[0]
        async with asyncio.timeout(_REQUEST_SECONDS), self._client() as http:
            if folder:
                await self._ensure_dirs(http, folder)
            response = await self._request(
                method,
                self._webdav_url(source.strip("/")),
                headers={
                    "Destination": self._webdav_url(destination.strip("/")),
                    "Overwrite": "T" if overwrite else "F",
                    "If-Match": _strong_etag(source_info.etag),
                },
            )
        if response.status_code not in {201, 204}:
            if response.status_code == 412 and not overwrite:
                if (await self.resource_info(source)).etag != source_info.etag:
                    raise ResourceRevisionConflict(
                        "The Nextcloud source changed during relocation; read it again."
                    )
                raise FileExistsError(destination)
            _check_status(response, {201, 204}, source)
        return FileMutation(
            path=destination.strip("/"),
            source=source.strip("/"),
            size=source_info.size or 0,
            state="moved" if method == "MOVE" else "copied",
        )

    async def resource_copy(
        self,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        return await self._resource_relocate("COPY", source, destination, overwrite=overwrite)

    async def resource_move(
        self,
        source: str,
        destination: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        return await self._resource_relocate("MOVE", source, destination, overwrite=overwrite)


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
    indexing_modes=("excluded", "known_uris", "recursive"),
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
