"""Private classification; assigning a tag never writes to the document."""

from uuid import UUID

from sqlalchemy import delete, func, select

from app.agent import AgentManagementScope
from core.database import get_db

from . import document_sharing, service
from .events import emit_classification
from .models import DocumentTag, DocumentTagAssignment, DocumentTagIcon
from .schemas import DocumentTagDeletionResult, DocumentTagPublic, DocumentTagWrite, DocumentTagIconPublic, DocumentTagIconWrite


async def list_tags(user_id: int) -> list[DocumentTagPublic]:
    tags = await get_db().scalars(select(DocumentTag).where(DocumentTag.user_id == user_id).order_by(
        DocumentTag.position, func.lower(DocumentTag.name), DocumentTag.id,
    ))
    return [DocumentTagPublic.model_validate(tag) for tag in tags]


async def require_tag(user_id: int, tag_id: UUID) -> DocumentTag:
    tag = await get_db().scalar(select(DocumentTag).where(
        DocumentTag.id == tag_id, DocumentTag.user_id == user_id,
    ).execution_options(populate_existing=True))
    if tag is None:
        raise service.MemoryNotFoundError("Tag not found")
    return tag


async def lock_tree(user_id: int) -> None:
    # Serialize one user's tree edits, including concurrent moves and assignments.
    await get_db().execute(select(func.pg_advisory_xact_lock(1195656263, user_id)))


async def next_position(user_id: int, parent_id: UUID | None) -> int:
    db = get_db()
    folder_max = await db.scalar(select(func.max(DocumentTag.position)).where(
        DocumentTag.user_id == user_id, DocumentTag.parent_id == parent_id,
    )) or 0
    document_max = await db.scalar(select(func.max(DocumentTagAssignment.position)).where(
        DocumentTagAssignment.tag_id == parent_id,
    )) if parent_id is not None else 0
    return max(folder_max, document_max or 0) + 1


async def write_tag(user_id: int, data: DocumentTagWrite, tag_id: UUID | None = None) -> DocumentTagPublic:
    db = get_db()
    await lock_tree(user_id)
    tag = await require_tag(user_id, tag_id) if tag_id is not None else DocumentTag(user_id=user_id)
    parent_id = data.parent_id
    while parent_id is not None:
        if parent_id == tag_id:
            raise ValueError("A tag cannot be placed inside itself")
        parent_id = (await require_tag(user_id, parent_id)).parent_id
    if tag_id is None or tag.parent_id != data.parent_id:
        tag.position = await next_position(user_id, data.parent_id)
    tag.name = data.name
    tag.parent_id = data.parent_id
    if "icon" in data.model_fields_set:
        tag.icon = data.icon
    db.add(tag)
    await db.flush()
    from .document_structure import sync_folder_structure
    await sync_folder_structure(user_id)
    result = DocumentTagPublic.model_validate(tag)
    await db.commit()
    await emit_classification(user_id, tags_changed=True)
    return result


async def remove_tag(user_id: int, tag_id: UUID, *, confirmed: bool = False) -> DocumentTagDeletionResult:
    """Delete a private branch and return its documents to this user's orphan list."""
    db = get_db()
    await lock_tree(user_id)
    await require_tag(user_id, tag_id)
    tags = list(await db.scalars(select(DocumentTag).where(DocumentTag.user_id == user_id)))
    branch = {tag_id}
    while children := {tag.id for tag in tags if tag.parent_id in branch} - branch:
        branch.update(children)
    affected_documents = select(DocumentTagAssignment.document_id).where(DocumentTagAssignment.tag_id.in_(branch))
    document_count = await db.scalar(select(func.count(func.distinct(DocumentTagAssignment.document_id))).where(
        DocumentTagAssignment.tag_id.in_(branch),
    )) or 0
    result = DocumentTagDeletionResult(deleted=False, tag_count=len(branch), document_count=document_count)
    if not confirmed and (len(branch) > 1 or document_count > 0):
        await db.commit()
        return result
    affected_ids = list(await db.scalars(affected_documents.distinct()))
    # Legacy documents can have multiple personal tags. Clear all of this user's
    # assignments for affected documents, while preserving everybody else's tags.
    await db.execute(delete(DocumentTagAssignment).where(
        DocumentTagAssignment.document_id.in_(affected_documents),
        DocumentTagAssignment.tag_id.in_(select(DocumentTag.id).where(DocumentTag.user_id == user_id)),
    ))
    for tag in tags:
        if tag.id in branch:
            tag.soft_delete()
    await db.flush()
    from .document_structure import sync_folder_structure
    await sync_folder_structure(user_id)
    for document_id in affected_ids:
        await _sync_classified_document(document_id)
    await db.commit()
    await emit_classification(user_id, document_ids=affected_ids, tags_changed=True, list_changed=bool(affected_ids))
    return result.model_copy(update={"deleted": True})


async def assign_tag(scope: AgentManagementScope, document_id: UUID, tag_id: UUID, *, remove: bool = False) -> None:
    db = get_db()
    await lock_tree(scope.user_id)
    await require_tag(scope.user_id, tag_id)
    await document_sharing.document_actor(document_id, scope)
    existing = await db.scalar(select(DocumentTagAssignment).where(
        DocumentTagAssignment.tag_id == tag_id, DocumentTagAssignment.document_id == document_id,
    ))
    if remove:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(DocumentTagAssignment(tag_id=tag_id, document_id=document_id,
            position=await next_position(scope.user_id, tag_id)))
    await _sync_classified_document(document_id)
    await db.commit()
    await emit_classification(scope.user_id, tag_ids=[tag_id], document_ids=[document_id], list_changed=True)


async def move_document(scope: AgentManagementScope, document_id: UUID, tag_id: UUID | None) -> None:
    """Replace only this user's classification, atomically and without writing the document."""
    db = get_db()
    await lock_tree(scope.user_id)
    if tag_id is not None:
        await require_tag(scope.user_id, tag_id)
    await document_sharing.document_actor(document_id, scope)
    own_tags = select(DocumentTag.id).where(DocumentTag.user_id == scope.user_id)
    previous = list(await db.scalars(select(DocumentTagAssignment.tag_id).where(
        DocumentTagAssignment.document_id == document_id, DocumentTagAssignment.tag_id.in_(own_tags),
    )))
    await db.execute(delete(DocumentTagAssignment).where(
        DocumentTagAssignment.document_id == document_id,
        DocumentTagAssignment.tag_id.in_(own_tags),
    ))
    if tag_id is not None:
        db.add(DocumentTagAssignment(tag_id=tag_id, document_id=document_id,
            position=await next_position(scope.user_id, tag_id)))
    await _sync_classified_document(document_id)
    await db.commit()
    await emit_classification(scope.user_id, tag_ids=[*previous, *([tag_id] if tag_id else [])],
        document_ids=[document_id], list_changed=bool(previous) != bool(tag_id))


async def _sync_classified_document(document_id: UUID) -> None:
    from .document_structure import sync_document_structure
    await get_db().flush()
    item = await service.document_record(document_id)
    if item is not None:
        await sync_document_structure(item)


async def list_icons(user_id: int) -> list[DocumentTagIconPublic]:
    icons = await get_db().scalars(select(DocumentTagIcon).where(
        DocumentTagIcon.user_id == user_id,
    ).order_by(func.lower(DocumentTagIcon.name), DocumentTagIcon.id))
    return [DocumentTagIconPublic.model_validate(icon) for icon in icons]


async def upload_icon(user_id: int, data: DocumentTagIconWrite) -> DocumentTagIconPublic:
    db = get_db()
    await lock_tree(user_id)
    icon = await db.scalar(select(DocumentTagIcon).where(
        DocumentTagIcon.user_id == user_id, DocumentTagIcon.data == data.data,
    ))
    if icon is None:
        icon = DocumentTagIcon(user_id=user_id, name=data.name, data=data.data)
        db.add(icon)
        await db.flush()
    result = DocumentTagIconPublic.model_validate(icon)
    await db.commit()
    return result
