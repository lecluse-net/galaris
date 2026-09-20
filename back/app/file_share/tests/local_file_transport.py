"""Filesystem-backed transport used only by file-share contract tests."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.file_share.path_normalization import (
    join_file_references,
    normalize_file_reference,
)
from app.file_share.file_contracts import (
    FileEntry,
    FileListing,
    FileMutation,
    FileText,
)


class TemporaryFileTransport:
    """Minimal local implementation of the provider transport contract for tests."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def root_path(self) -> Path:
        return self._root

    def resolve_path(
        self,
        ref: str,
        target: str = "",
        *,
        allow_root: bool = False,
        create_parent: bool = True,
    ) -> Path:
        relative = join_file_references(
            ref,
            target,
            root=self._root.as_posix(),
            allow_root=allow_root,
        )
        path = self._root / relative
        canonical_root = self._root.resolve()
        canonical_path = path.resolve(strict=False)
        if canonical_path != canonical_root and canonical_root not in canonical_path.parents:
            raise ValueError("Path resolves outside the temporary test root")
        if create_parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def normalize_resource_path(
        self,
        value: str,
        *,
        allow_root: bool = False,
    ) -> str:
        return normalize_file_reference(
            value,
            root=self._root.as_posix(),
            allow_root=allow_root,
        )

    def _relative(self, path: Path) -> str:
        relative = path.relative_to(self._root).as_posix()
        return "." if relative == "." else relative

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()

    def _entry(self, path: Path, *, include_sha256: bool = False) -> FileEntry:
        is_dir = path.is_dir()
        return FileEntry(
            path=self._relative(path),
            is_dir=is_dir,
            size=0 if is_dir else path.stat().st_size,
            modified_at=datetime.fromtimestamp(
                path.stat().st_mtime,
                timezone.utc,
            ).isoformat(),
            mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            sha256=self._digest(path) if include_sha256 and not is_dir else "",
        )

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = 512 * 1024 * 1024) -> int:
        source = self.resolve_path(remote, target, create_parent=False)
        if not source.is_file():
            raise FileNotFoundError(remote)
        shutil.copyfile(source, dest)
        return source.stat().st_size

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        destination = self.resolve_path(filename, target)
        shutil.copyfile(src, destination)
        return self._relative(destination)

    async def iter_bytes(
        self,
        remote: str,
        *,
        target: str = "",
        offset: int = 0,
    ) -> AsyncIterator[bytes]:
        source = self.resolve_path(remote, target, create_parent=False)
        if not source.is_file():
            raise FileNotFoundError(remote)
        with source.open("rb") as input_file:
            input_file.seek(max(0, offset))
            while chunk := input_file.read(1 << 20):
                yield chunk

    async def upload_stream(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        *,
        target: str = "",
    ) -> tuple[str, int]:
        destination = self.resolve_path(filename, target)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        size = 0
        try:
            with temporary.open("wb") as output:
                async for chunk in chunks:
                    output.write(chunk)
                    size += len(chunk)
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return self._relative(destination), size

    async def delete(self, remote: str, *, target: str = "") -> None:
        self.resolve_path(remote, target, create_parent=False).unlink(missing_ok=True)

    async def file_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing:
        base = self.resolve_path(path, allow_root=True, create_parent=False)
        if not base.exists():
            raise FileNotFoundError(path or ".")
        if base.is_file():
            return FileListing(self._relative(base), (self._entry(base),))
        iterator = base.rglob("*") if recursive else base.iterdir()
        items = sorted(iterator, key=self._relative)
        return FileListing(
            self._relative(base),
            tuple(self._entry(item) for item in items[:limit]),
            len(items) > limit,
        )

    async def file_info(self, path: str, *, include_sha256: bool) -> FileEntry:
        target = self.resolve_path(path, create_parent=False)
        if not target.exists():
            raise FileNotFoundError(path)
        return self._entry(target, include_sha256=include_sha256)

    async def file_read_text(
        self,
        path: str,
        *,
        offset: int,
        max_chars: int,
    ) -> FileText:
        target = self.resolve_path(path, create_parent=False)
        if not target.is_file():
            raise FileNotFoundError(path)
        content = target.read_text(encoding="utf-8")
        start = max(0, offset)
        excerpt = content[start : start + max_chars]
        return FileText(
            self._relative(target),
            excerpt,
            start,
            start + len(excerpt),
            len(content),
        )

    async def file_write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool,
    ) -> FileMutation:
        target = self.resolve_path(path)
        if target.exists() and not overwrite:
            raise FileExistsError(path)
        target.write_text(content, encoding="utf-8")
        return FileMutation(self._relative(target), len(content), state="written")

    async def file_append_text(self, path: str, content: str) -> FileMutation:
        target = self.resolve_path(path)
        with target.open("a", encoding="utf-8") as output:
            output.write(content)
        return FileMutation(self._relative(target), len(content), state="appended")

    async def file_copy(self, source: str, destination: str) -> FileMutation:
        src = self.resolve_path(source, create_parent=False)
        if not src.is_file():
            raise FileNotFoundError(source)
        dest = self.resolve_path(destination)
        shutil.copyfile(src, dest)
        return FileMutation(
            self._relative(dest),
            dest.stat().st_size,
            source=self._relative(src),
            state="copied",
        )

    async def file_move(self, source: str, destination: str) -> FileMutation:
        src = self.resolve_path(source, create_parent=False)
        if not src.is_file():
            raise FileNotFoundError(source)
        source_path = self._relative(src)
        dest = self.resolve_path(destination)
        shutil.move(str(src), str(dest))
        return FileMutation(
            self._relative(dest),
            dest.stat().st_size,
            source=source_path,
            state="moved",
        )

    async def file_delete(self, path: str) -> FileMutation:
        target = self.resolve_path(path, create_parent=False)
        if not target.is_file():
            raise FileNotFoundError(path)
        size = target.stat().st_size
        relative = self._relative(target)
        target.unlink()
        return FileMutation(relative, size, state="deleted")
