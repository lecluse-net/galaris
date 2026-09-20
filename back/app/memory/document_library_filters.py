"""Server-side personal classification and document filters."""

from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from .document_tags import list_tags, require_tag
from .models import DocumentTag, DocumentTagAssignment, MemoryItem
from .schemas import DocumentLibraryRequest


async def library_filters(request: DocumentLibraryRequest, user_id: int | None) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if request.document_type is not None:
        filters.append(MemoryItem.document_type == request.document_type)
    assignments = select(DocumentTagAssignment.document_id).join(DocumentTag).where(DocumentTag.user_id == user_id)
    if request.classification != "all":
        classified = MemoryItem.id.in_(assignments)
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
        filters.append(MemoryItem.id.in_(assignments.where(DocumentTag.id.in_(ids))))
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
