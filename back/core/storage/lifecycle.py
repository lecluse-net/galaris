"""Retire references transactionally; purge committed tombstones with crash recovery."""

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.util import complete_io

from .disk import DiskFileDriver, fingerprint, sync_directory
from .identity import ensure_disk_identity
from .models import FileAlias, StoredFile


async def retire_file_references(prefix: str, *, session: AsyncSession | None = None) -> list[UUID]:
    """Remove one domain's references in its deletion transaction, without touching bytes.

    Other domain, owner and archive references keep the file alive. Registration
    uses the same volume transaction lock and refuses to resurrect tombstones.
    """
    if not prefix.endswith("/") or not prefix.partition("://")[2].strip("/"):
        raise ValueError("File reference retirement requires an explicit domain scope")
    db = session if session is not None else get_db()
    await ensure_disk_identity(db)
    identifiers = list(await db.scalars(select(FileAlias.file_id).where(
        FileAlias.uri.startswith(prefix, autoescape=True),
    ).distinct()))
    await db.execute(delete(FileAlias).where(FileAlias.uri.startswith(prefix, autoescape=True)))
    retired: list[UUID] = []
    for identifier in sorted(identifiers):
        if await db.scalar(select(FileAlias.id).where(FileAlias.file_id == identifier).limit(1)) is not None:
            continue
        record = await db.get(StoredFile, identifier)
        if record is not None:
            record.soft_delete()
            retired.append(identifier)
    await db.flush()
    return retired


async def purge_retired_file(file_id: UUID, *, session: AsyncSession | None = None) -> bool:
    """Purge only a retired file. The caller must first commit its retirement.

    The permanent tombstone prevents re-registration between SQL commit and
    unlink. A crash after unlink is recoverable: the next pass records completion.
    """
    db = session if session is not None else get_db()
    await ensure_disk_identity(db)
    record = await db.scalar(select(StoredFile).where(StoredFile.id == file_id)
        .execution_options(include_historized=True).with_for_update())
    if record is None or record.deleted_at is None or record.purged_at is not None:
        return False
    if await db.scalar(select(FileAlias.id).where(FileAlias.file_id == file_id).limit(1)) is not None:
        raise ValueError("A referenced managed file cannot be purged")
    if record.backend != "disk":
        raise ValueError("Unsupported managed file storage backend")
    path = DiskFileDriver().path(record.storage_key)

    def remove() -> bool:
        if not path.exists():
            # An interrupted unlink may still need its directory entry synced.
            if path.parent.is_dir():
                sync_directory(path.parent)
            return False
        if fingerprint(path) != (record.size_bytes, record.sha256):
            raise ValueError("Retired managed file failed integrity verification")
        path.unlink()
        sync_directory(path.parent)
        return True

    removed = await complete_io(remove)
    record.purged_at = datetime.now(timezone.utc)
    await db.flush()
    return removed


async def discard_unregistered_file(file_id: UUID) -> bool:
    """Clean up a failed, unpublished upload; registered bytes are never discarded."""
    db = get_db()
    await ensure_disk_identity(db)
    record = await db.scalar(select(StoredFile.id).where(StoredFile.id == file_id)
        .execution_options(include_historized=True))
    if record is not None:
        return False
    from .disk import file_key

    path = DiskFileDriver().path(file_key(file_id))

    def remove() -> bool:
        if not path.is_file():
            return False
        path.unlink()
        sync_directory(path.parent)
        return True

    return await complete_io(remove)


async def resume_file_purges(session: AsyncSession) -> None:
    """Resume pending purges in bounded pages; completed rows leave the partial index."""
    cursor: UUID | None = None
    while True:
        query = select(StoredFile.id).where(StoredFile.deleted_at.is_not(None), StoredFile.purged_at.is_(None))
        if cursor is not None:
            query = query.where(StoredFile.id > cursor)
        identifiers = list(await session.scalars(query.order_by(StoredFile.id).limit(500)
            .execution_options(include_historized=True)))
        if not identifiers:
            return
        for identifier in identifiers:
            try:
                await purge_retired_file(identifier, session=session)
            except (OSError, ValueError) as exc:
                logger.error("Managed file purge deferred: file={} error={}", identifier, exc)
        await session.commit()
        cursor = identifiers[-1]
