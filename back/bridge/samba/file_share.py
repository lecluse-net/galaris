"""Bounded SMB resources, rooted in a server, share or subdirectory."""
from __future__ import annotations

import base64
import hashlib
import json
import time
import unicodedata
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.file_share import (
    FileEntry, FileListing, FileMutation, FileShareBridge, FileShareParamInfo,
    ResourceRevisionConflict, ResourceValidationError,
)
from core.util import DEFAULT_DOWNLOAD_BYTES, complete_io
from . import sdk

_CHUNK = 64 * 1024
_DIRECTORY_ENTRIES = 10_000
_DIRECTORY_BYTES = 8 * 1024 * 1024
_DIRECTORY = 0x10
_REPARSE = 0x400


def _path(value: str, *, root: bool = False) -> str:
    value = unicodedata.normalize("NFC", value)
    if root and value in {"", ".", "/"}:
        return ""
    if value.startswith(("/", "\\")) or "\\" in value or len(value) > 4096:
        raise ResourceValidationError("SMB paths must be relative to the configured share.")
    value = value.rstrip("/")
    parts = value.split("/")
    if not value or len(parts) > 64 or any(
        part in {"", ".", ".."} or part.endswith((".", " "))
        or any(c in ':*?"<>|' or ord(c) < 32 or ord(c) == 127 for c in part)
        for part in parts
    ):
        raise ResourceValidationError("Invalid SMB path.")
    return value


def _etag(metadata: sdk.Metadata) -> str:
    return '"' + hashlib.sha256(
        f"{metadata.inode}:{metadata.size}:{metadata.modified_ns}:{metadata.changed_ns}".encode()
    ).hexdigest() + '"'


def _safe(metadata: sdk.Metadata) -> None:
    if metadata.attributes & _REPARSE:
        raise PermissionError("SMB reparse points and symbolic links are unsupported.")


def _entry(path: str, metadata: sdk.Metadata, *, sha256: str = "") -> FileEntry:
    import mimetypes
    _safe(metadata)
    directory = bool(metadata.attributes & _DIRECTORY)
    # SMB FILETIME is measured in 100 ns ticks since 1601.
    timestamp = (metadata.modified_ns - 116444736000000000) / 10_000_000
    return FileEntry(path=path or ".", is_dir=directory, size=0 if directory else metadata.size,
                     modified_at=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                     mime_type="inode/directory" if directory else mimetypes.guess_type(path)[0] or "application/octet-stream",
                     sha256=sha256, etag=None if directory else _etag(metadata))


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)
    offset: int = Field(default=0, ge=0, le=_DIRECTORY_ENTRIES)
    fingerprint: str = ""


class _Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    frames: list[_Frame] = Field(max_length=64)


class SambaFileClient:
    def __init__(self, base_url: str, username: str, password: str, *, encrypt: bool = False) -> None:
        try:
            url = urlsplit(base_url)
            if (url.scheme != "smb" or not url.hostname or url.username or url.password
                or url.query or url.fragment or "\\" in base_url
                or any(ord(c) < 32 or ord(c) == 127 for c in base_url)):
                raise ValueError
            # A URL names the external server/share. Resource locators never do.
            host = url.hostname
            if any(c in host for c in '/\\:@[]%'):
                raise ValueError
            port = url.port if url.port is not None else 445
            if not 1 <= port <= 65535:
                raise ValueError
            location = _path(unquote(url.path.removeprefix("/")), root=url.path in {"", "/"})
            share, _, folder = location.partition("/")
        except ValueError:
            raise ResourceValidationError(
                "Invalid Samba Tool configuration: base_url must identify a server, "
                "optionally with an existing share or folder: smb://server[:port][/share[/folder]], "
                "without credentials. Ask the administrator to complete or correct "
                "the Tool's base_url. Keep using the connected Tool's code:// resource "
                "URIs in file tools; smb:// is only for base_url."
            ) from None
        if not username or not password:
            raise ResourceValidationError("SMB login and password are required.")
        self.server, self.port, self.share, self.folder = host, port, share, folder
        self.username, self.password, self.encrypt = username, password, encrypt

    async def _run[T](self, operation: Callable[[sdk.SmbSession], T]) -> T:
        def execute() -> T:
            with sdk.session(self.server, self.port, self.share or "IPC$", self.username,
                             self.password, self.encrypt) as active:
                return operation(active)
        return await complete_io(execute)

    async def iter_range(self, remote: str, *, offset: int, length: int,
                         target: str = "") -> AsyncIterator[bytes]:
        path = _path(f"{target}/{remote}" if target else remote)
        if offset < 0 or length < 0:
            raise ResourceValidationError("Invalid SMB byte range")
        remaining = length
        version: str | None = None
        while remaining:
            stack = ExitStack()
            try:
                active = await complete_io(stack.enter_context, sdk.session(
                    self.server, self.port, self.share or "IPC$", self.username, self.password, self.encrypt))
                await complete_io(self._check, active, path)
                handle = await complete_io(stack.enter_context, active.open(self._unc(active, path), "rb"))
                metadata = await complete_io(active.fstat, handle)
                _safe(metadata)
                if metadata.attributes & _DIRECTORY:
                    raise IsADirectoryError(path)
                if version is not None and version != _etag(metadata):
                    raise ResourceRevisionConflict("SMB file changed during playback")
                version = _etag(metadata)
                await complete_io(handle.seek, offset)
                # Renew before the SDK's operation deadline, even during long playback.
                renew_at = time.monotonic() + 120
                while remaining and time.monotonic() < renew_at:
                    chunk = await complete_io(handle.read, min(_CHUNK, remaining))
                    if not chunk:
                        raise OSError("SMB file was truncated during playback")
                    remaining -= len(chunk)
                    offset += len(chunk)
                    yield chunk
            finally:
                await complete_io(stack.close)

    def _unc(self, active: sdk.SmbSession, path: str) -> str:
        if not self.share:
            return f"\\\\{self.server}\\" + path.replace("/", "\\")
        components = [active.root, self.folder.replace("/", "\\"), path.replace("/", "\\")]
        return "\\".join(part for part in components if part)

    def _check(self, active: sdk.SmbSession, path: str, *, missing: bool = False) -> sdk.Metadata | None:
        if not self.share:
            if not path:
                # The authenticated server root is a virtual collection of shares.
                return sdk.Metadata(0, 0, 116444736000000000, 116444736000000000, _DIRECTORY)
            share, _, remainder = path.partition("/")
            current = f"\\\\{self.server}\\{share}"
            active.connect_share(current)
            parts = remainder.split("/")
        else:
            parts = "/".join(part for part in (self.folder, path) if part).split("/")
            current = active.root
            active.connect_share(current)
        metadata = active.stat(current)
        _safe(metadata)
        for index, part in enumerate(parts if parts != [""] else []):
            current += "\\" + part
            try:
                metadata = active.stat(current)
            except FileNotFoundError:
                if missing and index == len(parts) - 1:
                    return None
                raise
            _safe(metadata)
            if index < len(parts) - 1 and not metadata.attributes & _DIRECTORY:
                raise NotADirectoryError("SMB parent is not a directory.")
        return metadata

    def _parents(self, active: sdk.SmbSession, path: str) -> None:
        # Servers and shares are existing roots, never directories to create.
        parents = path.split("/")[:-1]
        if not self.share:
            self._require_file_path(path)
            parent = parents.pop(0)
            self._check(active, parent)
        else:
            self._check(active, "")
            parent = ""
        for part in parents:
            parent = f"{parent}/{part}" if parent else part
            try:
                active.mkdir(self._unc(active, parent))
            except FileExistsError:
                pass
            metadata = self._check(active, parent)
            if metadata is None or not metadata.attributes & _DIRECTORY:
                raise NotADirectoryError("SMB parent is not a directory.")

    def _download(self, active: sdk.SmbSession, path: str, dest: Path, max_bytes: int) -> FileEntry:
        self._check(active, path)
        with active.open(self._unc(active, path), "rb") as handle:
            metadata = active.fstat(handle)
            _safe(metadata)
            if metadata.attributes & _DIRECTORY:
                raise IsADirectoryError(path)
            if metadata.size > max_bytes:
                raise ResourceValidationError("SMB file exceeds the download byte limit.")
            received = 0
            with dest.open("wb") as output:
                while chunk := handle.read(min(_CHUNK, max_bytes - received + 1)):
                    received += len(chunk)
                    if received > max_bytes:
                        raise ResourceValidationError("SMB file exceeds the download byte limit.")
                    output.write(chunk)
            return _entry(path, metadata)

    async def download_versioned(self, remote: str, dest: Path, *, max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> FileEntry:
        path = _path(remote)
        self._require_file_path(path)
        if max_bytes < 0:
            raise ResourceValidationError("The download byte limit must be nonnegative.")
        try:
            return await self._run(lambda active: self._download(active, path, dest, max_bytes))
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        path = _path(f"{_path(target, root=True)}/{remote}" if target else remote)
        return (await self.download_versioned(path, dest, max_bytes=max_bytes)).size or 0

    def _upload(self, active: sdk.SmbSession, src: Path, path: str, overwrite: bool,
                expected_etag: str | None) -> str:
        if expected_etag is not None and not overwrite:
            raise ResourceValidationError("A version precondition requires overwrite=true.")
        self._parents(active, path)
        self._check(active, path, missing=True)
        created = False
        if overwrite:
            try:
                handle_context = active.open(self._unc(active, path), "r+b")
                handle = handle_context.__enter__()
            except FileNotFoundError:
                if expected_etag is not None:
                    raise ResourceRevisionConflict("The SMB file disappeared; read it again.") from None
                handle_context = active.open(self._unc(active, path), "x+b")
                handle = handle_context.__enter__()
                created = True
        else:
            handle_context = active.open(self._unc(active, path), "x+b")
            handle = handle_context.__enter__()
            created = True
        try:
            metadata = active.fstat(handle)
            _safe(metadata)
            if expected_etag is not None and _etag(metadata) != expected_etag:
                raise ResourceRevisionConflict("The SMB file changed; read it again before modifying it.")
            with src.open("rb") as source:
                while chunk := source.read(_CHUNK):
                    view = memoryview(chunk)
                    while view:
                        written = handle.write(view)
                        if not written:
                            raise OSError("SMB upload made no progress.")
                        view = view[written:]
            handle.truncate(handle.tell())
            handle.flush()
        except BaseException:
            if created:
                active.delete_handle(handle)
            raise
        finally:
            handle_context.__exit__(None, None, None)
        return path

    async def upload_conditional(self, src: Path, filename: str, *, target: str = "", overwrite: bool,
                                 expected_etag: str | None = None) -> str:
        filename = _path(filename)
        if "/" in filename:
            raise ResourceValidationError("An SMB upload filename must be one path segment.")
        parent = _path(target, root=True)
        path = f"{parent}/{filename}" if parent else filename
        self._require_file_path(path)
        return await self._run(lambda active: self._upload(active, src, path, overwrite, expected_etag))

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        return await self.upload_conditional(src, filename, target=target, overwrite=False)

    async def resource_info(self, path: str, *, include_sha256: bool = False) -> FileEntry:
        path = _path(path, root=True)
        def inspect(active: sdk.SmbSession) -> FileEntry:
            metadata = self._check(active, path)
            assert metadata is not None
            if not include_sha256 or metadata.attributes & _DIRECTORY:
                return _entry(path, metadata)
            digest = hashlib.sha256()
            with active.open(self._unc(active, path), "rb") as handle:
                metadata = active.fstat(handle)
                _safe(metadata)
                if metadata.size > DEFAULT_DOWNLOAD_BYTES:
                    raise ResourceValidationError("SMB file exceeds the checksum byte limit.")
                received = 0
                while chunk := handle.read(_CHUNK):
                    received += len(chunk)
                    if received > DEFAULT_DOWNLOAD_BYTES:
                        raise ResourceValidationError("SMB file exceeds the checksum byte limit.")
                    digest.update(chunk)
            return _entry(path, metadata, sha256=digest.hexdigest())
        return await self._run(inspect)

    def _children(self, active: sdk.SmbSession, path: str) -> list[FileEntry]:
        if not self.share and not path:
            entries: list[FileEntry] = []
            for share in active.shares():
                # Only disk shares; IPC, printer and device endpoints are not files.
                if share.kind & 0xFFFF:
                    continue
                _path(share.name)
                if "/" in share.name:
                    raise ResourceValidationError("The server returned an invalid share name.")
                try:
                    metadata = self._check(active, share.name)
                except (PermissionError, FileNotFoundError):
                    continue
                assert metadata is not None
                entries.append(_entry(share.name, metadata))
            return sorted(entries, key=lambda item: item.path)
        metadata = self._check(active, path)
        if metadata is None or not metadata.attributes & _DIRECTORY:
            raise NotADirectoryError(path)
        entries: list[FileEntry] = []
        received = 0
        scanned = 0
        for name in active.children(self._unc(active, path)):
            scanned += 1
            _path(name)
            if "/" in name:
                raise ResourceValidationError("SMB returned an invalid directory entry.")
            received += len(name.encode("utf-8"))
            if scanned > _DIRECTORY_ENTRIES or received > _DIRECTORY_BYTES:
                raise ResourceValidationError("SMB directory exceeds the bounded listing limit; use a smaller folder.")
            child = f"{path}/{name}" if path else name
            metadata = active.stat(self._unc(active, child))
            if metadata.attributes & _REPARSE:
                continue
            entries.append(_entry(child, metadata))
        return sorted(entries, key=lambda item: item.path)

    async def resource_list(self, path: str, *, recursive: bool, limit: int) -> FileListing:
        return await self.resource_list_page(path, recursive=recursive, limit=limit)

    async def resource_list_page(self, path: str, *, recursive: bool, limit: int,
                                 cursor: str | None = None) -> FileListing:
        path = _path(path, root=True)
        if not 1 <= limit <= 500:
            raise ResourceValidationError("SMB listing limits must be between 1 and 500.")
        scope = hashlib.sha256(json.dumps([self.server, self.port, self.share, self.folder,
                                          self.username, path, recursive]).encode()).hexdigest()
        state = _Cursor(scope=scope, frames=[_Frame(path=path)])
        if cursor:
            try:
                if len(cursor) > 100_000:
                    raise ValueError
                state = _Cursor.model_validate_json(base64.urlsafe_b64decode(cursor))
                if state.scope != scope or not state.frames:
                    raise ValueError
                for frame in state.frames:
                    _path(frame.path, root=True)
                    if frame.path != path and (not recursive or (path and not frame.path.startswith(path + "/"))):
                        raise ValueError
            except ValueError:
                raise ResourceValidationError("Invalid SMB listing cursor for this connection and folder.") from None
        def listing(active: sdk.SmbSession) -> FileListing:
            result: list[FileEntry] = []
            cache: dict[str, list[FileEntry]] = {}
            while state.frames and len(result) < limit:
                frame = state.frames[-1]
                if frame.path not in cache:
                    if len(cache) >= 64:
                        break
                    cache[frame.path] = self._children(active, frame.path)
                children = cache[frame.path]
                fingerprint = hashlib.sha256(json.dumps([(e.path, e.is_dir, e.etag) for e in children]).encode()).hexdigest()
                if frame.fingerprint and fingerprint != frame.fingerprint:
                    raise ResourceRevisionConflict("The SMB directory changed; restart the listing.")
                frame.fingerprint = fingerprint
                if frame.offset >= len(children):
                    state.frames.pop()
                    continue
                child = children[frame.offset]
                frame.offset += 1
                result.append(child)
                if child.is_dir and recursive:
                    if len(state.frames) >= 64:
                        raise ResourceValidationError("SMB listing exceeds the maximum directory depth.")
                    state.frames.append(_Frame(path=child.path))
            next_cursor = base64.urlsafe_b64encode(state.model_dump_json().encode()).decode() if state.frames else None
            return FileListing(path=path or ".", entries=tuple(result), truncated=bool(next_cursor), next_cursor=next_cursor)
        return await self._run(listing)

    async def resource_delete(self, path: str) -> FileMutation:
        return await self._delete(path, None)

    async def resource_delete_conditional(self, path: str, *, expected_etag: str) -> FileMutation:
        return await self._delete(path, expected_etag)

    async def resource_delete_collection(self, path: str) -> FileMutation:
        path = _path(path)
        self._require_file_path(path)

        def remove_tree(active: sdk.SmbSession) -> FileMutation:
            root = self._check(active, path)
            if root is None or not root.attributes & _DIRECTORY:
                raise NotADirectoryError(path)
            pending = [(path, 0)]
            entries: list[tuple[str, sdk.Metadata]] = []
            while pending:
                current, depth = pending.pop()
                metadata = self._check(active, current)
                assert metadata is not None
                entries.append((current, metadata))
                if len(entries) > _DIRECTORY_ENTRIES or depth > 64:
                    raise ResourceValidationError("Directory deletion exceeds its bounded traversal limit")
                if metadata.attributes & _DIRECTORY:
                    for name in active.children(self._unc(active, current)):
                        pending.append((_path(f"{current}/{name}"), depth + 1))
                        if len(entries) + len(pending) > _DIRECTORY_ENTRIES:
                            raise ResourceValidationError("Directory deletion exceeds its bounded traversal limit")
            for current, metadata in reversed(entries):
                live = self._check(active, current)
                if live is None or live.inode != metadata.inode or live.attributes != metadata.attributes or (
                    not metadata.attributes & _DIRECTORY and live != metadata
                ):
                    raise ResourceRevisionConflict("The directory changed during deletion; inspect remaining entries before retrying")
                if metadata.attributes & _DIRECTORY:
                    active.rmdir(self._unc(active, current))
                else:
                    with active.open(self._unc(active, current), "rb", delete=True) as handle:
                        actual = active.fstat(handle)
                        _safe(actual)
                        if actual != metadata:
                            raise ResourceRevisionConflict("A file changed during directory deletion")
                        active.delete_handle(handle)
            return FileMutation(path=path, state="deleted")

        return await self._run(remove_tree)

    async def _delete(self, path: str, expected_etag: str | None) -> FileMutation:
        path = _path(path)
        self._require_file_path(path)
        def remove(active: sdk.SmbSession) -> FileMutation:
            self._check(active, path)
            with active.open(self._unc(active, path), "rb", delete=True) as handle:
                metadata = active.fstat(handle)
                _safe(metadata)
                if metadata.attributes & _DIRECTORY:
                    raise IsADirectoryError(path)
                if expected_etag is not None and expected_etag != _etag(metadata):
                    raise ResourceRevisionConflict("The SMB file changed; it was not deleted.")
                active.delete_handle(handle)
            return FileMutation(path=path, state="deleted")
        return await self._run(remove)

    async def resource_copy(self, source: str, destination: str, *, overwrite: bool) -> FileMutation:
        # The generic facade uses the bounded FileTransport transfer for copies.
        import tempfile
        source, destination = _path(source), _path(destination)
        with tempfile.TemporaryDirectory(prefix="galaris_smb_copy_") as folder:
            temporary = Path(folder) / "content"
            entry = await self.download_versioned(source, temporary)
            parent, _, name = destination.rpartition("/")
            await self.upload_conditional(temporary, name, target=parent, overwrite=overwrite)
            return FileMutation(path=destination, source=source, size=entry.size or 0, state="copied")

    async def resource_move(self, source: str, destination: str, *, overwrite: bool) -> FileMutation:
        source, destination = _path(source), _path(destination)
        self._require_file_path(source)
        self._require_file_path(destination)
        if source.casefold() == destination.casefold():
            raise ResourceValidationError("SMB source and destination must differ.")
        if not self.share and source.partition("/")[0].casefold() != destination.partition("/")[0].casefold():
            import tempfile
            with tempfile.TemporaryDirectory(prefix="galaris_smb_move_") as folder:
                temporary = Path(folder) / "content"
                entry = await self.download_versioned(source, temporary)
                parent, _, name = destination.rpartition("/")
                await self.upload_conditional(temporary, name, target=parent, overwrite=overwrite)
                try:
                    assert entry.etag is not None
                    await self.resource_delete_conditional(source, expected_etag=entry.etag)
                except Exception:
                    raise ResourceValidationError(
                        "The destination copy succeeded, but the source was not deleted. "
                        "Inspect both resources before retrying the move."
                    ) from None
                return FileMutation(path=destination, source=source, size=entry.size or 0, state="moved")
        def move(active: sdk.SmbSession) -> FileMutation:
            metadata = self._check(active, source)
            assert metadata is not None
            self._parents(active, destination)
            self._check(active, destination, missing=True)
            active.rename(self._unc(active, source), self._unc(active, destination), overwrite)
            return FileMutation(path=destination, source=source, size=metadata.size, state="moved")
        return await self._run(move)

    def _require_file_path(self, path: str) -> None:
        if not self.share and "/" not in path:
            raise ResourceValidationError(
                "Choose a file inside a share listed by file_list on this Tool's root URI. "
                "The server root and its shares cannot be created, overwritten or deleted."
            )


def build_file_transport(base_url: str, params: dict[str, str]) -> SambaFileClient:
    encryption = params.get("encrypt", "false").lower()
    if encryption not in {"true", "false"}:
        raise ResourceValidationError("SMB encrypt must be true or false.")
    return SambaFileClient(base_url, params["login"], params["password"], encrypt=encryption == "true")


SAMBA_FILE_SHARE_BRIDGE = FileShareBridge(
    service="samba", label="Samba / SMB 2–3",
    indexing_modes=("excluded", "known_uris", "recursive"),
    params=(FileShareParamInfo(key="login", label="Login (DOMAIN\\user or user)"),
            FileShareParamInfo(key="password", label="Password", type="password"),
            FileShareParamInfo(key="encrypt", label="Require SMB 3 encryption (true/false)", required=False)),
    build=build_file_transport,
)
