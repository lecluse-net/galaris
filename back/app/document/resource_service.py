"""Canonical documentary persistence, revisions, ownership and live permissions."""
from __future__ import annotations
from .models import Document
import base64
import binascii
import hashlib
from collections.abc import Collection, Sequence
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import delete, select, update, exists, or_
from sqlalchemy.orm import defer, selectinload, raiseload
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm.attributes import set_committed_value
from loguru import logger
from app.share import ShareGrant
from app.agent import get_agent_record
from core.database import get_db
from core.i18n import tr
from core.storage import get_storage, prepare_content, resource_is_referenced
from core.user import HumanActor, get_user_record, UserModel
from .schemas import DocumentLibraryRequest, DocumentLibraryPage, DocumentOwnerOptions, DocumentSourceCreate
from core.util import archived_document_html, convert_to_html, visible_text, image_references, attachment_reference, complete_await
from .models import DocumentRevision, DocumentSummaryRevision, DocumentSource
from .schemas import DocumentItemCreate, DocumentUpdate, DocumentPayload, DocumentGrantUpdate, DocumentDeletionResult, DocumentDetail, DocumentContentRevisionPage, DocumentContentRevisionPublic, DocumentContentRevisionDetail, DocumentContentDiff, DocumentOwnerUpdate, DocumentFolderOption, DocumentGlobalAccessUpdate
from .contracts import DocumentAccess
from .access import effective_access, managed_item_agent_ids, readable_item_clause
from .content_diff import content_diff_hunks as _content_diff_hunks
from .document_apps import document_apps
from .document_types import validate_document_content
from .lifecycle import notify_document
from .item_projection import item_to_public
from .safety import assert_safe_text, assert_safe_value

class DocumentError(RuntimeError):
    """Base documentary error."""

class DocumentNotFoundError(DocumentError):
    """Absent or invisible document."""

class DocumentPermissionError(DocumentError):
    """Document access denied."""

class DocumentConflictError(DocumentError):
    """Concurrent edit or invalid document operation."""

async def _commit_with_conflict(message: str) -> None:
    """Commit an optimistic write and expose stale ORM state as a domain conflict."""

    db = get_db()
    try:
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        raise DocumentConflictError(message) from exc

def _assert_not_source_managed(item: Document, *, allow_catalogue: bool = False) -> None:
    if item.source_managed and not (allow_catalogue and item.managed_source_kind == "file_catalogue"):
        raise DocumentPermissionError(
            "This memory is generated from source data and can only be changed through that source."
        )

def _assert_not_deletion_protected(item: Document) -> None:
    if item.deletion_protected or (
        item.document_type == "process" and item.metadata_.get("process_code")
    ):
        raise DocumentPermissionError(
            "This document is owned by another Galaris resource and cannot be forgotten."
        )

def _is_goal_document(item: Document) -> bool:
    return item.metadata_.get("goal_document_kind") in {
        "description",
        "tracking",
    }

def decode_payload(payload: DocumentPayload) -> bytes:
    if payload.text is not None:
        return payload.text.encode("utf-8")
    assert payload.base64 is not None
    try:
        return base64.b64decode(payload.base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("The payload is not valid base64.") from exc

def encode_payload(content: bytes, *, content_type: str, media_type: str) -> DocumentPayload:
    textual = content_type == "text" or media_type.startswith("text/")
    if textual:
        try:
            return DocumentPayload(text=content.decode("utf-8"))
        except UnicodeDecodeError:
            pass
    return DocumentPayload(base64=base64.b64encode(content).decode("ascii"))

def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def _keywords(values: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()[:100]
        folded = value.casefold()
        if not value or folded in seen:
            continue
        normalized.append(value)
        seen.add(folded)
    return normalized[:50]

def _set_keywords(item: Document, values: Sequence[str]) -> bool:
    """Both document and synthesis editors write the node's shared metadata."""
    normalized = _keywords(values)
    if normalized == item.keywords:
        return False
    item.keywords = normalized
    return True

def _search_text(content: bytes, *, content_type: str, media_type: str) -> str:
    if content_type != "text" and not media_type.startswith("text/"):
        return ""
    decoded = content.decode("utf-8", errors="replace")
    return (
        visible_text(decoded) if content_type == "text" and media_type == "text/html" else decoded
    )[:2_000_000]

async def list_document_content_revisions(
    item_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
    limit: int = 50,
    offset: int = 0,
    before_revision: int | None = None,
) -> DocumentContentRevisionPage:
    """List only restorable document-content versions, newest first."""

    item = await _get_item_record(item_id, revisions=False)
    if item is None or item.node_kind != "document":
        raise DocumentNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id)
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(item_id):
        if before_revision is not None:
            raise ValueError("Bounded history is only available for native documents.")
        return DocumentContentRevisionPage.model_validate(await adapter.history(item_id, actor_agent_id, limit, offset))
    from .revision_queries import content_revision_page

    rows, total = await content_revision_page(item_id, limit=limit, offset=offset, before_revision=before_revision)
    return DocumentContentRevisionPage(
        items=[DocumentContentRevisionPublic.model_validate(entry) for entry in rows],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + limit < total,
    )

async def _document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> tuple[Document, DocumentRevision, bytes]:
    item = await _get_item_record(item_id, revisions=False)
    if item is None or item.node_kind != "document":
        raise DocumentNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id)
    from .revision_queries import content_revision

    entry = await content_revision(item_id, revision)
    if entry is None:
        raise DocumentNotFoundError("Document content revision not found.")
    content = await get_storage(entry.provider_code).read(entry.resource_id)
    return item, entry, content

async def get_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> DocumentContentRevisionDetail:
    """Read one immutable UTF-8 document-content version."""
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(item_id):
        state = await adapter.read(item_id, actor_agent_id, revision)
        return DocumentContentRevisionDetail(**state["revision_detail"], content=state["content"])

    _item, entry, content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    return DocumentContentRevisionDetail(
        **DocumentContentRevisionPublic.model_validate(entry).model_dump(),
        content=content.decode("utf-8"),
    )

async def diff_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    actor_agent_id: int | HumanActor,
) -> DocumentContentDiff:
    """Compare one stored content version with the current document text."""
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(item_id):
        previous = await adapter.read(item_id, actor_agent_id, revision)
        current = await adapter.read(item_id, actor_agent_id)
        hunks, additions, deletions = _content_diff_hunks(previous["content"], current["content"])
        return DocumentContentDiff(revision=revision, current_revision=current["revision"],
            additions=additions, deletions=deletions, hunks=hunks, structure_changed=False)

    item, entry, previous_content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    current_content = await get_storage(item.provider_code).read(item.resource_id)
    hunks, additions, deletions = _content_diff_hunks(
        visible_text(previous_content.decode("utf-8"))
        if entry.media_type == "text/html"
        else previous_content.decode("utf-8"),
        visible_text(current_content.decode("utf-8"))
        if item.media_type == "text/html"
        else current_content.decode("utf-8"),
    )
    return DocumentContentDiff(
        revision=revision,
        current_revision=item.revision,
        additions=additions,
        deletions=deletions,
        hunks=hunks,
        structure_changed=entry.content_hash != item.content_hash
        and (entry.media_type == "text/html" or item.media_type == "text/html"),
        previous_html=previous_content.decode("utf-8") if entry.media_type == "text/html" else None,
        current_html=current_content.decode("utf-8") if item.media_type == "text/html" else None,
    )

async def restore_document_content_revision(
    item_id: UUID,
    revision: int,
    *,
    expected_revision: int,
    actor_agent_id: int | HumanActor,
) -> Document:
    """Restore only editorial content while keeping current metadata and ACLs."""
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(item_id):
        await adapter.restore(item_id, actor_agent_id, revision, expected_revision)
        loaded = await _get_item_record(item_id)
        assert loaded is not None
        return loaded

    item, entry, content = await _document_content_revision(
        item_id,
        revision,
        actor_agent_id=actor_agent_id,
    )
    await assert_item_access(item, actor_agent_id, write=True)
    if expected_revision != item.revision:
        raise DocumentConflictError(
            f"Document revision conflict: expected {expected_revision}, "
            f"current revision is {item.revision}."
        )
    if entry.content_hash == item.content_hash:
        return item
    return await update_item(
        item_id,
        DocumentUpdate(
            expected_revision=expected_revision,
            payload=DocumentPayload(
                text=content.decode("utf-8") if item.document_type != "html" else convert_to_html(
                    archived_document_html(content.decode("utf-8"))
                    if entry.media_type == "text/html" and item.content_profile == "document"
                    else content.decode("utf-8"),
                    entry.media_type, profile=item.content_profile
                )
            ),
            media_type=item.media_type if item.document_type != "html" else "text/html",
        ),
        actor_agent_id=actor_agent_id,
        document_revision_author_agent_id=None,
    )

async def set_item_grant(
    item_id: UUID,
    agent_id: int,
    data: DocumentGrantUpdate,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
    include_revisions: bool = True,
) -> Document:
    from .sharing_inheritance import lock_sharing, prepare_own_sharing, finish_own_sharing
    await lock_sharing()
    item = await _get_item_record(item_id, revisions=include_revisions)
    if item is None:
        raise DocumentNotFoundError("Document not found.")
    if item.document_type == "dataset":
        from .dataset_port import dataset_compatibility
        if adapter := dataset_compatibility():
            await adapter.adopt(item.id)
            # The omitted actor is reserved for trusted engine/bootstrap callers.
            principal = actor_agent_id if actor_agent_id is not None else (item.owner_agent_id if item.owner_agent_id is not None else HumanActor(item.owner_user_id or 0))
            await adapter.grant(item.id, principal, "agent", agent_id, data.can_write)
            await get_db().refresh(item)
            return item
    _assert_not_source_managed(item)
    if item.node_kind != "document":
        raise DocumentPermissionError("Sharing belongs to documents; memories are private.")
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise DocumentConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    if agent_id == item.owner_agent_id:
        raise DocumentConflictError("The owner already has direct access to this memory.")
    await prepare_own_sharing(item)
    db = get_db()
    grant = await db.scalar(
        select(ShareGrant).where(
            ShareGrant.share_id == Document.share_for(item_id),
            ShareGrant.agent_id == agent_id,
        )
    )
    if grant is None:
        db.add(ShareGrant(share_id=Document.share_for(item_id), agent_id=agent_id, can_write=data.can_write))
    else:
        grant.can_write = data.can_write
    if item.visibility != "public":
        item.visibility = "shared"
    if item.node_kind == "document":
        # Grant rows are versioned independently; explicitly dirty the parent so
        # two concurrent sharing edits still contend on the document lock.
        item.lock_version += 1
    if item.node_kind != "document":
        item.revision += 1
        db.add(
            _revision_for(
                item,
                author_agent_id=actor_agent_id,
                task_id=actor_task_id,
            )
        )
    await finish_own_sharing(item)
    await _commit_with_conflict(
        "The document changed while sharing was being edited; reload and retry."
    )
    loaded = await _get_item_record(item_id, revisions=include_revisions)
    assert loaded is not None
    await _emit_document_event("update", loaded)
    await notify_document(loaded.id, "sharing")
    return loaded

async def has_document_grants(item_id: UUID) -> bool:
    return bool(await get_db().scalar(select(
        exists(select(ShareGrant.id).where(ShareGrant.share_id == Document.share_for(item_id))),
    )))

async def set_document_global_access(
    item_id: UUID,
    data: DocumentGlobalAccessUpdate,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
    include_revisions: bool = True,
) -> Document:
    """Set the durable public permission for authenticated humans and Agents."""
    from .sharing_inheritance import lock_sharing, prepare_own_sharing, finish_own_sharing
    await lock_sharing()
    item = await _get_item_record(item_id, revisions=include_revisions)
    if item is None:
        raise DocumentNotFoundError("Document not found.")
    _assert_not_source_managed(item)
    if item.node_kind != "document":
        raise DocumentConflictError("Global access is only available for documents.")
    if data.expected_revision != item.revision:
        raise DocumentConflictError(
            f"Document revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise DocumentConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    await prepare_own_sharing(item)
    has_grants = await has_document_grants(item_id)
    item.global_access = data.global_access
    item.group_access = 0
    item.visibility = "shared" if data.global_access > 0 or has_grants else "private"
    await finish_own_sharing(item)
    await commit_item_sharing(item)
    loaded = await _get_item_record(item_id, revisions=include_revisions)
    assert loaded is not None
    await _emit_document_event("update", loaded)
    await invalidate_document_views()
    await notify_document(loaded.id, "sharing")
    return loaded

async def get_item_owner_agent_id(item_id: UUID) -> int | None:
    """Resolve an active Document owner's Agent id for human API scoping."""

    return await get_db().scalar(select(Document.owner_agent_id).where(Document.id == item_id))

async def remove_item_grant(
    item_id: UUID,
    agent_id: int,
    *,
    actor_agent_id: int | None = None,
    actor_task_id: UUID | None = None,
    expected_lock_version: int | None = None,
    include_revisions: bool = True,
) -> Document:
    from .sharing_inheritance import lock_sharing, prepare_own_sharing, finish_own_sharing
    await lock_sharing()
    item = await _get_item_record(item_id, revisions=include_revisions)
    if item is None:
        raise DocumentNotFoundError("Document not found.")
    if item.document_type == "dataset":
        from .dataset_port import dataset_compatibility
        if adapter := dataset_compatibility():
            await adapter.adopt(item.id)
            principal = actor_agent_id if actor_agent_id is not None else (item.owner_agent_id if item.owner_agent_id is not None else HumanActor(item.owner_user_id or 0))
            await adapter.grant(item.id, principal, "agent", agent_id, None)
            await get_db().refresh(item)
            return item
    _assert_not_source_managed(item)
    if item.node_kind != "document":
        raise DocumentPermissionError("Sharing belongs to documents; memories are private.")
    if expected_lock_version is not None and expected_lock_version != item.lock_version:
        raise DocumentConflictError(
            "The document changed while sharing was being edited; reload and retry."
        )
    await prepare_own_sharing(item)
    db = get_db()
    grant = await db.scalar(
        select(ShareGrant).where(
            ShareGrant.share_id == Document.share_for(item_id),
            ShareGrant.agent_id == agent_id,
        )
    )
    if grant is not None:
        await db.delete(grant)
        await db.flush()
        remaining = await has_document_grants(item_id)
        if not remaining and item.global_access == 0 and item.group_access == 0 and item.visibility == "shared":
            item.visibility = "private"
        if item.node_kind != "document":
            item.revision += 1
            db.add(
                _revision_for(
                    item,
                    author_agent_id=actor_agent_id,
                    task_id=actor_task_id,
                )
            )
        else:
            # Deleting a grant may leave visibility unchanged, so make the
            # document row participate in optimistic concurrency explicitly.
            item.lock_version += 1
    await finish_own_sharing(item)
    await _commit_with_conflict(
        "The document changed while sharing was being edited; reload and retry."
    )
    loaded = await _get_item_record(item_id, revisions=include_revisions)
    assert loaded is not None
    if grant is not None:
        await _emit_document_event("update", loaded)
        await invalidate_document_views()
        await notify_document(loaded.id, "sharing")
    return loaded

async def managed_document_agent_ids(
    document_id: UUID,
    *,
    managed_agent_ids: Collection[int] | None,
) -> tuple[Document, tuple[int, ...], tuple[int, ...]]:
    """Load one document and resolve its effective managed-Agent access."""

    item = await _get_item_record(document_id, revisions=False, contents=False)
    if item is None or item.node_kind != "document":
        raise DocumentNotFoundError("Document not found.")
    readable_agent_ids, writable_agent_ids = await managed_item_agent_ids(
        item,
        managed_agent_ids,
    )
    if not readable_agent_ids:
        raise DocumentNotFoundError("Document not found.")
    return item, readable_agent_ids, writable_agent_ids

async def transfer_document_owner(
    document_id: UUID,
    data: DocumentOwnerUpdate,
    *,
    actor_agent_id: int | HumanActor,
    include_revisions: bool = True,
) -> Document:
    """Transfer a document while preserving the current editor's write access."""
    from .sharing_inheritance import lock_sharing, prepare_own_sharing, finish_own_sharing
    await lock_sharing()
    item = await _get_item_record(document_id, revisions=include_revisions)
    if item is None or item.node_kind != "document":
        raise DocumentNotFoundError("Document not found.")
    _assert_not_source_managed(item)
    await assert_item_access(item, actor_agent_id, write=True)
    if data.expected_revision != item.revision:
        raise DocumentConflictError(
            f"Document revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )

    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise DocumentConflictError(
            "The document changed while ownership was being edited; reload and retry."
        )

    unchanged = (
        data.kind == "agent" and item.owner_agent_id == data.id and item.owner_user_id is None
    ) or (data.kind == "user" and item.owner_user_id == data.id and item.owner_agent_id is None)
    if unchanged:
        return item
    if _is_goal_document(item):
        raise DocumentPermissionError(
            "The title, owner, and path of a Goal document are controlled by its Goal "
            "and cannot be changed directly."
        )

    if data.kind == "agent":
        if await get_agent_record(data.id) is None:
            raise ValueError("Agent owner not found.")
    else:
        owner_user = await get_user_record(data.id)
        if owner_user is None or not owner_user.is_active:
            raise ValueError("User owner not found.")

    await prepare_own_sharing(item)
    db = get_db()
    if data.kind == "agent":
        item.owner_agent_id = data.id
        item.owner_user_id = None
        await db.execute(
            delete(ShareGrant).where(
                ShareGrant.share_id == Document.share_for(document_id),
                ShareGrant.agent_id == data.id,
            )
        )
    else:
        item.owner_agent_id = None
        item.owner_user_id = data.id
        await db.execute(
            delete(ShareGrant).where(
                ShareGrant.share_id == item.share_id,
                ShareGrant.user_id == data.id,
            )
        )

    if isinstance(actor_agent_id, HumanActor):
        if data.kind != "user" or data.id != actor_agent_id.user_id:
            human_grant = await db.scalar(select(ShareGrant).where(ShareGrant.share_id == Document.share_for(document_id), ShareGrant.user_id == actor_agent_id.user_id))
            if human_grant is None:
                db.add(ShareGrant(share_id=Document.share_for(document_id), user_id=actor_agent_id.user_id, can_write=True))
            else:
                human_grant.can_write = True
    elif data.kind != "agent" or data.id != actor_agent_id:
        actor_grant = await db.scalar(
            select(ShareGrant).where(
                ShareGrant.share_id == Document.share_for(document_id),
                ShareGrant.agent_id == actor_agent_id,
            )
        )
        if actor_grant is None:
            db.add(
                ShareGrant(share_id=Document.share_for(document_id),
                    agent_id=actor_agent_id,
                    can_write=True,
                )
            )
        else:
            actor_grant.can_write = True

    await db.flush()
    has_grants = await has_document_grants(document_id)
    item.visibility = "shared" if has_grants or item.global_access > 0 or item.group_access > 0 else "private"
    await finish_own_sharing(item)
    await commit_item_sharing(item)
    loaded = await _get_item_record(document_id, revisions=include_revisions)
    assert loaded is not None
    await _emit_document_event("update", loaded)
    await notify_document(loaded.id, "update")
    return loaded

async def list_document_folders(agent_id: int) -> list[str]:
    """List distinct logical folders from documents readable by one agent."""

    now = datetime.now(timezone.utc)
    result = await get_db().scalars(
        select(Document.metadata_).where(
            readable_item_clause(agent_id),
            Document.node_kind == "document",
            or_(Document.valid_from.is_(None), Document.valid_from <= now),
            or_(Document.valid_until.is_(None), Document.valid_until > now),
        )
    )
    folders = {
        value.strip().strip("/")
        for metadata in result.all()
        if isinstance((value := metadata.get("document_path")), str)
        and value.strip().strip("/")
    }
    return sorted(folders, key=str.casefold)

async def list_document_folder_options(agent_id: int) -> list[DocumentFolderOption]:
    """Describe readable folders, including ancestors, from their documents' actual roles and grants."""

    now = datetime.now(timezone.utc)
    items = await get_db().scalars(
        select(Document)
        .options(selectinload(Document.grants), raiseload(Document.revisions),
                 defer(Document.summary_content), defer(Document.content))
        .where(
            readable_item_clause(agent_id),
            Document.node_kind == "document",
            or_(Document.valid_from.is_(None), Document.valid_from <= now),
            or_(Document.valid_until.is_(None), Document.valid_until > now),
        )
    )
    folders: dict[str, DocumentFolderOption] = {}
    for item in items:
        raw_path = item.metadata_.get("document_path")
        if not isinstance(raw_path, str):
            continue
        parts = [part.strip() for part in raw_path.replace("\\", "/").split("/") if part.strip()]
        if any(part in {".", ".."} for part in parts):
            continue
        readers = {grant.agent_id for grant in item.grants}
        if item.owner_agent_id is not None:
            readers.add(item.owner_agent_id)
        shared = item.visibility == "public" or item.global_access >= 1 or len(readers) > 1
        for depth in range(1, len(parts) + 1):
            path = "/".join(parts[:depth])
            folder = folders.setdefault(path, DocumentFolderOption(path=path, kind="custom", shared=False))
            if _is_goal_document(item):
                folder.kind = "goal"
            folder.shared = folder.shared or shared
    return sorted(folders.values(), key=lambda folder: folder.path.casefold())

async def update_item(
    item_id: UUID,
    data: DocumentUpdate,
    *,
    actor_agent_id: int | HumanActor | None,
    administrative: bool = False,
    actor_task_id: UUID | None = None,
    notify_observers: bool = True,
    preserve_document_attachments: bool = True,
    document_revision_author_agent_id: int | None = None,
    document_append: bool = False,
    allow_goal_document_metadata_sync: bool = False,
    include_revisions: bool = True,
) -> Document:
    item = await _get_item_record(item_id, revisions=include_revisions)
    if item is None:
        raise DocumentNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    if item.document_type == "dataset" and actor_agent_id is not None:
        from .dataset_port import dataset_compatibility
        if adapter := dataset_compatibility():
            await adapter.adopt(item.id)
            await adapter.update(item.id, actor_agent_id, data.model_dump(exclude_unset=True))
            await get_db().refresh(item)
            return item
    if data.expected_revision is not None and data.expected_revision != item.revision:
        raise DocumentConflictError(
            f"Document revision conflict: expected {data.expected_revision}, "
            f"current revision is {item.revision}."
        )
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise DocumentConflictError(
            "The document changed while it was being edited; reload and retry."
        )
    fields = data.model_fields_set - {
        "expected_revision",
        "expected_lock_version",
    }
    if not fields:
        return item
    if "metadata" in fields and data.metadata is not None:
        protected_workflow = ("creation_command", "process_code", "topic_assignment")
        if any(data.metadata.get(key) != item.metadata_.get(key) for key in protected_workflow):
            raise DocumentPermissionError("Workflow metadata is server-owned")
    if item.document_type == "process" and "metadata" in fields and data.metadata is not None and data.metadata.get("process_code") != item.metadata_.get("process_code"):
        raise DocumentPermissionError("The process code is immutable")
    if item.node_kind == "memory" and not item.source_managed:
        if "title" in fields:
            raise DocumentPermissionError("A memory has no editable title.")
        if "visibility" in fields and data.visibility != "private":
            raise DocumentPermissionError("Memories are private; share a document instead.")
    if item.managed_source_kind == "file_catalogue" and "visibility" in fields and data.visibility != "private":
        raise DocumentPermissionError("A file catalogue entry must remain private to its agent.")
    if "visibility" in fields and data.visibility != item.visibility:
        owns_item = (
            item.owner_agent_id == actor_agent_id if isinstance(actor_agent_id, int)
            else isinstance(actor_agent_id, HumanActor) and item.owner_user_id == actor_agent_id.user_id
        )
        if not administrative and not owns_item:
            raise DocumentPermissionError("Only the owner can manage sharing.")
        if item.global_access > 0 and data.visibility != "shared":
            raise DocumentConflictError("Update public access through the sharing form.")
    is_goal_document = _is_goal_document(item)
    if (
        is_goal_document
        and "title" in fields
        and data.title != item.title
        and not allow_goal_document_metadata_sync
    ):
        raise DocumentPermissionError(
            "The title, owner, and path of a Goal document are controlled by its Goal "
            "and cannot be changed directly."
        )
    if "metadata" in fields and data.metadata is not None:
        goal_metadata_changed = any(
            data.metadata.get(key) != item.metadata_.get(key)
            for key in ("goal_id", "goal_document_kind", "document_path")
        )
        if is_goal_document and goal_metadata_changed and not allow_goal_document_metadata_sync:
            raise DocumentPermissionError(
                "The title, owner, and path of a Goal document are controlled by its Goal "
                "and cannot be changed directly."
            )
    if item.node_kind == "document":
        if data.content_type not in (None, "text"):
            raise DocumentConflictError("A document must contain text.")
        if item.document_type == "dataset" and data.media_type not in (None, "application/json"):
            raise DocumentConflictError("A Dataset document must retain its application/json format.")
        if item.document_type == "process" and data.media_type not in (None, "application/bpmn+xml"):
            raise DocumentConflictError("A Process document must retain its BPMN format.")
        if item.document_type == "html" and data.media_type is not None and not data.media_type.startswith("text/"):
            raise DocumentConflictError("A document must contain text.")
        if data.visibility == "public":
            raise DocumentConflictError("A document must be shared through explicit agent grants.")
        if data.visibility == "private" and (item.global_access > 0 or item.group_access > 0):
            raise DocumentConflictError("A globally shared document must keep shared visibility.")
        if data.read_only:
            raise DocumentConflictError("A working document must remain editable.")
    assert_safe_value(
        data.model_dump(
            exclude={"payload", "expected_revision", "expected_lock_version"},
            exclude_unset=True,
            mode="python",
        )
    )

    if item.content_profile_version == 1 and (
        data.content_type not in (None, "text") or data.media_type not in (None, "text/html")
    ):
        raise DocumentConflictError("Editorial content must retain its text/html profile.")
    if data.media_type is not None and data.media_type != item.media_type and data.payload is None:
        raise DocumentConflictError("A format change requires an explicit converted payload.")
    previous_values = {
        name: getattr(item, name)
        for name in (
            "title",
            "content_type",
            "media_type",
            "filename",
            "visibility",
            "read_only",
            "valid_from",
            "valid_until",
            "temporal",
        )
    }
    previous_metadata = dict(item.metadata_)
    previous_provider_code = item.provider_code
    previous_resource_id = item.resource_id
    new_resource_id: str | None = None
    document_content: bytes | None = None
    content_changed = False
    provider = get_storage(item.provider_code)
    if "payload" in fields and data.payload is not None:
        content = decode_payload(data.payload)
        if item.node_kind == "document" and item.document_type != "html":
            validate_document_content(item.document_type, content)
        future_content_type = data.content_type or item.content_type
        future_media_type = data.media_type or item.media_type
        if future_content_type == "text" and future_media_type in {
            "text/html",
            "text/markdown",
            "text/plain",
        }:
            content = convert_to_html(
                content.decode("utf-8"), future_media_type, profile=item.content_profile
            ).encode("utf-8")
            if item.node_kind == "document":
                apps = document_apps(content.decode("utf-8"))
                if apps and item.deletion_protected:
                    raise ValueError("Managed editorial documents cannot contain applications.")
            if item.media_type == "text/html" and data.media_type not in (None, "text/html"):
                raise DocumentConflictError(
                    "This content now requires explicit text/html writes. Refresh the client."
                )
            if item.node_kind == "document":
                from .document_attachment_service import attachments_from_item

                allowed = {
                    str(value.id)
                    for value in attachments_from_item(item, include_retained=True)
                    if value.media_type in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
                }
                for uri in image_references(content.decode("utf-8")):
                    reference = attachment_reference(uri)
                    if (
                        reference is None
                        or reference[0] != item.id
                        or str(reference[1]) not in allowed
                    ):
                        raise DocumentPermissionError(
                            "The image must belong to this document's attachments."
                        )
            if _is_goal_document(item) and item.metadata_.get("goal_document_kind") == "tracking":
                if (
                    len(content.decode("utf-8")) > 120_000
                    or len(visible_text(content.decode("utf-8"))) > 30_000
                ):
                    raise DocumentConflictError(
                        "Goal tracking exceeds its serialized or visible text limit."
                    )
            future_media_type = "text/html"
            data = data.model_copy(update={"media_type": "text/html"})
            fields.add("media_type")
            item.content_profile_version = 1
            if item.node_kind == "document":
                item.metadata_ = {
                    **item.metadata_,
                    "content_images": sorted(image_references(content.decode("utf-8"))),
                }
        if future_content_type == "text" or future_media_type.startswith("text/"):
            assert_safe_text(content.decode("utf-8", errors="replace"))
        digest = _content_hash(content)
        document_content = content
        content_changed = item.content_hash != digest
        if content_changed:
            new_resource_id, inline = await prepare_content(content, provider.code, content_type=future_content_type)
            item.resource_id = new_resource_id
            item.content = inline
            item.content_hash = digest
            item.size_bytes = len(content)
            item.search_text = _search_text(
                content,
                content_type=future_content_type,
                media_type=future_media_type,
            )

    scalar_fields = (
        "title",
        "content_type",
        "media_type",
        "filename",
        "visibility",
        "read_only",
        "valid_from",
        "valid_until",
    )
    for field_name in scalar_fields:
        if field_name in fields:
            setattr(item, field_name, getattr(data, field_name))
    keywords_changed = False
    if "temporal" in fields:
        item.temporal = data.temporal.model_dump(mode="json") if data.temporal else None
    if "keywords" in fields and data.keywords is not None:
        keywords_changed = _set_keywords(item, data.keywords)
    if "metadata" in fields and data.metadata is not None:
        filename = item.filename
        metadata = dict(data.metadata)
        if item.node_kind == "document" and preserve_document_attachments:
            for attachment_key in (
                "document_attachments",
                "retained_document_attachments",
                "content_images",
            ):
                if attachment_key in item.metadata_:
                    metadata[attachment_key] = item.metadata_[attachment_key]
                else:
                    metadata.pop(attachment_key, None)
        item.metadata_ = metadata
        if item.node_kind != "document":
            item.filename = filename
    if item.managed_source_kind == "file_catalogue":
        # Source identity and manual ownership survive generic metadata writes.
        metadata = dict(item.metadata_)
        for key in ("catalogue_ref", "catalogue_editable", "catalogue_manual_content", "catalogue_manual_title"):
            if key in previous_metadata:
                metadata[key] = previous_metadata[key]
            else:
                metadata.pop(key, None)
        if content_changed:
            metadata["catalogue_manual_content"] = True
        if item.title != previous_values["title"]:
            metadata["catalogue_manual_title"] = True
        item.metadata_ = metadata
    if item.node_kind == "memory" and not item.source_managed:
        item.title = item.search_text[:120]
    document_format_changed = any(previous_values[field] != getattr(item, field) for field in ("content_type", "media_type"))
    if content_changed or document_format_changed:
        await refresh_document_search(item, content=document_content)
    _set_semantic_fingerprint(item)
    meaningful_change = bool(
        fields
        & {
            "payload",
            "title",
            "keywords",
            "metadata",
            "valid_from",
            "valid_until",
            "temporal",
        }
    )
    if content_changed or keywords_changed or previous_values["temporal"] != item.temporal:
        item.updated_at = datetime.now(timezone.utc)
    if meaningful_change:
        item.old_at = None
        item.old_reason = None
    changed = (
        content_changed
        or keywords_changed
        or previous_metadata != item.metadata_
        or any(getattr(item, name) != value for name, value in previous_values.items())
    )
    # A document revision describes its payload, not its metadata or ACLs.
    if content_changed or (item.node_kind != "document" and changed):
        item.revision += 1
    db = get_db()
    if content_changed or (item.node_kind != "document" and changed):
        db.add(
            _revision_for(
                item,
                author_agent_id=(
                    document_revision_author_agent_id
                    if item.node_kind == "document"
                    else (actor_agent_id if isinstance(actor_agent_id, int) else None)
                ),
                task_id=actor_task_id,
                document_content_version=(True if item.node_kind == "document" else None),
                document_append=document_append if item.node_kind == "document" else False,
            )
        )
    try:
        if item.node_kind == "document" and (content_changed or document_format_changed or any(
            previous_metadata.get(key) != item.metadata_.get(key)
            for key in ("document_attachments", "retained_document_attachments")
        )):
            from .document_structure import sync_document_structure
            await db.flush()
            await sync_document_structure(item, document_content)
        if content_changed:
            item.thumbnail_id = None
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        if new_resource_id is not None:
            await provider.delete(new_resource_id)
        raise DocumentConflictError(
            "The document changed while it was being edited; reload and retry."
        ) from exc
    except Exception:
        await db.rollback()
        if new_resource_id is not None:
            await provider.delete(new_resource_id)
        raise
    loaded = await _get_item_record(item.id, revisions=include_revisions)
    assert loaded is not None
    if content_changed and previous_resource_id != loaded.resource_id:
        await _delete_resource_if_unreferenced(
            previous_provider_code,
            previous_resource_id,
        )
    if content_changed:
        from .document_thumbnail_service import cleanup_current_document_thumbnail
        await cleanup_current_document_thumbnail(loaded.id)
    await _notify_index(loaded)
    await _emit_document_event("update", loaded)
    if notify_observers:
        await notify_document(loaded.id, "update")
    return loaded

async def update_summary(
    item_id: UUID, data: DocumentUpdate, *, actor_agent_id: int | HumanActor | None,
    administrative: bool = False,
) -> Document:
    """Edit an independent synthesis using the current document's live rights."""
    item = await _get_item_record(item_id)
    if item is None:
        raise DocumentNotFoundError("Document not found.")
    await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    fields = data.model_fields_set - {"expected_revision", "expected_lock_version"}
    if fields - {"payload", "keywords", "temporal", "valid_from", "valid_until", "media_type", "content_type"}:
        raise DocumentPermissionError("Edit document metadata and sharing through its document.")
    if data.media_type not in (None, "text/html") or data.content_type not in (None, "text"):
        raise DocumentConflictError("A document synthesis must use rich text.")
    if data.expected_revision is not None and data.expected_revision != item.summary_revision:
        raise DocumentConflictError("Document summary changed; reload and retry")
    if data.expected_lock_version is not None and data.expected_lock_version != item.lock_version:
        raise DocumentConflictError("Document or synthesis changed; reload and retry")
    previous_resource = item.summary_resource_id
    provider = get_storage(item.summary_provider_code)
    new_resource: str | None = None
    changed = False
    if data.payload is not None:
        content = convert_to_html(decode_payload(data.payload).decode("utf-8"), "text/html", profile="rich-text").encode("utf-8")
        assert_safe_text(content.decode("utf-8"))
        digest = _content_hash(content)
        if digest != item.summary_content_hash:
            new_resource, inline = await prepare_content(content, provider.code) if content else ("", "")
            item.summary_resource_id = new_resource
            item.summary_content = inline
            item.summary_content_hash = digest
            item.summary_size_bytes = len(content)
            item.summary_document_revision = item.revision
            changed = True
    keywords_changed = data.keywords is not None and _set_keywords(item, data.keywords)
    if "temporal" in fields:
        temporal = data.temporal.model_dump(mode="json") if data.temporal else None
        changed = changed or temporal != item.temporal
        item.temporal = temporal
    for name in ("valid_from", "valid_until"):
        if name in fields:
            changed = changed or getattr(item, name) != getattr(data, name)
            setattr(item, name, getattr(data, name))
    if not changed and not keywords_changed:
        return item
    if changed:
        item.summary_revision += 1
    item.lock_version += 1
    item.updated_at = datetime.now(timezone.utc)
    if changed:
        get_db().add(DocumentSummaryRevision(
            document_id=item.id, revision=item.summary_revision, provider_code=item.summary_provider_code,
            resource_id=item.summary_resource_id, content=item.summary_content, content_hash=item.summary_content_hash,
            source_document_revision=item.summary_document_revision or item.revision,
            author_agent_id=actor_agent_id if isinstance(actor_agent_id, int) else None,
            keywords=list(item.keywords), temporal=item.temporal,
        ))
    try:
        await refresh_document_search(item)
        _set_semantic_fingerprint(item)
        await _commit_with_conflict("Document or synthesis changed; reload and retry")
    except BaseException:
        async def discard_unpublished() -> None:
            await get_db().rollback()
            if new_resource:
                await _delete_resource_if_unreferenced(provider.code, new_resource)

        try:
            await complete_await(discard_unpublished())
        except Exception:
            logger.exception("Unable to reconcile an interrupted Document summary update")
        raise
    if new_resource is not None and previous_resource and previous_resource != new_resource:
        await _delete_resource_if_unreferenced(item.summary_provider_code, previous_resource)
    loaded = await _get_item_record(item_id)
    assert loaded is not None
    await _notify_index(loaded)
    await _emit_document_event("update", loaded)
    await notify_document(item_id, "content")
    return loaded


async def _get_item_record(item_id: UUID, *, revisions: bool = True, contents: bool = True, include_historized: bool = False) -> Document | None:
    options = [selectinload(Document.grants), selectinload(Document.url_relations), selectinload(Document.revisions) if revisions else raiseload(Document.revisions)]
    if not contents:
        options += [defer(Document.content), defer(Document.summary_content)]
    return await get_db().scalar(select(Document).options(*options).where(Document.id == item_id).execution_options(populate_existing=True, include_historized=include_historized))


async def item_record(item_id: UUID, *, revisions: bool = True, contents: bool = True) -> Document | None:
    return await _get_item_record(item_id, revisions=revisions, contents=contents)


async def document_record(document_id: UUID, *, revisions: bool = True) -> Document | None:
    return await _get_item_record(document_id, revisions=revisions)


async def assert_item_access(item: Document, actor: int | HumanActor | None, *, write: bool = False, administrative: bool = False) -> DocumentAccess:
    if administrative:
        return DocumentAccess(can_read=True, can_write=not item.read_only)
    if actor is None:
        raise DocumentPermissionError("A document actor is required")
    access = await effective_access(item, actor)
    if not (access.can_write if write else access.can_read):
        raise DocumentPermissionError("Document access denied")
    return access


async def get_item_metadata(item_id: UUID, *, agent_id: int | HumanActor, administrative: bool = False) -> tuple[Document, DocumentAccess]:
    item = await _get_item_record(item_id, revisions=False)
    if item is None:
        raise DocumentNotFoundError("Document not found")
    return item, await assert_item_access(item, agent_id, administrative=administrative)


async def source_refs(item_id: UUID) -> list[str]:
    return list(await get_db().scalars(select(DocumentSource.source_ref).where(DocumentSource.document_id == item_id).order_by(DocumentSource.created_at, DocumentSource.id)))


async def add_item_source(item_id: UUID, data: DocumentSourceCreate, *, actor_agent_id: int | HumanActor) -> None:
    item = await _get_item_record(item_id, revisions=False)
    if item is None:
        raise DocumentNotFoundError("Document not found")
    await assert_item_access(item, actor_agent_id, write=True)
    existing = await get_db().scalar(select(DocumentSource.id).where(
        DocumentSource.document_id == item_id, DocumentSource.source_kind == data.source_kind,
        DocumentSource.source_ref == data.source_ref,
    ))
    if existing is None:
        task, round_ = await _source_targets(data.source_kind, data.source_ref)
        get_db().add(DocumentSource(document_id=item_id, source_kind=data.source_kind,
            source_ref=data.source_ref, excerpt=data.excerpt, content_hash=item.content_hash,
            metadata_=dict(data.metadata), task_id=task, conversation_round_id=round_))
        await get_db().commit()
        await notify_document(item_id, "source")


async def get_item(item_id: UUID, *, agent_id: int | HumanActor, revision: int | None = None, record_llm_access: bool = False, task_id: UUID | None = None, include_revisions: bool = True, administrative: bool = False) -> tuple[Document, bytes, DocumentAccess, str, str]:
    item = await _get_item_record(item_id, revisions=include_revisions)
    if item is None:
        raise DocumentNotFoundError("Document not found")
    access = await assert_item_access(item, agent_id, administrative=administrative)
    if revision is not None:
        entry = await get_db().scalar(select(DocumentRevision).where(DocumentRevision.document_id == item_id, DocumentRevision.revision == revision))
        if entry is None:
            raise DocumentNotFoundError("Document revision not found")
        content = await get_storage(entry.provider_code).read(entry.resource_id)
        return item, content, access, entry.content_type, entry.media_type
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(item_id):
        state = await adapter.read(item_id, agent_id)
        return item, str(state["content"]).encode(), access, "text", "application/json"
    content = await get_storage(item.provider_code).read(item.resource_id)
    if hashlib.sha256(content).hexdigest() != item.content_hash:
        raise DocumentConflictError("Document content does not match its resource")
    if record_llm_access:
        # Account for reads without committing the caller's pending work.
        await get_db().execute(update(Document).where(Document.id == item.id).values(last_accessed_at=datetime.now(timezone.utc), access_count=Document.access_count + 1).execution_options(synchronize_session=False))
    return item, content, access, item.content_type, item.media_type


async def item_to_detail(item: Document, content: bytes, access: DocumentAccess, *, content_type: str, media_type: str) -> DocumentDetail:
    return DocumentDetail(**item_to_public(item, access).model_dump(), payload=encode_payload(content, content_type=content_type, media_type=media_type), source_refs=await source_refs(item.id))


def _revision_for(item: Document, *, author_agent_id: int | None, task_id: UUID | None = None, document_content_version: bool | None = True, document_append: bool = False) -> DocumentRevision:
    return DocumentRevision(document_id=item.id, revision=item.revision, provider_code=item.provider_code, resource_id=item.resource_id, content=item.content, content_hash=item.content_hash, content_type=item.content_type, media_type=item.media_type, content_profile_version=item.content_profile_version, filename=item.filename, title=item.title, keywords=list(item.keywords), metadata_=dict(item.metadata_), temporal=item.temporal, task_id=task_id, author_agent_id=author_agent_id, document_content_version=document_content_version, document_append=document_append)


async def create_item(data: DocumentItemCreate, *, actor_task_id: UUID | None = None, deletion_protected: bool = False, deduplicate: bool = False, owner_user_id: int | None = None, initial_editor_agent_id: int | None = None, workflow_metadata: bool = False) -> tuple[Document, bool]:
    if not workflow_metadata and any(key in data.metadata for key in ("creation_command", "process_code")):
        raise DocumentPermissionError("Workflow metadata is server-owned")
    if any(key in data.metadata for key in ("document_attachments", "retained_document_attachments", "content_images")):
        raise DocumentPermissionError("Attachment metadata is server-owned")
    if data.visibility != "private" or data.read_only:
        raise DocumentPermissionError("A new document is private and editable")
    content = decode_payload(data.payload)
    validate_document_content(data.document_type, content)
    media_type = data.media_type
    if data.document_type == "html" and media_type in {"text/html", "text/markdown", "text/plain"}:
        content = convert_to_html(content.decode(), media_type, profile="rich-text" if deletion_protected else "document").encode()
        media_type = "text/html"
    if image_references(content.decode("utf-8", errors="replace")):
        raise DocumentPermissionError("The image must belong to this document's attachments")
    assert_safe_text(content.decode("utf-8", errors="replace"))
    assert_safe_value(data.model_dump(exclude={"payload", "source"}))
    if deletion_protected and data.document_type == "html" and document_apps(content.decode()):
        raise ValueError("Managed editorial documents cannot contain applications")
    pointer, inline = await prepare_content(content, data.provider_code, content_type=data.content_type)
    item = Document(id=uuid4(), owner_agent_id=None if owner_user_id is not None else data.owner_agent_id, owner_user_id=owner_user_id, title=data.title.strip(), provider_code=data.provider_code, resource_id=pointer, content=inline, revision=1, content_hash=_content_hash(content), size_bytes=len(content), content_type=data.content_type, media_type=media_type, content_profile_version=1 if media_type == "text/html" else None, filename=data.filename, document_type=data.document_type, keywords=_keywords(data.keywords), metadata_=dict(data.metadata), deletion_protected=deletion_protected, valid_from=data.valid_from, valid_until=data.valid_until, temporal=data.temporal.model_dump(mode="json") if data.temporal else None, search_text=_search_text(content, content_type=data.content_type, media_type=media_type))
    db=get_db()
    try:
        db.add(item)
        await db.flush()
        db.add(_revision_for(item, author_agent_id=None if owner_user_id is not None else data.owner_agent_id, task_id=actor_task_id))
        if initial_editor_agent_id is not None:
            if owner_user_id is None:
                raise ValueError("An initial editor grant requires a human-owned document")
            db.add(ShareGrant(share_id=item.share_id, agent_id=initial_editor_agent_id, can_write=True))
        if data.source is not None:
            task_target, round_target = await _source_targets(data.source.source_kind, data.source.source_ref)
            db.add(DocumentSource(document_id=item.id, source_kind=data.source.source_kind, source_ref=data.source.source_ref, excerpt=data.source.excerpt, content_hash=item.content_hash, metadata_=dict(data.source.metadata), task_id=task_target, conversation_round_id=round_target))
        await db.commit()
    except BaseException:
        async def compensate() -> None:
            await db.rollback()
            await _delete_resource_if_unreferenced(data.provider_code, pointer)
        try:
            await complete_await(compensate())
        except Exception:
            logger.exception("Unable to reconcile an interrupted document creation")
        raise
    loaded=await _get_item_record(item.id)
    assert loaded is not None
    await _emit_document_event("create", loaded)
    await notify_document(loaded.id, "create")
    return loaded, True


async def _source_targets(kind: str, reference: str) -> tuple[UUID | None, UUID | None]:
    from app.task import Task
    from app.conversation import ConversationRound
    prefix = "task:" if kind in {"task", "task_outcome"} else "conversation_round:" if kind == "conversation_round" else ""
    if not prefix or not reference.startswith(prefix):
        return None, None
    try:
        identity = UUID(reference.removeprefix(prefix).split(":", 1)[0])
    except ValueError:
        return None, None
    if prefix == "task:":
        return await get_db().scalar(select(Task.id).where(Task.id==identity).execution_options(include_historized=True)), None
    return None, await get_db().scalar(select(ConversationRound.id).where(ConversationRound.id==identity))


async def refresh_document_search(item: Document, *, content: bytes | None = None) -> None:
    if content is None:
        content=await get_storage(item.provider_code).read(item.resource_id)
    text=_search_text(content, content_type=item.content_type, media_type=item.media_type)
    if item.summary_resource_id:
        text += "\n" + visible_text((await get_storage(item.summary_provider_code).read(item.summary_resource_id)).decode())
    item.search_text=text


def _set_semantic_fingerprint(item: Document) -> None:
    # The graph/search adapter owns its fingerprint and rebuildable index.
    pass


async def _notify_index(item: Document) -> None:
    await notify_document(item.id, "index")


async def _emit_document_event(action: str, item: Document) -> None:
    from core import websocket
    await websocket.emit("document", action, {
        "id": str(item.id), "node_kind": "document", "owner_agent_id": item.owner_agent_id,
        "owner_user_id": item.owner_user_id, "revision": item.revision, "lock_version": item.lock_version,
        "media_type": item.media_type, "content_profile": item.content_profile,
        "content_profile_version": item.content_profile_version,
    }, None)
    if action == "delete" or get_db().info.pop("document_sharing_changed", False):
        # Former readers cannot receive an identified event after losing access.
        # A content-free invalidation makes them recheck all source permissions.
        await invalidate_document_views()


async def invalidate_document_views() -> None:
    from core import websocket
    await websocket.emit("document", "invalidate", {}, None)


async def commit_item_sharing(item: Document) -> None:
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if item.document_type == "dataset" and adapter and await adapter.contains(item.id):
        db = get_db()
        await db.flush()
        grants = await db.execute(select(
            ShareGrant.agent_id, ShareGrant.user_id, ShareGrant.team_id, ShareGrant.can_write,
        ).where(ShareGrant.share_id == Document.share_for(item.id)))
        await adapter.sharing(item.id, {
            "owner_agent_id": item.owner_agent_id, "owner_user_id": item.owner_user_id,
            "global_access": item.global_access, "group_access": item.group_access,
            "lock_version": item.lock_version,
            "grants": [{**({"agent_id": row.agent_id} if row.agent_id is not None else
                {"user_id": row.user_id} if row.user_id is not None else {"team_id": row.team_id}),
                "can_write": row.can_write}
                for row in grants],
        })
    await _commit_with_conflict("Document sharing changed; reload and retry")
    await _emit_document_event("update", item)
    await notify_document(item.id, "sharing")


async def _delete_resource_if_unreferenced(provider_code: str, resource_id: str) -> None:
    if resource_id and not await resource_is_referenced(provider_code, resource_id):
        await get_storage(provider_code).delete(resource_id)


async def delete_document(item_id: UUID, *, actor_agent_id: int | HumanActor | None = None, administrative: bool = False) -> DocumentDeletionResult:
    item=await _get_item_record(item_id)
    if item is None:
        raise DocumentNotFoundError("Document not found")
    await assert_item_access(item, actor_agent_id, write=True, administrative=administrative)
    _assert_not_deletion_protected(item)
    owns = (isinstance(actor_agent_id, int) and item.owner_agent_id == actor_agent_id) or (
        isinstance(actor_agent_id, HumanActor) and item.owner_user_id == actor_agent_id.user_id)
    if not administrative and not owns:
        raise DocumentPermissionError("Only the owner can delete a document")
    return await forget_item_record(item, forget_kind="explicit")

async def browse_document_library(request: DocumentLibraryRequest, *, managed_agent_ids: Collection[int] | None, user_id: int | None = None) -> DocumentLibraryPage:
    from .library_queries import browse_document_library as browse
    return await browse(request, managed_agent_ids=managed_agent_ids, user_id=user_id)


async def list_document_keywords(agent_id: int) -> list[str]:
    from .library_queries import list_document_keywords as keywords
    return await keywords(agent_id)


async def list_document_owner_options(*, current_user_id: int, include_all_users: bool, managed_agent_ids: Collection[int] | None, search: str = "", current_user: UserModel | None = None) -> DocumentOwnerOptions:
    from .library_queries import list_document_owner_options as owners
    return await owners(current_user_id=current_user_id, include_all_users=include_all_users,
        managed_agent_ids=managed_agent_ids, search=search, current_user=current_user)

async def forget_deleted_dataset_projection(identity: UUID) -> None:
    item=await document_record(identity, revisions=False)
    if item is not None:
        item.soft_delete()
        await get_db().flush()

async def forget_item_record(item: Document, *, forget_kind: str) -> DocumentDeletionResult:
    from .models import DocumentAttachment, DocumentAutomationJob
    from .sharing_inheritance import lock_sharing, reconcile_sharing
    from core.storage import retire_file_references
    await lock_sharing()
    db = get_db()
    summaries = list(await db.scalars(select(DocumentSummaryRevision).where(
        DocumentSummaryRevision.document_id == item.id)))
    revisions = list(await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == item.id)))
    resources = {(item.provider_code, item.resource_id), (item.summary_provider_code, item.summary_resource_id),
        *((row.provider_code, row.resource_id) for row in [*summaries, *revisions])}
    retired = await retire_file_references(f"document://{item.id}/attachments/")
    resources.update(("native", str(identity)) for identity in retired)
    for model in (DocumentRevision, DocumentSummaryRevision, DocumentSource):
        await db.execute(delete(model).where(model.document_id == item.id))
    await db.execute(update(DocumentAttachment).where(DocumentAttachment.document_id == item.id).values(active=False))
    set_committed_value(item, "revisions", [])
    item.content, item.summary_content = "", ""
    item.thumbnail_id = None
    item.resource_id, item.summary_resource_id = "", ""
    item.content_hash = item.summary_content_hash = _content_hash(b"")
    item.size_bytes = item.summary_size_bytes = 0
    item.metadata_, item.keywords, item.search_text = {}, [], ""
    item.soft_delete()
    for provider, pointer in sorted(resources):
        if not pointer:
            continue
        key = hashlib.sha256(f"document_cleanup:{provider}:{pointer}:{item.id}".encode()).hexdigest()
        if await db.scalar(select(DocumentAutomationJob.id).where(DocumentAutomationJob.idempotency_key == key)) is None:
            db.add(DocumentAutomationJob(kind="resource_cleanup", idempotency_key=key,
                payload={"provider": provider, "pointer": pointer}))
    await reconcile_sharing()
    await db.commit()
    from .document_thumbnail_service import cleanup_current_document_thumbnail
    await cleanup_current_document_thumbnail(item.id)
    await _emit_document_event("delete",item)
    await notify_document(item.id,"delete")
    return DocumentDeletionResult(document_id=item.id)

async def delete_process_content_revision(
    item_id: UUID, revision: int, *, actor_agent_id: int | HumanActor,
) -> None:
    """Erase an old process snapshot without changing its current content or ACLs."""
    item = await document_record(item_id, revisions=False)
    if item is None or item.document_type != "process":
        raise DocumentNotFoundError("Process not found.")
    await assert_item_access(item, actor_agent_id, write=True)
    if revision >= item.revision:
        raise DocumentConflictError(await tr("document.errors.current_revision_delete"))
    from .revision_queries import content_revision
    entry = await content_revision(item_id, revision)
    if entry is None:
        raise DocumentNotFoundError("Process revision not found.")
    provider_code, resource_id = entry.provider_code, entry.resource_id
    await get_db().delete(entry)
    await get_db().commit()
    await _delete_resource_if_unreferenced(provider_code, resource_id)
