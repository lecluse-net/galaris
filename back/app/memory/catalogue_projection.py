"""Transactional lexical projection of an external resource; no model invocation."""

import hashlib
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from html import escape, unescape
from typing import cast
from uuid import UUID

from core.database import get_db
from core.util import visible_text
from sqlalchemy import select, func, or_

from .models import MemoryItem, MemoryLink, MemoryRevision, MemorySource, MemoryContextEdge
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
    source_ref: str | None = None,
) -> UUID:
    """Stage one projection in the caller's transaction, preserving personal notes.

    The caller serializes the resource identity and owns commit/rollback.
    Descriptions and notes are escaped plain text; external bytes are never copied into Memory.
    """
    db = get_db()
    source_ref = source_ref or str(identity)
    title = title[:500] or uri[:500]
    assert_safe_text(notes)
    content = "".join(f"<p>{escape(part)}</p>" for part in (description, notes) if part).encode()
    digest = hashlib.sha256(content).hexdigest()
    item = await db.scalar(select(MemoryItem).where(MemoryItem.id == item_id).with_for_update().execution_options(populate_existing=True)) if item_id else None
    if item is not None and (item.managed_source_kind != "file_catalogue" or item.managed_source_ref != source_ref):
        raise ValueError("A catalogue entry cannot replace another managed source")
    if item is not None and item.metadata_.get("catalogue_manual_title"):
        title = item.title
    metadata: dict[str, object] = {
        **(dict(item.metadata_) if item is not None else {}),
        "resource_uri": uri, "catalogue_ref": str(identity), "catalogue_editable": True,
    }
    manual_content = item is not None and bool(item.metadata_.get("catalogue_manual_content"))
    search_text = "\n".join(part for part in (visible_text(content.decode()), uri) if part)
    if not manual_content:
        # Index the path without putting transport metadata in the editable body.
        metadata["html_text_version"] = 1
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
            managed_source_kind="file_catalogue", managed_source_ref=source_ref,
            content_hash=digest, size_bytes=len(content), search_text=search_text,
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
            item.search_text = search_text
        item.metadata_ = metadata
        item.node_kind = "directory" if directory else "file"
        item.revision += 1
        sources = await db.scalars(select(MemorySource).where(MemorySource.item_id == item.id))
        for source in sources:
            source.source_ref = uri[:1024]
    _record_revision(item)
    await db.flush()
    return item.id


async def reconcile_catalogue_descriptions() -> None:
    """Retire only generated descriptor paragraphs, preserving edits and history."""
    db = get_db()
    cursor: UUID | None = None
    async with catalogue_projection_write():
        while True:
            query = select(MemoryItem).where(
                MemoryItem.managed_source_kind == "file_catalogue",
                MemoryItem.node_kind.in_(("file", "directory")),
                MemoryItem.media_type == "text/html",
                MemoryItem.metadata_["catalogue_manual_content"].as_boolean().is_not(True),
                MemoryItem.search_text.startswith('{"uri":'),
            )
            if cursor is not None:
                query = query.where(MemoryItem.id > cursor)
            items = list(await db.scalars(query.order_by(MemoryItem.id).limit(250).with_for_update()))
            if not items:
                return
            cursor = items[-1].id
            for item in items:
                storage = get_storage(item.provider_code)
                body = (await storage.read(item.resource_id)).decode()
                paragraph, separator, remainder = body.partition("</p>")
                if not separator or not paragraph.startswith("<p>"):
                    continue
                try:
                    parsed: object = json.loads(unescape(paragraph[3:]))
                except ValueError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                descriptor = cast(dict[str, object], parsed)
                if set(descriptor) != {
                    "uri", "name", "media_type", "size", "modified_at", "revision", "checksum", "etag",
                } or not isinstance(descriptor.get("uri"), str):
                    continue
                content = remainder.encode() if visible_text(remainder).strip() else b""
                item.resource_id = await storage.create(content)
                if (created := _created.get()) is not None:
                    created.append(item.resource_id)
                item.content_hash = hashlib.sha256(content).hexdigest()
                item.size_bytes = len(content)
                locations = item.metadata_.get("resource_uris") or [item.metadata_.get("resource_uri", "")]
                item.search_text = "\n".join(part for part in (
                    visible_text(content.decode()), *locations,
                ) if part)
                item.revision += 1
                _record_revision(item)
            await db.flush()


def _record_revision(item: MemoryItem) -> None:
    get_db().add(MemoryRevision(
        item_id=item.id, revision=item.revision, provider_code=item.provider_code,
        resource_id=item.resource_id, content_hash=item.content_hash, content_type=item.content_type,
        media_type=item.media_type, content_profile_version=item.content_profile_version,
        title=item.title, filename=item.filename, keywords=list(item.keywords), metadata_=dict(item.metadata_),
    ))


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


async def detach_catalogue_parent_links(item_id: UUID, *, parent_ids: list[UUID] | None = None) -> None:
    """Retire only source-owned parent evidence invalidated by a proven move."""
    query = select(MemoryLink).where(
        MemoryLink.target_item_id == item_id, MemoryLink.relation_type == "parent_of",
        MemoryLink.projection_key == "file_catalogue",
    )
    if parent_ids is not None:
        query = query.where(MemoryLink.source_item_id.in_(parent_ids))
    links = await get_db().scalars(query)
    for link in links:
        link.soft_delete()
    await get_db().flush()


async def identify_catalogue_file(item_id: UUID, agent_id: int, sha256: str) -> UUID:
    """Serialize content identity per agent and preserve duplicate fiche evidence.

    Catalogue bindings are repointed by the caller in the same transaction. Old
    revisions remain available for audit; the duplicate is a retained tombstone.
    """
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError("Invalid file SHA-256")
    db = get_db()
    key = int.from_bytes(hashlib.sha256(f"file:{agent_id}:{sha256}".encode()).digest()[:8], signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(key)))
    item = await db.scalar(select(MemoryItem).where(MemoryItem.id == item_id).with_for_update())
    if item is None or item.owner_agent_id != agent_id or item.node_kind != "file":
        raise ValueError("File identity requires an agent-owned catalogue fiche")
    canonical = await db.scalar(select(MemoryItem).where(
        MemoryItem.owner_agent_id == agent_id, MemoryItem.file_sha256 == sha256,
    ).with_for_update().execution_options(include_historized=True))
    if canonical is None:
        if item.file_sha256 not in (None, sha256):
            raise ValueError("A file identity cannot change its content hash")
        item.file_sha256 = sha256
        await db.flush()
        return item.id
    canonical.deleted_at = None
    if canonical.id == item.id:
        return item.id
    canonical.keywords = sorted(set(canonical.keywords) | set(item.keywords))
    changed = False
    if item.metadata_.get("catalogue_manual_title") and not canonical.metadata_.get("catalogue_manual_title"):
        canonical.title = item.title
        canonical.metadata_ = {**canonical.metadata_, "catalogue_manual_title": True}
        changed = True
    if item.metadata_.get("catalogue_manual_content"):
        old = await get_storage(canonical.provider_code).read(canonical.resource_id)
        extra = await get_storage(item.provider_code).read(item.resource_id)
        if extra not in old:
            content = old + extra
            resource_id = await get_storage("native").create(content)
            if (created := _created.get()) is not None:
                created.append(resource_id)
            canonical.resource_id = resource_id
            canonical.content_hash = hashlib.sha256(content).hexdigest()
            canonical.size_bytes = len(content)
            canonical.search_text = visible_text(content.decode())
            canonical.metadata_ = {**canonical.metadata_, "catalogue_manual_content": True}
            changed = True
    if changed:
        canonical.revision += 1
        _record_revision(canonical)
    sources = list(await db.scalars(select(MemorySource).where(MemorySource.item_id.in_((canonical.id, item.id)))))
    known = {(row.source_kind, row.source_ref) for row in sources if row.item_id == canonical.id}
    for row in sources:
        if row.item_id != item.id:
            continue
        if (row.source_kind, row.source_ref) in known:
            await db.delete(row)
        else:
            row.item_id = canonical.id
            known.add((row.source_kind, row.source_ref))
    for link in await db.scalars(select(MemoryLink).where(or_(MemoryLink.source_item_id == item.id, MemoryLink.target_item_id == item.id))):
        source = canonical.id if link.source_item_id == item.id else link.source_item_id
        target = canonical.id if link.target_item_id == item.id else link.target_item_id
        existing = await db.scalar(select(MemoryLink).where(
            MemoryLink.id != link.id, MemoryLink.source_item_id == source,
            MemoryLink.target_item_id == target, MemoryLink.relation_type == link.relation_type,
        ).execution_options(include_historized=True))
        if source == target or existing is not None:
            if existing is not None:
                existing.deleted_at = None
            link.soft_delete()
        else:
            link.source_item_id, link.target_item_id = source, target
    for edge in await db.scalars(select(MemoryContextEdge).where(MemoryContextEdge.item_id == item.id)):
        existing = await db.scalar(select(MemoryContextEdge.id).where(
            MemoryContextEdge.context_node_id == edge.context_node_id,
            MemoryContextEdge.item_id == canonical.id, MemoryContextEdge.relation_type == edge.relation_type,
        ))
        if existing is not None:
            await db.delete(edge)
        else:
            edge.item_id = canonical.id
    item.metadata_ = {**item.metadata_, "merged_into": str(canonical.id)}
    item.file_sha256 = None
    item.soft_delete()
    await db.flush()
    return canonical.id


async def update_catalogue_file_locations(item_id: UUID, uris: list[str]) -> None:
    item = await get_db().get(MemoryItem, item_id)
    if item is None:
        return
    old_uris = set(item.metadata_.get("resource_uris", []))
    # Keep the editable body intact; retire only the location lines we added.
    lines = [line for line in item.search_text.splitlines() if line not in old_uris]
    locations = sorted(set(uris))
    item.search_text = "\n".join(lines + [uri for uri in locations if uri not in lines])
    item.metadata_ = {**item.metadata_, "resource_uris": locations}
    if uris:
        item.metadata_ = {**item.metadata_, "resource_uri": locations[0]}
    else:
        item.metadata_ = {key: value for key, value in item.metadata_.items() if key != "resource_uri"}
    await get_db().flush()


async def catalogue_file_summary(item_id: UUID, sha256: str, description: str) -> bool:
    db = get_db()
    item = await db.scalar(select(MemoryItem).where(MemoryItem.id == item_id).with_for_update())
    if item is None or item.file_sha256 != sha256 or item.metadata_.get("file_summary_sha256") == sha256:
        return False
    item.metadata_ = {**item.metadata_, "file_summary_sha256": sha256, "file_summary": description[:50000]}
    if not item.metadata_.get("catalogue_manual_content"):
        content = f"<p>{escape(description[:50000])}</p>".encode()
        item.resource_id = await get_storage("native").create(content)
        if (created := _created.get()) is not None:
            created.append(item.resource_id)
        item.content_hash = hashlib.sha256(content).hexdigest()
        item.size_bytes = len(content)
        item.search_text = visible_text(content.decode()) + "\n" + "\n".join(item.metadata_.get("resource_uris", []))
        item.revision += 1
        _record_revision(item)
    await db.flush()
    return True
