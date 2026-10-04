"""Source-authorized previews of live locations of an agent's Memory file."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy import select
from app.connection import Connection
from app.tools import ToolModel
from app.memory import render_file_thumbnail
from core.database import get_db
from core.preview import PreviewFile, prepare_preview, thumbnails
from .catalogue import live_catalogue_binding, descriptor_version
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext, ResourceDescriptor
from .resource_observation import suspend_observations
from .resource_service import materialize_resource, resource_info


class CatalogueResource(BaseModel):
    id: UUID
    uri: str
    name: str
    media_type: str
    size_bytes: int


async def resources(item_id: UUID, agent_id: int, *, limit: int = 500) -> list[CatalogueResource]:
    entries = await get_db().scalars(select(FileCatalogEntry).join(Connection, Connection.id == FileCatalogEntry.connection_id)
        .join(ToolModel, ToolModel.id == Connection.tool_id).where(
            FileCatalogEntry.memory_item_id == item_id, FileCatalogEntry.agent_id == agent_id,
            FileCatalogEntry.present.is_(True), live_catalogue_binding(),
        ).order_by(FileCatalogEntry.uri).limit(limit))
    result: list[CatalogueResource] = []
    for entry in entries:
        info = ResourceDescriptor.model_validate(entry.descriptor)
        if not info.is_collection:
            result.append(CatalogueResource(id=entry.id, uri=entry.uri, name=info.name,
                media_type=info.media_type, size_bytes=info.size or 0))
    return result


async def authorized_resource(item_id: UUID, agent_id: int, entry_id: UUID) -> tuple[ResourceContext, ResourceDescriptor]:
    entry = await get_db().scalar(select(FileCatalogEntry).join(Connection, Connection.id == FileCatalogEntry.connection_id)
        .join(ToolModel, ToolModel.id == Connection.tool_id).where(
            FileCatalogEntry.id == entry_id, FileCatalogEntry.memory_item_id == item_id,
            FileCatalogEntry.agent_id == agent_id, FileCatalogEntry.present.is_(True), live_catalogue_binding(),
        ).execution_options(populate_existing=True))
    if entry is None:
        raise PermissionError("Resource is not a current location of this agent's Memory item")
    ctx = ResourceContext(agent_id=agent_id, runtime=entry.runtime)
    with suspend_observations():
        info = await resource_info(ctx, entry.uri)
    if info.is_collection:
        raise IsADirectoryError(entry.uri)
    if entry.file_sha256 and descriptor_version(info.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != entry.fingerprint_version:
        raise PermissionError("Resource changed since fingerprint acquisition")
    return ctx, info


@asynccontextmanager
async def content(item_id: UUID, agent_id: int, entry_id: UUID, *, preview: bool) -> AsyncGenerator[PreviewFile]:
    ctx, info = await authorized_resource(item_id, agent_id, entry_id)
    with TemporaryDirectory(prefix="memory-file-preview-") as temporary:
        path = Path(temporary) / "source"
        with suspend_observations():
            await materialize_resource(ctx, info.uri, path, max_bytes=512 * 1024**2)
        entry = await get_db().get(FileCatalogEntry, entry_id)
        if entry is not None and entry.file_sha256:
            def digest() -> str:
                with path.open('rb') as stream:
                    return hashlib.file_digest(stream, 'sha256').hexdigest()
            if await asyncio.to_thread(digest) != entry.file_sha256:
                raise PermissionError("Downloaded bytes no longer match this Memory file")
        await authorized_resource(item_id, agent_id, entry_id)
        source = PreviewFile(path=path, name=info.name, media_type=info.media_type)
        if preview:
            async with prepare_preview(source) as prepared:
                await authorized_resource(item_id, agent_id, entry_id)
                yield prepared
        else:
            yield source


async def thumbnail(item_id: UUID, agent_id: int, entry_id: UUID, *, cached_only: bool = False) -> bytes | None:
    _ctx, info = await authorized_resource(item_id, agent_id, entry_id)
    entry = await get_db().get(FileCatalogEntry, entry_id)
    if entry is None:
        raise PermissionError("Resource is no longer available")
    key = f"memory-file:v1:{agent_id}:{entry.binding_stamp}:{info.uri}:{entry.file_sha256}:{descriptor_version(info.model_dump())}"
    path = thumbnails.cache_path(key)

    async def assert_current() -> None:
        _ctx, current = await authorized_resource(item_id, agent_id, entry_id)
        current_key = f"memory-file:v1:{agent_id}:{entry.binding_stamp}:{current.uri}:{entry.file_sha256}:{descriptor_version(current.model_dump())}"
        if current_key != key:
            raise PermissionError("Resource changed while preparing its thumbnail")

    cached = await asyncio.to_thread(thumbnails.read, path)
    if cached is not None:
        await assert_current()
        return cached
    if cached_only:
        return None
    async with thumbnails.generation(key):
        await assert_current()
        cached = await asyncio.to_thread(thumbnails.read, path)
        if cached is not None:
            return cached
        async with content(item_id, agent_id, entry_id, preview=False) as source:
            image = await render_file_thumbnail(source.path, source.name, source.media_type)
            await assert_current()
            if image is not None:
                await asyncio.to_thread(thumbnails.write, path, image)
            return image
