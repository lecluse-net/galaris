"""Authorize managed files through their live domain references."""

import mimetypes
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi import UploadFile

from sqlalchemy import select

from core.database import get_db
from core.storage import FileAlias, StoredFile
from core.storage import DiskFileDriver, file_key, fingerprint, register_file
from core.storage import ensure_disk_identity
from core.params import runtime_settings
from core.util import complete_io

from .resource_contracts import ResourceContext, ResourceDescriptor
from .models import ManagedFileOwner


async def managed_file_info(ctx: ResourceContext, file_id: UUID) -> ResourceDescriptor:
    from .resource_service import resource_info
    from app.memory import MemoryNotFoundError, MemoryPermissionError

    db = get_db()
    record = await db.get(StoredFile, file_id)
    if record is None:
        raise FileNotFoundError("Managed file unavailable")
    owner = await db.scalar(select(ManagedFileOwner.agent_id).where(ManagedFileOwner.file_id == file_id))
    accessible = owner == ctx.agent_id
    aliases = await db.scalars(select(FileAlias.uri).where(FileAlias.file_id == file_id).order_by(FileAlias.uri))
    for alias in aliases:
        if accessible:
            break
        # Only local domain references can grant access. Never resolve an external URI here.
        if not alias.startswith(("document://", "data://", "chat://")):
            continue
        try:
            await resource_info(ctx, alias)
        except (PermissionError, FileNotFoundError, ValueError, MemoryNotFoundError, MemoryPermissionError):
            continue
        accessible = True
        break
    if accessible:
        if record.backend != "disk":
            raise ValueError("Unsupported managed file storage backend")
        return ResourceDescriptor(
            uri=f"file://{record.id}", name=record.name, media_type=record.media_type,
            size=record.size_bytes, checksum=record.sha256,
            capabilities=["info", "read", "copy"],
        )
    raise PermissionError("Managed file unavailable")


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
    db = get_db()
    owner = await db.scalar(select(ManagedFileOwner.agent_id).where(ManagedFileOwner.file_id == file_id))
    if owner != ctx.agent_id:
        raise PermissionError("Managed file rename denied")
    record = await db.get(StoredFile, file_id)
    if record is None:
        raise FileNotFoundError("Managed file unavailable")
    record.name = Path(name.replace("\\", "/")).name.strip()[:512]
    if not record.name:
        raise ValueError("A managed file requires a name")
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
