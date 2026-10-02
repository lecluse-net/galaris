"""Transactional lexical projection of an external resource; no model invocation."""

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from html import escape
from uuid import UUID

from core.database import get_db
from core.util import visible_text
from sqlalchemy import select

from .models import MemoryItem, MemoryLink, MemoryRevision, MemorySource
from .safety import assert_safe_text
from .storage import get_storage

_created: ContextVar[list[str] | None] = ContextVar("catalogue_projection_resources", default=None)


@asynccontextmanager
async def catalogue_projection_write() -> AsyncGenerator[None]:
    """Remove new opaque payloads when their database transaction is rolled back."""
    resources: list[str] = []
    token = _created.set(resources)
    try:
        yield
    except BaseException:
        for resource_id in resources:
            await get_storage("native").delete(resource_id)
        raise
    finally:
        _created.reset(token)


async def project_catalogue_entry(
    *, identity: UUID, agent_id: int, item_id: UUID | None, title: str,
    uri: str, directory: bool, description: str, notes: str,
) -> UUID:
    """Stage one projection in the caller's transaction, preserving personal notes.

    The caller serializes the resource identity and owns commit/rollback. Source
    metadata is escaped plain text; external bytes are never copied into Memory.
    """
    db = get_db()
    title = title[:500] or uri[:500]
    assert_safe_text(notes)
    content = (f"<p>{escape(description)}</p><p>{escape(notes)}</p>").encode()
    digest = hashlib.sha256(content).hexdigest()
    item = await db.scalar(select(MemoryItem).where(MemoryItem.id == item_id).with_for_update().execution_options(populate_existing=True)) if item_id else None
    if item is not None and (item.managed_source_kind != "file_catalogue" or item.managed_source_ref != str(identity)):
        raise ValueError("A catalogue entry cannot replace another managed source")
    if item is not None and item.metadata_.get("catalogue_manual_title"):
        title = item.title
    metadata: dict[str, object] = {
        **(dict(item.metadata_) if item is not None else {}),
        "resource_uri": uri, "catalogue_ref": str(identity), "catalogue_editable": True,
    }
    manual_content = item is not None and bool(item.metadata_.get("catalogue_manual_content"))
    if manual_content and item is not None:
        digest = item.content_hash
    if item is not None and item.content_hash == digest and item.title == title and item.metadata_ == metadata:
        return item.id
    resource_id = item.resource_id if manual_content and item is not None else await get_storage("native").create(content)
    created = _created.get()
    if created is not None and not manual_content:
        created.append(resource_id)
    if item is None:
        item = MemoryItem(
            owner_agent_id=agent_id, title=title[:500] or uri[:500], memory_type="working",
            node_kind="directory" if directory else "file", provider_code="native",
            resource_id=resource_id, content_type="text", media_type="text/html", content_profile_version=1,
            visibility="private", source_managed=True, read_only=False, deletion_protected=True,
            managed_source_kind="file_catalogue", managed_source_ref=str(identity),
            content_hash=digest, size_bytes=len(content), search_text=visible_text(content.decode()),
            metadata_=metadata, keywords=[],
        )
        db.add(item)
        await db.flush()
        db.add(MemorySource(item_id=item.id, source_kind="resource", source_ref=uri[:1024]))
    else:
        if not item.metadata_.get("catalogue_editable"):
            item.read_only = False
        item.resource_id = resource_id
        item.title = title[:500] or uri[:500]
        item.content_hash = digest
        if not manual_content:
            item.size_bytes = len(content)
            item.search_text = visible_text(content.decode())
        item.metadata_ = metadata
        item.node_kind = "directory" if directory else "file"
        item.revision += 1
        sources = await db.scalars(select(MemorySource).where(MemorySource.item_id == item.id))
        for source in sources:
            source.source_ref = uri[:1024]
    db.add(MemoryRevision(
        item_id=item.id, revision=item.revision, provider_code=item.provider_code,
        resource_id=item.resource_id, content_hash=item.content_hash, content_type=item.content_type,
        media_type=item.media_type, content_profile_version=item.content_profile_version,
        title=item.title, filename=item.filename, keywords=list(item.keywords), metadata_=dict(item.metadata_),
    ))
    await db.flush()
    return item.id


async def link_catalogue_entries(parent_id: UUID, child_ids: list[UUID], *, agent_id: int) -> None:
    """Stage explicit direct membership only, without inferring opaque URI paths."""
    db = get_db()
    parent = await db.scalar(select(MemoryItem).where(
        MemoryItem.id == parent_id, MemoryItem.owner_agent_id == agent_id,
        MemoryItem.managed_source_kind == "file_catalogue", MemoryItem.node_kind == "directory",
    ))
    if parent is None:
        return
    for child_id in child_ids:
        if child_id == parent_id:
            continue
        child = await db.scalar(select(MemoryItem).where(
            MemoryItem.id == child_id, MemoryItem.owner_agent_id == agent_id,
            MemoryItem.managed_source_kind == "file_catalogue",
        ))
        if child is None:
            continue
        link = await db.scalar(select(MemoryLink).where(
            MemoryLink.source_item_id == parent_id, MemoryLink.target_item_id == child_id,
            MemoryLink.relation_type == "parent_of",
        ).execution_options(include_historized=True))
        if link is None:
            db.add(MemoryLink(source_item_id=parent_id, target_item_id=child_id,
                              relation_type="parent_of", created_by_agent_id=agent_id,
                              projection_key="file_catalogue", projection_version=1))
        else:
            link.deleted_at = None
    await db.flush()


async def detach_catalogue_parent_links(item_id: UUID) -> None:
    """Retire only source-owned parent evidence invalidated by a proven move."""
    links = await get_db().scalars(select(MemoryLink).where(
        MemoryLink.target_item_id == item_id, MemoryLink.relation_type == "parent_of",
        MemoryLink.projection_key == "file_catalogue",
    ))
    for link in links:
        link.soft_delete()
    await get_db().flush()
