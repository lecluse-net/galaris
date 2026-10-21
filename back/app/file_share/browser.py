"""Read-only browsing through the same provider context as the selected agent."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from tempfile import TemporaryDirectory
from app.agent import AgentManagementScope

from app.console import ConsoleRunResource, resolve_ssh_connection
from app.skill import can_manage_skill_resources
from core.preview import PreviewFile, prepare_preview, thumbnails
from core.storage import validate_file_name

from .resource_contracts import ResourceContext, ResourceMutation, ResourceTransfer
from .resource_service import materialize_resource, resource_info, resource_move, resource_delete
from .resource_uri import NATIVE_RESOURCE_SCHEMES, parse_resource_uri


async def browser_rename(ctx: ResourceContext, uri: str, name: str) -> ResourceTransfer:
    """Rename within the canonical parent; never accept a client-supplied destination."""
    name = validate_file_name(name)
    source = parse_resource_uri(uri)
    if source.scheme in NATIVE_RESOURCE_SCHEMES and source.scheme != "console":
        raise PermissionError("Use the owning domain to rename this resource")
    descriptor = await resource_info(ctx, uri)
    reference = parse_resource_uri(descriptor.uri)
    if "move" not in descriptor.capabilities or not reference.locator.strip("/."):
        raise PermissionError("This resource cannot be renamed")
    parent = reference.locator.rstrip("/").rpartition("/")[0]
    destination = f"{reference.scheme}://{parent + '/' if parent else ''}{quote(name, safe='')}"
    result = await resource_move(ctx, reference, destination, overwrite=False, exact_destination=True)
    if descriptor.is_collection:
        result.uri = result.uri.rstrip("/") + "/"
    return result


async def browser_delete(ctx: ResourceContext, uri: str, *, recursive: bool) -> ResourceMutation:
    source = parse_resource_uri(uri)
    document_attachment = source.scheme == "document" and len(source.segments) == 3 and source.segments[1] == "attachments"
    if source.scheme in NATIVE_RESOURCE_SCHEMES and source.scheme not in {"console", "file"} and not document_attachment:
        raise PermissionError("Use the owning domain to delete this resource")
    descriptor = await resource_info(ctx, uri)
    reference = parse_resource_uri(descriptor.uri)
    if "delete" not in descriptor.capabilities or not reference.locator.strip("/."):
        raise PermissionError("This resource cannot be deleted")
    if descriptor.is_collection != recursive:
        raise ValueError("Directory deletion requires explicit recursive confirmation")
    return await resource_delete(ctx, reference, recursive=recursive)


async def read_internal_attachment(uri: str, agent_id: int, scope: AgentManagementScope | None) -> dict[str, object]:
    async with asyncio.timeout(20), browser_context(agent_id, scope=scope) as ctx:
        descriptor = await resource_info(ctx, uri)
        if descriptor.is_collection or "read" not in descriptor.capabilities:
            raise ValueError("Select a readable resource, not a directory")
        return descriptor.model_dump(mode="json")


@asynccontextmanager
async def browser_context(agent_id: int, *, management: bool = False, scope: AgentManagementScope | None = None) -> AsyncGenerator[ResourceContext]:
    from app.agent import current_management_scope
    config = await resolve_ssh_connection(agent_id)
    console = ConsoleRunResource(config) if config is not None else None
    try:
        yield ResourceContext(agent_id=agent_id, runtime="internal", console_resource=console,
            skill_management=await can_manage_skill_resources(agent_id),
            management_scope=scope or (await current_management_scope() if management else None))
    finally:
        if console is not None:
            await console.close()


@asynccontextmanager
async def browser_content(ctx: ResourceContext, uri: str, *, preview: bool) -> AsyncGenerator[PreviewFile]:
    info = await resource_info(ctx, uri)
    if info.is_collection:
        raise IsADirectoryError(uri)
    with TemporaryDirectory(prefix="galaris-file-browser-") as temporary:
        path = Path(temporary) / "source"
        source = await materialize_resource(ctx, uri, path, max_bytes=512 * 1024**2)
        await resource_info(ctx, uri)
        file = PreviewFile(path=path, name=source.name, media_type=source.media_type)
        if preview:
            async with prepare_preview(file) as prepared:
                await resource_info(ctx, uri)
                yield prepared
        else:
            yield file


async def browser_thumbnail(ctx: ResourceContext, uri: str) -> bytes | None:
    from app.memory import render_file_thumbnail

    info = await resource_info(ctx, uri)
    if info.is_collection or (info.size is not None and info.size > 50 * 1024**2):
        return None
    version = info.model_dump_json(exclude={"indexing_status", "metadata", "capabilities"})
    key = f"file-browser:v1:{ctx.agent_id}:{hashlib.sha256(version.encode()).hexdigest()}"
    path = thumbnails.cache_path(key)
    async with thumbnails.generation(key):
        cached = await asyncio.to_thread(thumbnails.read, path)
        if cached is not None:
            return cached
        async with browser_content(ctx, uri, preview=False) as source:
            image = await render_file_thumbnail(source.path, source.name, source.media_type)
        current = await resource_info(ctx, uri)
        if current.model_dump_json(exclude={"indexing_status", "metadata", "capabilities"}) != version:
            raise ValueError("Resource changed")
        if image is not None:
            await asyncio.to_thread(thumbnails.write, path, image)
        return image
