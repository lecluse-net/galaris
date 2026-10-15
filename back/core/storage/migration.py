"""Resumable, offline moves with a durable inventory and a separate cleanup phase."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from core.util import complete_io

from .disk import DiskFileDriver, file_key, file_path, fingerprint, sync_directory
from .models import FileAlias, StoredFile
from .registry import register_file
from .identity import ensure_disk_identity


@dataclass(frozen=True)
class LegacyFile:
    kind: str
    uuid: str
    name: str
    media_type: str
    aliases: tuple[str, ...]

    @property
    def source(self) -> Path:
        identifier = UUID(self.uuid)
        if self.kind == "chat":
            root = Path(settings.GALARIS_INTERNAL_MESSENGER_ROOT).resolve()
            path = root / "attachments" / identifier.hex[:2] / identifier.hex
        elif self.kind == "document":
            root = Path(settings.GALARIS_MEMORY_ROOT).resolve()
            path = root / str(identifier)[:2] / str(identifier)
        else:
            raise ValueError("Unknown legacy file source")
        if not path.resolve().is_relative_to(root) or any(
            part.is_symlink() for part in (path, path.parent)
        ):
            raise ValueError("Legacy file path escapes its storage root")
        return path


def manifest_path() -> Path:
    return Path(settings.GALARIS_FILE_ROOT) / ".migration" / "internal-files.json"


def _read_manifest() -> dict[str, dict[str, object]]:
    path = manifest_path()
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError("Invalid file migration manifest")
    raw: object = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Invalid file migration manifest")
    payload = cast(dict[str, object], raw)
    if payload.get("version") != 1 or not isinstance(payload.get("files"), dict):
        raise ValueError("Invalid file migration manifest")
    return cast(dict[str, dict[str, object]], payload["files"])


def _inventory(sources: list[LegacyFile]) -> dict[str, dict[str, object]]:
    previous = _read_manifest()
    result: dict[str, dict[str, object]] = {}
    identities: dict[str, tuple[int, str]] = {}
    for source in sources:
        key = f"{source.kind}:{source.uuid}"
        old = previous.get(key)
        path = source.source
        if path.exists():
            size, digest = fingerprint(path)
        elif old is not None:
            size, digest = fingerprint(file_path(UUID(source.uuid)))
        else:
            raise FileNotFoundError("A referenced internal attachment is missing; migration stopped")
        if old is not None and (old["size"], old["sha256"]) != (size, digest):
            raise ValueError("Legacy file differs from the durable migration manifest")
        identity = identities.setdefault(source.uuid, (size, digest))
        if identity != (size, digest):
            raise ValueError("Legacy UUID collision; no source has been removed")
        result[key] = {**asdict(source), "size": size, "sha256": digest}
    if previous and result != previous:
        # Normalize tuples to JSON arrays before comparing. A frozen inventory may
        # only be resumed with the same domain references, never silently replaced.
        normalized = json.loads(json.dumps(result))
        if normalized != previous:
            raise ValueError("Legacy file inventory changed; stop writers before retrying")
    return result


def _persist_manifest(entries: dict[str, dict[str, object]]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("Invalid migration manifest directory")
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".part")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"version": 1, "files": entries}, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
        sync_directory(path.parent.parent)
    finally:
        temporary.unlink(missing_ok=True)


async def transfer_legacy_files(session: AsyncSession, sources: list[LegacyFile]) -> None:
    await ensure_disk_identity(session)
    entries = await complete_io(_inventory, sources)
    # All sources and UUID collisions are validated before the first transfer.
    await complete_io(_persist_manifest, entries)
    driver = DiskFileDriver()
    for source in sources:
        entry = entries[f"{source.kind}:{source.uuid}"]
        size, digest = int(str(entry["size"])), str(entry["sha256"])
        await complete_io(driver.publish, source.source, file_key(UUID(source.uuid)), size=size, sha256=digest)
        for alias in source.aliases:
            await register_file(UUID(source.uuid), name=source.name, media_type=source.media_type, alias=alias, session=session)
    # Caller owns the database transaction. Sources remain untouched until a
    # subsequent DbAdmin phase has observed the committed registry.


async def legacy_files_verified(session: AsyncSession, sources: list[LegacyFile]) -> bool:
    await ensure_disk_identity(session)
    if not sources:
        return True
    entries = await complete_io(_inventory, sources)
    if not manifest_path().is_file():
        return False
    for source in sources:
        record = await session.scalar(select(StoredFile).where(StoredFile.id == UUID(source.uuid)))
        entry = entries[f"{source.kind}:{source.uuid}"]
        if record is None or (record.size_bytes, record.sha256, record.backend, record.storage_key) != (
            entry["size"], entry["sha256"], "disk", file_key(UUID(source.uuid)),
        ):
            return False
        if not file_path(record.id).exists():
            return False
        if await complete_io(fingerprint, file_path(record.id)) != (record.size_bytes, record.sha256):
            raise ValueError("Migrated file failed integrity verification")
        for alias in source.aliases:
            if await session.scalar(select(FileAlias.file_id).where(FileAlias.uri == alias)) != record.id:
                return False
    return True


async def cleanup_legacy_files(session: AsyncSession, sources: list[LegacyFile]) -> None:
    if not await legacy_files_verified(session, sources):
        raise ValueError("File migration registry is incomplete; all sources retained")
    # Verify the complete inventory before deleting even one source.
    for source in sources:
        def remove(legacy: LegacyFile = source) -> None:
            path = legacy.source
            if path.exists():
                if fingerprint(path) != fingerprint(file_path(UUID(legacy.uuid))):
                    raise ValueError("Legacy source changed before cleanup")
                path.unlink()
                sync_directory(path.parent)

        await complete_io(remove)
