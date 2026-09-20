"""Resource-storage registry and native filesystem implementation."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from core import settings
from core.params import runtime_settings
from core.util import complete_io

from .contracts import (
    ResourceNotFoundError,
    ResourceStorage,
    ResourceStorageError,
    ResourceTooLargeError,
)


class NativeFileStorage:
    """Store opaque resources below one configured, traversal-safe root."""

    code = "native"

    def __init__(self, root: str | Path, *, max_bytes: int | None = None) -> None:
        self._root = Path(root)
        self._max_bytes_override = max_bytes

    @property
    def _max_bytes(self) -> int:
        return (
            self._max_bytes_override
            if self._max_bytes_override is not None
            else runtime_settings.MEMORY_RESOURCE_MAX_BYTES
        )

    def _validate_content(self, content: bytes) -> None:
        if len(content) > self._max_bytes:
            raise ResourceTooLargeError(
                f"Resource contains {len(content)} bytes; limit is {self._max_bytes}."
            )

    def _path(self, resource_id: str) -> Path:
        try:
            normalized = str(UUID(str(resource_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ResourceNotFoundError("Invalid native resource identifier.") from exc
        root = self._root.resolve()
        candidate = (root / normalized[:2] / normalized).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ResourceStorageError("Resource path escapes the configured root.") from exc
        return candidate

    @staticmethod
    def _sync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".part", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            NativeFileStorage._sync_directory(path.parent)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    async def create(self, content: bytes) -> str:
        self._validate_content(content)
        resource_id = str(uuid4())
        path = self._path(resource_id)
        try:
            await complete_io(self._atomic_write, path, content)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return resource_id

    async def create_stream(
        self,
        chunks: AsyncIterator[bytes],
    ) -> tuple[str, int]:
        """Persist an async byte stream atomically without buffering it in memory."""

        resource_id = str(uuid4())
        path = self._path(resource_id)
        await complete_io(path.parent.mkdir, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".part", dir=path.parent
        )
        temporary = Path(temporary_name)
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ResourceTooLargeError(
                            f"Resource contains more than {self._max_bytes} bytes."
                        )
                    await complete_io(handle.write, chunk)
                await complete_io(handle.flush)
                await complete_io(os.fsync, handle.fileno())
            await complete_io(os.replace, temporary, path)
            await complete_io(self._sync_directory, path.parent)
            return resource_id, size
        except BaseException:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise

    async def path_for_read(self, resource_id: str) -> Path:
        """Return a validated native path for a response that streams the file."""

        path = self._path(resource_id)
        if not await asyncio.to_thread(path.is_file):
            raise ResourceNotFoundError(
                f"Native resource {resource_id!r} does not exist."
            )
        return path

    async def read(self, resource_id: str) -> bytes:
        path = self._path(resource_id)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ResourceNotFoundError(
                f"Native resource {resource_id!r} does not exist."
            ) from exc

    async def update(self, resource_id: str, content: bytes) -> None:
        self._validate_content(content)
        path = self._path(resource_id)
        if not await asyncio.to_thread(path.is_file):
            raise ResourceNotFoundError(
                f"Native resource {resource_id!r} does not exist."
            )
        await complete_io(self._atomic_write, path, content)

    async def delete(self, resource_id: str) -> bool:
        path = self._path(resource_id)

        def remove() -> bool:
            if not path.is_file():
                return False
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass
            return True

        return await asyncio.to_thread(remove)


_providers: dict[str, ResourceStorage] = {}


def register_storage(provider: ResourceStorage) -> None:
    """Register or deliberately replace one provider by its stable code."""

    code = provider.code.strip().lower()
    if not code:
        raise ValueError("A resource-storage provider requires a non-empty code.")
    _providers[code] = provider


def get_storage(code: str = "native") -> ResourceStorage:
    normalized = (code or "native").strip().lower()
    if normalized == "native" and normalized not in _providers:
        register_storage(NativeFileStorage(settings.GALARIS_MEMORY_ROOT))
    provider = _providers.get(normalized)
    if provider is None:
        raise ResourceStorageError(f"Unknown resource-storage provider: {normalized!r}.")
    return provider


def registered_storage_codes() -> tuple[str, ...]:
    get_storage("native")
    return tuple(sorted(_providers))


def reset_storage_registry() -> None:
    """Clear providers for isolated tests."""

    _providers.clear()


__all__ = [
    "NativeFileStorage",
    "get_storage",
    "register_storage",
    "registered_storage_codes",
]
