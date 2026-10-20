"""Authorize managed files through their live domain references."""

import mimetypes
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi import UploadFile

from sqlalchemy import or_, select

from core.database import get_db
from core.storage import FileAlias, StoredFile, validate_file_name
from core.storage import DiskFileDriver, file_key, fingerprint, register_file
from core.storage import ensure_disk_identity
from core.params import runtime_settings
from core.util import complete_io

from .resource_contracts import ResourceContext, ResourceDescriptor, ResourceListing
from .models import ManagedFileOwner


_DOMAIN_FILE_PREFIXES = ("document://", "data://", "chat://", "galaris://processes/runs/")
_LIST_SCAN_LIMIT = 500


async def _can_read_file(ctx: ResourceContext, owner: int | None, aliases: Iterable[str]) -> bool:
    from .resource_service import resource_info
    from app.memory import MemoryNotFoundError, MemoryPermissionError

    if owner == ctx.agent_id:
        return True
    for alias in aliases:
        # Only local domain references can grant access. Never resolve an external URI here.
        if not alias.startswith(_DOMAIN_FILE_PREFIXES):
            continue
        try:
            await resource_info(ctx, alias)
        except (PermissionError, FileNotFoundError, ValueError, MemoryNotFoundError, MemoryPermissionError):
            continue
        return True
    return False


async def _can_rename_file(ctx: ResourceContext, owner: int | None, aliases: Iterable[str]) -> bool:
    from .resource_service import resource_info
    from app.memory import MemoryNotFoundError, MemoryPermissionError

    if owner == ctx.agent_id:
        return True
    for alias in aliases:
        if not alias.startswith("document://"):
            continue
        try:
            if "delete" in (await resource_info(ctx, alias)).capabilities:
                return True
        except (PermissionError, FileNotFoundError, ValueError, MemoryNotFoundError, MemoryPermissionError):
            continue
    return False


def _descriptor(record: StoredFile, *, can_rename: bool) -> ResourceDescriptor:
    if record.backend != "disk":
        raise ValueError("Unsupported managed file storage backend")
    return ResourceDescriptor(
        uri=f"file://{record.id}", name=record.name, media_type=record.media_type,
        size=record.size_bytes, checksum=record.sha256, capabilities=["info", "read", "copy"],
        metadata={"can_rename": can_rename},
    )


async def managed_file_info(ctx: ResourceContext, file_id: UUID) -> ResourceDescriptor:
    db = get_db()
    record = await db.get(StoredFile, file_id)
    if record is None:
        raise FileNotFoundError("Managed file unavailable")
    owner = await db.scalar(select(ManagedFileOwner.agent_id).where(ManagedFileOwner.file_id == file_id))
    aliases = list(await db.scalars(select(FileAlias.uri).where(FileAlias.file_id == file_id).order_by(FileAlias.uri)))
    if not await _can_read_file(ctx, owner, aliases):
        raise PermissionError("Managed file unavailable")
    return _descriptor(record, can_rename=await _can_rename_file(ctx, owner, aliases))


async def list_managed_files(ctx: ResourceContext, *, limit: int, cursor: str | None, name_query: str | None = None) -> ResourceListing:
    """List owned files and attachments readable through a live domain reference."""
    domain_reference = select(FileAlias.id).where(
        FileAlias.file_id == StoredFile.id,
        or_(*(FileAlias.uri.startswith(prefix) for prefix in _DOMAIN_FILE_PREFIXES)),
    ).exists()
    query = select(StoredFile, ManagedFileOwner.agent_id).outerjoin(
        ManagedFileOwner, ManagedFileOwner.file_id == StoredFile.id,
    ).where(StoredFile.backend == "disk", or_(ManagedFileOwner.agent_id == ctx.agent_id, domain_reference))
    if name_query:
        escaped = name_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(StoredFile.name.ilike(f"%{escaped}%", escape="\\"))
    if cursor:
        query = query.where(StoredFile.id > UUID(cursor))
    db = get_db()
    records = (await db.execute(query.order_by(StoredFile.id).limit(_LIST_SCAN_LIMIT + 1))).all()
    candidates = records[:_LIST_SCAN_LIMIT]
    aliases: dict[UUID, list[str]] = {}
    if candidates:
        for file_id, uri in await db.execute(select(FileAlias.file_id, FileAlias.uri).where(
            FileAlias.file_id.in_([record.id for record, _owner in candidates]),
        ).order_by(FileAlias.uri)):
            aliases.setdefault(file_id, []).append(uri)
    entries: list[ResourceDescriptor] = []
    for record, owner in candidates:
        if not await _can_read_file(ctx, owner, aliases.get(record.id, ())):
            continue
        if len(entries) == limit:
            return ResourceListing(uri="file://", entries=entries, truncated=True,
                next_cursor=entries[-1].uri.removeprefix("file://"))
        entries.append(_descriptor(record, can_rename=await _can_rename_file(ctx, owner, aliases.get(record.id, ()))))
    # Bound authorization work per request, even when an entire batch is denied.
    more = len(records) > _LIST_SCAN_LIMIT
    return ResourceListing(uri="file://", entries=entries, truncated=more,
        next_cursor=str(candidates[-1][0].id) if more else None)


async def upload_managed_file(ctx: ResourceContext, upload: UploadFile) -> ResourceDescriptor:
    """Stream an independent upload, private to its owning agent."""
    db = get_db()
    await ensure_disk_identity(db)
    name = Path((upload.filename or "file").replace("\\", "/")).name.strip()[:512] or "file"
    media_type = (upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream").split(";", 1)[0][:255]
    limit = runtime_settings.MEMORY_RESOURCE_MAX_BYTES
    if upload.size is not None and upload.size > limit:
        raise ValueError("Managed file exceeds its upload limit")
    size = 0
    with TemporaryDirectory(prefix=".upload-", dir=DiskFileDriver().root) as directory:
        source = Path(directory) / "upload"
        with source.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Managed file exceeds its upload limit")
                await complete_io(output.write, chunk)
        return await persist_managed_file(ctx, source, name=name, media_type=media_type)


async def persist_managed_file(ctx: ResourceContext, source: Path, *, name: str, media_type: str) -> ResourceDescriptor:
    """Register one bounded, server-owned staging path as a private file."""
    db = get_db()
    await ensure_disk_identity(db)
    measured, digest = await complete_io(fingerprint, source)
    if measured > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
        raise ValueError("Managed file exceeds its upload limit")
    file_id = uuid4()
    name = Path(name.replace("\\", "/")).name.strip()[:512] or str(file_id)
    await complete_io(DiskFileDriver().publish, source, file_key(file_id), size=measured, sha256=digest)
    await register_file(file_id, name=name, media_type=media_type,
        alias=f"agent-file://{ctx.agent_id}/{file_id}")
    db.add(ManagedFileOwner(file_id=file_id, agent_id=ctx.agent_id))
    await db.flush()
    await db.commit()
    return await managed_file_info(ctx, file_id)


async def rename_managed_file(ctx: ResourceContext, file_id: UUID, name: str) -> ResourceDescriptor:
    name = validate_file_name(name)
    db = get_db()
    owner = await db.scalar(select(ManagedFileOwner.agent_id).where(ManagedFileOwner.file_id == file_id))
    if owner != ctx.agent_id:
        from app.memory import MemoryNotFoundError, MemoryPermissionError, rename_document_attachment

        aliases = list(await db.scalars(select(FileAlias.uri).where(FileAlias.file_id == file_id)))
        for alias in aliases:
            parts = alias.removeprefix("document://").split("/")
            if not alias.startswith("document://") or len(parts) != 3 or parts[1] != "attachments":
                continue
            try:
                await rename_document_attachment(UUID(parts[0]), file_id, actor_agent_id=ctx.agent_id, name=name)
                return await managed_file_info(ctx, file_id)
            except (MemoryNotFoundError, MemoryPermissionError):
                continue
        raise PermissionError("Managed file rename denied")
    record = await db.get(StoredFile, file_id)
    if record is None:
        raise FileNotFoundError("Managed file unavailable")
    record.name = name
    await db.commit()
    return await managed_file_info(ctx, file_id)


async def managed_file_thumbnail(ctx: ResourceContext, file_id: UUID) -> bytes | None:
    from core.preview import thumbnails
    from core.storage import file_path
    from core.util import complete_io
    from app.memory import render_file_thumbnail

    descriptor = await managed_file_info(ctx, file_id)
    async with thumbnails.generation(descriptor.uri):
        path = thumbnails.cache_path(descriptor.uri)
        cached = await complete_io(thumbnails.read, path)
        if cached is not None:
            return cached
        content = await render_file_thumbnail(file_path(file_id), descriptor.name, descriptor.media_type)
        if content is not None and len(content) <= thumbnails.MAX_BYTES:
            await managed_file_info(ctx, file_id)
            await complete_io(thumbnails.write, path, content)
        return content
