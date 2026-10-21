"""SFTP-backed file provider sharing the console SSH connection."""

from __future__ import annotations

import codecs
import hashlib
import json
import mimetypes
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import asyncssh
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download

from app.file_share.path_normalization import (
    join_file_references,
    normalize_file_reference,
)
from app.file_share.transport import CHUNK_SIZE
from app.file_share.file_contracts import (
    FileEntry,
    FileListing,
    FileMutation,
    FileText,
)
from app.tools.contracts import ToolCallRejectedError

from .ssh_client import SshExecutionTransport

_SFTP_TYPE_DIRECTORY = 2
_SFTP_TYPE_SYMLINK = 3


class SshAgentFileTransport:
    """File transport rooted at the remote Unix home."""

    def __init__(self, execution: SshExecutionTransport) -> None:
        self._execution = execution

    def storage_path_label(self) -> str:
        config = self._execution.config
        return f"ssh://{config.username}@{config.host}:{config.port}/~"

    async def _client(self) -> Any:
        connection = await self._execution.connection()
        return await connection.start_sftp_client()

    @staticmethod
    def _inside(home: str, path: str) -> bool:
        root = home.rstrip("/") or "/"
        return path == root or path.startswith(root + "/")

    async def _lexical(self, ref: str, target: str = "") -> tuple[str, str]:
        home = await self._execution.home()
        relative = join_file_references(
            ref,
            target,
            root=home,
            aliases=(home,),
            allow_root=True,
        )
        absolute = str(PurePosixPath(home) / relative)
        return absolute, relative

    async def normalize_resource_path(
        self,
        value: str,
        *,
        allow_root: bool = False,
    ) -> str:
        """Return the canonical path relative to the connected Unix home."""

        home = await self._execution.home()
        return normalize_file_reference(
            value,
            root=home,
            aliases=(home,),
            allow_root=allow_root,
        )

    async def _resolve_existing(self, sftp: Any, ref: str, target: str = "") -> tuple[str, str]:
        absolute, _relative = await self._lexical(ref, target)
        home = str(await sftp.realpath(await self._execution.home())).rstrip("/") or "/"
        try:
            real = str(await sftp.realpath(absolute))
            # OpenSSH may normalize a missing path instead of rejecting realpath(),
            # so existence must be checked explicitly at this provider boundary.
            await sftp.lstat(real)
        except asyncssh.SFTPNoSuchFile as exc:
            raise FileNotFoundError(ref) from exc
        if not self._inside(home, real):
            raise ValueError("Path resolves outside the SSH home")
        relative = PurePosixPath(real).relative_to(PurePosixPath(home)).as_posix()
        return real, relative or "."

    async def _resolve_destination(
        self,
        sftp: Any,
        ref: str,
        target: str = "",
    ) -> tuple[str, str]:
        _absolute, relative = await self._lexical(ref, target)
        home = str(await sftp.realpath(await self._execution.home())).rstrip("/") or "/"
        relative_path = PurePosixPath(relative)
        current = home
        for part in relative_path.parent.parts:
            if part in {"", "."}:
                continue
            candidate = str(PurePosixPath(current) / part)
            try:
                resolved = str(await sftp.realpath(candidate))
            except asyncssh.SFTPNoSuchFile:
                resolved = candidate
            if not self._inside(home, resolved):
                raise ValueError("Destination parent resolves outside the SSH home")
            try:
                # OpenSSH can normalize a missing path successfully. Check it
                # explicitly before deciding whether its directory exists.
                attrs = await sftp.stat(resolved)
            except asyncssh.SFTPNoSuchFile:
                await sftp.mkdir(candidate)
                resolved = str(await sftp.realpath(candidate))
                attrs = await sftp.stat(resolved)
            if not self._inside(home, resolved):
                raise ValueError("Destination parent resolves outside the SSH home")
            if attrs.type != _SFTP_TYPE_DIRECTORY:
                raise NotADirectoryError(ref)
            current = resolved
        destination = str(PurePosixPath(current) / relative_path.name)
        try:
            resolved_destination = str(await sftp.realpath(destination))
        except asyncssh.SFTPNoSuchFile:
            resolved_destination = destination
        if not self._inside(home, resolved_destination):
            raise ValueError("Destination resolves outside the SSH home")
        canonical_relative = PurePosixPath(resolved_destination).relative_to(
            PurePosixPath(home)
        ).as_posix()
        return resolved_destination, canonical_relative or "."

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        return await copy_download(self.iter_bytes(remote, target=target), dest, max_bytes=max_bytes)

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        async def chunks() -> AsyncIterator[bytes]:
            with src.open("rb") as source:
                while chunk := source.read(CHUNK_SIZE):
                    yield chunk

        location, _size = await self.upload_stream(chunks(), filename, target=target)
        return location

    async def iter_range(self, remote: str, *, offset: int, length: int,
                         target: str = "") -> AsyncIterator[bytes]:
        sftp = await self._client()
        try:
            source, _relative = await self._resolve_existing(sftp, remote, target)
            async with sftp.open(source, "rb", encoding=None) as input_file:
                remaining = length
                while remaining:
                    chunk = bytes(await input_file.read(min(CHUNK_SIZE, remaining), offset=offset))
                    if not chunk:
                        raise OSError("Console file was truncated during playback")
                    remaining -= len(chunk)
                    offset += len(chunk)
                    yield chunk
        finally:
            sftp.exit()

    async def iter_bytes(
        self,
        remote: str,
        *,
        target: str = "",
        offset: int = 0,
    ) -> AsyncIterator[bytes]:
        sftp = await self._client()
        try:
            source, _relative = await self._resolve_existing(sftp, remote, target)
            async with sftp.open(source, "rb", encoding=None) as input_file:
                position = max(0, offset)
                while True:
                    chunk = await input_file.read(CHUNK_SIZE, offset=position)
                    if not chunk:
                        break
                    raw = bytes(chunk)
                    position += len(raw)
                    yield raw
        finally:
            sftp.exit()

    async def upload_stream(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        *,
        target: str = "",
    ) -> tuple[str, int]:
        sftp = await self._client()
        temporary = ""
        publishing = False
        try:
            destination, relative = await self._resolve_destination(sftp, filename, target)
            path = PurePosixPath(destination)
            temporary = str(path.with_name(f".{path.name}.galaris-part-{uuid4().hex}"))
            size = 0
            async with sftp.open(temporary, "wb", encoding=None) as output:
                async for chunk in chunks:
                    await output.write(chunk)
                    size += len(chunk)
            publishing = True
            try:
                await sftp.posix_rename(temporary, destination)
            except asyncssh.SFTPOpUnsupported:
                try:
                    await sftp.remove(destination)
                except asyncssh.SFTPNoSuchFile:
                    pass
                await sftp.rename(temporary, destination)
            return relative, size
        except BaseException as exc:
            cleaned = True
            if temporary:
                try:
                    await sftp.remove(temporary)
                except asyncssh.SFTPNoSuchFile:
                    pass
                except (asyncssh.SFTPError, OSError):
                    cleaned = False
            if isinstance(exc, Exception) and not publishing and cleaned:
                # Only disposable staging bytes and idempotent parent directories
                # may have changed. The destination file has not been published.
                raise ToolCallRejectedError(
                    "Upload failed before publishing the destination file; "
                    "temporary content was removed. Correct the source or destination and retry."
                ) from exc
            raise
        finally:
            sftp.exit()

    async def delete(self, remote: str, *, target: str = "") -> None:
        sftp = await self._client()
        try:
            path, _relative = await self._resolve_existing(sftp, remote, target)
            await sftp.remove(path)
        finally:
            sftp.exit()

    @staticmethod
    def _entry(path: str, attrs: Any, relative: str, sha256: str = "") -> FileEntry:
        is_dir = attrs.type == _SFTP_TYPE_DIRECTORY
        timestamp = (
            datetime.fromtimestamp(float(attrs.mtime), timezone.utc).isoformat()
            if attrs.mtime is not None
            else ""
        )
        return FileEntry(
            path=relative,
            is_dir=is_dir,
            size=0 if is_dir else int(attrs.size or 0),
            modified_at=timestamp,
            mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            sha256=sha256,
        )

    async def file_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing:
        sftp = await self._client()
        try:
            base, base_relative = await self._resolve_existing(sftp, path or ".")
            attrs = await sftp.stat(base, follow_symlinks=False)
            if attrs.type != _SFTP_TYPE_DIRECTORY:
                return FileListing(
                    base_relative,
                    (self._entry(base, attrs, base_relative),),
                )
            entries: list[FileEntry] = []
            pending = [base]
            truncated = False
            home = str(await sftp.realpath(await self._execution.home())).rstrip("/") or "/"
            while pending:
                directory = pending.pop(0)
                async for item in sftp.scandir(directory):
                    name = str(item.filename)
                    if name in {".", ".."}:
                        continue
                    candidate = str(PurePosixPath(directory) / name)
                    real = str(await sftp.realpath(candidate))
                    if not self._inside(home, real):
                        continue
                    relative = PurePosixPath(real).relative_to(PurePosixPath(home)).as_posix()
                    item_attrs = await sftp.lstat(candidate)
                    if item_attrs.type == _SFTP_TYPE_SYMLINK:
                        continue
                    entries.append(self._entry(candidate, item_attrs, relative))
                    if recursive and item_attrs.type == _SFTP_TYPE_DIRECTORY:
                        pending.append(candidate)
                    if len(entries) >= limit:
                        truncated = bool(pending)
                        break
                if len(entries) >= limit:
                    truncated = True
                    break
            entries.sort(key=lambda entry: entry.path)
            return FileListing(base_relative, tuple(entries[:limit]), truncated)
        finally:
            sftp.exit()

    async def resource_list(self, path: str, *, recursive: bool, limit: int) -> FileListing:
        return await self.resource_list_page(path, recursive=recursive, limit=limit)

    async def resource_list_page(self, path: str, *, recursive: bool, limit: int,
        cursor: str | None = None) -> FileListing:
        """Keep only one page in memory, using canonical paths as continuation keys."""
        if recursive:
            if cursor:
                raise ValueError("Recursive console listing does not support cursors")
            return await self.file_list(path, recursive=True, limit=limit)
        sftp = await self._client()
        try:
            base, relative = await self._resolve_existing(sftp, path or ".")
            binding_key = hashlib.sha256(base.encode()).hexdigest()
            after = ""
            if cursor:
                try:
                    binding, after = json.loads(cursor)
                    if binding != binding_key or not isinstance(after, str):
                        raise ValueError
                except (ValueError, TypeError) as exc:
                    raise ValueError("Invalid console listing cursor") from exc
            home = str(await sftp.realpath(await self._execution.home())).rstrip("/") or "/"
            selected: list[FileEntry] = []
            async for item in sftp.scandir(base):
                name = str(item.filename)
                if name in {".", ".."}:
                    continue
                candidate = str(PurePosixPath(base) / name)
                attrs = await sftp.lstat(candidate)
                if attrs.type == _SFTP_TYPE_SYMLINK:
                    continue
                real = str(await sftp.realpath(candidate))
                if not self._inside(home, real):
                    continue
                entry_path = PurePosixPath(real).relative_to(PurePosixPath(home)).as_posix()
                if entry_path <= after:
                    continue
                selected.append(self._entry(real, attrs, entry_path))
                selected.sort(key=lambda entry: entry.path)
                if len(selected) > limit + 1:
                    selected.pop()
            truncated = len(selected) > limit
            page = selected[:limit]
            next_cursor = json.dumps([binding_key, page[-1].path]) if truncated else None
            return FileListing(relative, tuple(page), truncated, next_cursor)
        finally:
            sftp.exit()

    async def file_info(self, path: str, *, include_sha256: bool) -> FileEntry:
        sftp = await self._client()
        try:
            target, relative = await self._resolve_existing(sftp, path)
            attrs = await sftp.stat(target, follow_symlinks=False)
        except asyncssh.SFTPNoSuchFile as exc:
            raise FileNotFoundError(path) from exc
        finally:
            sftp.exit()
        digest = ""
        if include_sha256 and attrs.type != _SFTP_TYPE_DIRECTORY:
            hasher = hashlib.sha256()
            async for chunk in self.iter_bytes(path):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        return self._entry(target, attrs, relative, digest)

    async def file_read_text(
        self,
        path: str,
        *,
        offset: int,
        max_chars: int,
    ) -> FileText:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        start = max(0, offset)
        total = 0
        selected: list[str] = []
        async for chunk in self.iter_bytes(path):
            text = decoder.decode(chunk)
            chunk_start = total
            total += len(text)
            left = max(0, start - chunk_start)
            right = min(len(text), start + max_chars - chunk_start)
            if right > left:
                selected.append(text[left:right])
        tail = decoder.decode(b"", final=True)
        if tail:
            chunk_start = total
            total += len(tail)
            left = max(0, start - chunk_start)
            right = min(len(tail), start + max_chars - chunk_start)
            if right > left:
                selected.append(tail[left:right])
        content = "".join(selected)
        _absolute, relative = await self._lexical(path)
        return FileText(relative, content, start, start + len(content), total)

    async def file_write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        if not overwrite:
            sftp = await self._client()
            try:
                try:
                    await self._resolve_existing(sftp, path)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(path)
            finally:
                sftp.exit()

        encoded = content.encode("utf-8")

        async def chunks() -> AsyncIterator[bytes]:
            yield encoded

        location, _bytes = await self.upload_stream(chunks(), path)
        return FileMutation(location, len(content), state="written")

    async def file_append_text(self, path: str, content: str) -> FileMutation:
        sftp = await self._client()
        try:
            target, relative = await self._resolve_destination(sftp, path)
            async with sftp.open(target, "ab", encoding=None) as output:
                await output.write(content.encode("utf-8"))
            return FileMutation(relative, len(content), state="appended")
        finally:
            sftp.exit()

    async def file_copy(self, source: str, destination: str) -> FileMutation:
        sftp = await self._client()
        try:
            src, src_relative = await self._resolve_existing(sftp, source)
            dest, dest_relative = await self._resolve_destination(sftp, destination)
            await sftp.copy(src, dest, follow_symlinks=False)
            attrs = await sftp.stat(dest)
            return FileMutation(
                dest_relative,
                int(attrs.size or 0),
                source=src_relative,
                state="copied",
            )
        finally:
            sftp.exit()

    async def file_move(self, source: str, destination: str, *, overwrite: bool = False) -> FileMutation:
        sftp = await self._client()
        try:
            src, src_relative = await self._resolve_existing(sftp, source)
            dest, dest_relative = await self._resolve_destination(sftp, destination)
            if src_relative in {"", "."} or dest_relative in {"", "."}:
                raise PermissionError("The SSH home cannot be moved")
            if overwrite:
                try:
                    await sftp.posix_rename(src, dest)
                except asyncssh.SFTPOpUnsupported:
                    await sftp.rename(src, dest)
            else:
                await sftp.rename(src, dest)
            attrs = await sftp.stat(dest)
            return FileMutation(
                dest_relative,
                int(attrs.size or 0),
                source=src_relative,
                state="moved",
            )
        finally:
            sftp.exit()

    async def file_delete(self, path: str) -> FileMutation:
        sftp = await self._client()
        try:
            target, relative = await self._resolve_existing(sftp, path)
            attrs = await sftp.stat(target, follow_symlinks=False)
            if attrs.type == _SFTP_TYPE_DIRECTORY:
                raise IsADirectoryError(path)
            await sftp.remove(target)
            return FileMutation(relative, int(attrs.size or 0), state="deleted")
        finally:
            sftp.exit()

    async def resource_delete_collection(self, path: str) -> FileMutation:
        """Remove an explicitly selected tree, bounded and without following links."""
        sftp = await self._client()
        try:
            target, relative = await self._resolve_existing(sftp, path)
            if relative in {"", "."}:
                raise PermissionError("The SSH home cannot be deleted")
            attrs = await sftp.lstat(target)
            if attrs.type != _SFTP_TYPE_DIRECTORY:
                raise NotADirectoryError(path)
            pending = [(target, 0)]
            entries: list[tuple[str, bool]] = []
            while pending:
                current, depth = pending.pop()
                current_attrs = await sftp.lstat(current)
                if current_attrs.type == _SFTP_TYPE_SYMLINK:
                    raise PermissionError("Directory deletion cannot follow symbolic links")
                directory = current_attrs.type == _SFTP_TYPE_DIRECTORY
                entries.append((current, directory))
                if len(entries) > 10_000 or depth > 64:
                    raise ValueError("Directory deletion exceeds its bounded traversal limit")
                if directory:
                    async for child in sftp.scandir(current):
                        name = str(child.filename)
                        if name in {".", ".."}:
                            continue
                        if "/" in name or "\\" in name:
                            raise ValueError("Invalid directory entry")
                        pending.append((str(PurePosixPath(current) / name), depth + 1))
                        if len(entries) + len(pending) > 10_000:
                            raise ValueError("Directory deletion exceeds its bounded traversal limit")
            for current, directory in reversed(entries):
                resolved, _ = await self._resolve_existing(sftp, current)
                current_attrs = await sftp.lstat(current)
                if resolved != current or current_attrs.type == _SFTP_TYPE_SYMLINK or (current_attrs.type == _SFTP_TYPE_DIRECTORY) != directory:
                    raise ValueError("The directory changed; inspect remaining entries before retrying deletion")
                if directory:
                    await sftp.rmdir(current)
                else:
                    await sftp.remove(current)
            return FileMutation(relative, state="deleted")
        finally:
            sftp.exit()
