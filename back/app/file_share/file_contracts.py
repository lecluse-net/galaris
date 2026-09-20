"""Storage-independent contracts for canonical file providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class FileEntry:
    path: str
    is_dir: bool
    size: int | None = 0
    modified_at: str = ""
    mime_type: str = "application/octet-stream"
    sha256: str = ""


@dataclass(frozen=True)
class FileListing:
    path: str
    entries: tuple[FileEntry, ...]
    truncated: bool = False


@dataclass(frozen=True)
class FileText:
    path: str
    content: str
    start: int
    end: int
    total: int


@dataclass(frozen=True)
class FileMutation:
    path: str
    size: int = 0
    source: str = ""
    state: Literal["written", "identical", "appended", "copied", "moved", "deleted"] = "written"


@runtime_checkable
class FileResourceTransport(Protocol):
    def storage_path_label(self) -> str: ...

    async def normalize_resource_path(
        self,
        value: str,
        *,
        allow_root: bool = False,
    ) -> str: ...

    async def file_list(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int,
    ) -> FileListing: ...

    async def file_info(self, path: str, *, include_sha256: bool) -> FileEntry: ...

    async def file_read_text(
        self,
        path: str,
        *,
        offset: int,
        max_chars: int,
    ) -> FileText: ...

    async def file_write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool,
    ) -> FileMutation: ...

    async def file_append_text(self, path: str, content: str) -> FileMutation: ...

    async def file_copy(self, source: str, destination: str) -> FileMutation: ...

    async def file_move(self, source: str, destination: str) -> FileMutation: ...

    async def file_delete(self, path: str) -> FileMutation: ...
