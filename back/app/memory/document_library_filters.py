"""Server-side personal classification and document filters."""

from uuid import UUID
from sqlalchemy import Select, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from .document_tags import list_tags, require_tag
from .models import DocumentNesting, DocumentTag, DocumentTagAssignment, MemoryItem
from .schemas import DocumentLibraryRequest


async def library_filters(request: DocumentLibraryRequest, user_id: int | None, visible_ids: Select[tuple[UUID]]) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if request.document_type is not None:
        filters.append(MemoryItem.document_type == request.document_type)
    assignments = select(DocumentTagAssignment.document_id).join(DocumentTag).where(DocumentTag.user_id == user_id)
    nesting = select(DocumentNesting.document_id).where(
        DocumentNesting.user_id == user_id, DocumentNesting.parent_document_id.in_(visible_ids),
    )
    # A personal folder or a visible document parent already proves that every
    # result is classified. Rechecking global nesting membership multiplies joins.
    explicit_branch = request.tag_id is not None or request.parent_document_id is not None
    if request.classification == "unclassified" or (request.classification == "classified" and not explicit_branch):
        classified = or_(MemoryItem.id.in_(assignments), MemoryItem.id.in_(nesting))
        filters.append(classified if request.classification == "classified" else ~classified)
    if request.tag_id is not None:
        if user_id is None:
            raise ValueError("A personal tag requires a user")
        await require_tag(user_id, request.tag_id)
        ids = {request.tag_id}
        if request.include_descendants:
            tags = await list_tags(user_id)
            while True:
                children = {tag.id for tag in tags if tag.parent_id in ids} - ids
                if not children:
                    break
                ids.update(children)
        folder_documents = assignments.where(DocumentTag.id.in_(ids))
        if request.include_descendants:
            subtree = folder_documents.where(DocumentTagAssignment.document_id.in_(visible_ids)).cte(recursive=True)
            subtree = subtree.union_all(select(DocumentNesting.document_id).join(
                subtree, DocumentNesting.parent_document_id == subtree.c.document_id,
            ).where(DocumentNesting.user_id == user_id, DocumentNesting.document_id.in_(visible_ids)))
            filters.append(MemoryItem.id.in_(select(subtree.c.document_id)))
        else:
            filters.append(MemoryItem.id.in_(folder_documents))
    if request.parent_document_id is not None:
        from core.database import get_db
        from .service import MemoryNotFoundError

        if user_id is None or await get_db().scalar(visible_ids.where(visible_ids.selected_columns[0] == request.parent_document_id)) is None:
            raise MemoryNotFoundError("Document not found")
        children = select(DocumentNesting.document_id).where(
            DocumentNesting.user_id == user_id, DocumentNesting.parent_document_id == request.parent_document_id,
            DocumentNesting.document_id.in_(visible_ids),
        )
        if request.include_descendants:
            descendants = children.cte(recursive=True)
            descendants = descendants.union_all(select(DocumentNesting.document_id).join(
                descendants, DocumentNesting.parent_document_id == descendants.c.document_id,
            ).where(DocumentNesting.user_id == user_id, DocumentNesting.document_id.in_(visible_ids)))
            filters.append(MemoryItem.id.in_(select(descendants.c.document_id)))
        else:
            filters.append(MemoryItem.id.in_(children))
    if request.owner_kind is not None:
        owner = MemoryItem.owner_agent_id if request.owner_kind == "agent" else MemoryItem.owner_user_id
        filters.append(owner == request.owner if request.owner is not None else owner.is_not(None))
    for column, start, end in (
        (MemoryItem.created_at, request.created_from, request.created_until),
        (func.coalesce(MemoryItem.updated_at, MemoryItem.created_at), request.updated_from, request.updated_until),
    ):
        if start is not None:
            filters.append(column >= start)
        if end is not None:
            filters.append(column < end)
    return filters
