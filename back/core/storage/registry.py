"""Transactional registration; this module never grants access by UUID alone."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.util import complete_io
from core.user import get_current_user_id

from .disk import file_key, file_path, fingerprint
from .models import FileAlias, StoredFile
from .identity import ensure_disk_identity


async def register_file(
    file_id: UUID, *, name: str, media_type: str, alias: str | None = None,
    session: AsyncSession | None = None,
) -> StoredFile:
    db = session if session is not None else get_db()
    await ensure_disk_identity(db)
    size, digest = await complete_io(fingerprint, file_path(file_id))
    await db.execute(insert(StoredFile).values(
        id=file_id, name=name[:512], original_name=name[:512], media_type=media_type[:255],
        size_bytes=size, sha256=digest, backend="disk", storage_key=file_key(file_id),
        created_by=get_current_user_id(),
    ).on_conflict_do_nothing(index_elements=[StoredFile.id]))
    record = await db.scalar(select(StoredFile).where(StoredFile.id == file_id))
    if record is None or (record.backend, record.storage_key, record.size_bytes, record.sha256) != (
        "disk", file_key(file_id), size, digest,
    ):
        raise ValueError("Managed file identity conflicts with existing bytes")
    if alias is None:
        return record
    await db.execute(insert(FileAlias).values(uri=alias, file_id=file_id).on_conflict_do_nothing())
    linked = await db.scalar(select(FileAlias.file_id).where(FileAlias.uri == alias))
    if linked != file_id:
        raise ValueError("Managed file alias conflicts with an existing identity")
    return record
