"""The local disk driver. Logical URIs never expose this driver's paths."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import UUID

from core.settings import settings


class FileDriver(Protocol):
    code: str

    def path(self, key: str) -> Path: ...

    def publish(self, source: Path, key: str, *, size: int, sha256: str) -> Path: ...


def file_key(file_id: UUID) -> str:
    return f"{file_id.hex[:2]}/{file_id.hex[2:4]}/{file_id}"


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fingerprint(path: Path) -> tuple[int, str]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("A managed file must be a regular file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


class DiskFileDriver:
    code = "disk"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root if root is not None else settings.GALARIS_FILE_ROOT).resolve()

    def path(self, key: str) -> Path:
        try:
            file_id = UUID(key.rsplit("/", 1)[-1])
        except ValueError as exc:
            raise ValueError("Invalid managed file key") from exc
        if key != file_key(file_id):
            raise ValueError("Invalid managed file key")
        candidate = self.root / key
        if not candidate.resolve().is_relative_to(self.root) or any(
            parent.is_symlink() for parent in (candidate, *candidate.parents) if parent != self.root
        ):
            raise ValueError("Managed file path escapes its root")
        return candidate

    def publish(self, source: Path, key: str, *, size: int, sha256: str) -> Path:
        """Publish verified bytes without overwriting an existing identity."""
        destination = self.path(key)
        expected = size, sha256
        if destination.exists():
            if fingerprint(destination) != expected:
                raise ValueError("Managed file destination conflicts with its manifest")
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        sync_directory(destination.parent.parent)
        sync_directory(self.root)
        descriptor, name = tempfile.mkstemp(prefix=".publish-", suffix=".part", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as incoming:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if fingerprint(temporary) != expected or fingerprint(source) != expected:
                raise ValueError("Managed file changed during transfer")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if fingerprint(destination) != expected:
                    raise ValueError("Managed file destination conflicts with its manifest") from None
            sync_directory(destination.parent)
            return destination
        finally:
            temporary.unlink(missing_ok=True)


def file_path(file_id: UUID) -> Path:
    return DiskFileDriver().path(file_key(file_id))
