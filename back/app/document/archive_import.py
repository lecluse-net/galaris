"""Bounded ZIP expansion without filesystem extraction or durable side effects."""

from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
import json
import mimetypes
import stat
from typing import TypedDict
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED
from zlib import error as ZlibError

from core.params import runtime_settings
from .content_limits import validate_document_size


class ArchiveFile(TypedDict):
    key: str
    path: str
    media_type: str


class ArchiveManifest(TypedDict):
    directories: list[str]
    files: list[ArchiveFile]


@dataclass(frozen=True)
class ExpandedArchive:
    source: bytes
    entries: tuple[ZipInfo, ...]
    manifest: ArchiveManifest
    boundary: str


def prepare_archive(content: bytes) -> ExpandedArchive:
    validate_document_size(content)
    limit = runtime_settings.MEMORY_RESOURCE_MAX_BYTES
    entries: list[ZipInfo] = []
    files: list[ArchiveFile] = []
    directories: set[str] = set()
    paths: set[str] = set()
    try:
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 2000:
                raise ValueError("ZIP archive exceeds the 2000-entry limit")
            total = 0
            for entry in archive.infolist():
                name = entry.orig_filename.replace("\\", "/")
                path = name.removesuffix("/")
                parts = path.split("/")
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if (not path or len(parts) > 32 or any(part in {"", ".", ".."} for part in parts)
                    or ":" in parts[0] or any(ord(char) < 32 or ord(char) == 127 for char in name)
                    or mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or mode == stat.S_IFDIR and not name.endswith("/")):
                    raise ValueError("ZIP archive contains an unsafe path or special file")
                if path in paths:
                    raise ValueError("ZIP archive contains duplicate paths")
                paths.add(path)
                folder_parts = parts if name.endswith("/") else parts[:-1]
                if any(len(part) > 100 or part != part.strip() for part in folder_parts):
                    raise ValueError("ZIP directory names must fit the document folder names")
                for depth in range(1, len(folder_parts) + 1):
                    directories.add("/".join(folder_parts[:depth]))
                if name.endswith("/"):
                    continue
                if entry.flag_bits & 1 or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                    raise ValueError("Encrypted ZIP files or this compression method are not supported")
                total += entry.file_size
                if total > limit:
                    raise ValueError("Expanded ZIP exceeds the configured resource quota")
                entries.append(entry)
                files.append({"key": f"entry{len(files)}", "path": path,
                              "media_type": mimetypes.guess_type(parts[-1])[0] or "application/octet-stream"})
            if directories.intersection(file["path"] for file in files):
                raise ValueError("ZIP archive has conflicting file and directory paths")
            if len(directories) + len(files) > 2000:
                raise ValueError("Expanded ZIP exceeds the 2000-entry limit")
            # Verify CRC and actual sizes before returning any body or creating a folder.
            actual = 0
            for entry in entries:
                with archive.open(entry) as source:
                    while chunk := source.read(1024 * 1024):
                        actual += len(chunk)
                        if actual > limit:
                            raise ValueError("Expanded ZIP exceeds the configured resource quota")
    except (BadZipFile, NotImplementedError, RuntimeError, ZlibError, EOFError) as exc:
        raise ValueError("Invalid or unsupported ZIP archive") from exc
    manifest: ArchiveManifest = {"directories": sorted(directories, key=lambda path: (path.count("/"), path)), "files": files}
    return ExpandedArchive(content, tuple(entries), manifest, uuid4().hex)


def archive_parts(prepared: ExpandedArchive) -> Iterator[bytes]:
    boundary = prepared.boundary
    yield (f'--{boundary}\r\nContent-Disposition: form-data; name="manifest"\r\n'
           'Content-Type: application/json\r\n\r\n').encode()
    yield json.dumps(prepared.manifest, ensure_ascii=False).encode()
    yield b"\r\n"
    with ZipFile(BytesIO(prepared.source)) as archive:
        for entry, file in zip(prepared.entries, prepared.manifest["files"], strict=True):
            key = file["key"]
            yield (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{key}"\r\n'
                   f'Content-Type: {file["media_type"]}\r\n\r\n').encode()
            with archive.open(entry) as source:
                while chunk := source.read(1024 * 1024):
                    yield chunk
            yield b"\r\n"
    yield f"--{boundary}--\r\n".encode()
