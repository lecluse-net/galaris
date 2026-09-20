"""Private document icons: read access suffices; content and classification stay unchanged."""

from uuid import UUID

from sqlalchemy import or_, select

from app.agent import AgentManagementScope
from core.database import get_db

from . import document_sharing, document_tags
from .access import human_document_clause, readable_item_for_agents_clause
from .models import DocumentIcon, MemoryItem
from .schemas import DocumentIconWrite


async def resolve(scope: AgentManagementScope, document_ids: list[UUID]) -> dict[UUID, str | None]:
    rows = await get_db().execute(select(MemoryItem.id, DocumentIcon.icon).outerjoin(DocumentIcon,
        (DocumentIcon.document_id == MemoryItem.id) & (DocumentIcon.user_id == scope.user_id),
    ).where(MemoryItem.id.in_(document_ids), MemoryItem.node_kind == "document", or_(
        readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id),
    )))
    # Existing folder choices fall back to the document icon without rewriting user data.
    return {identity: None if icon and icon.startswith(("folder:", "folder-open:")) else icon for identity, icon in rows}


async def save(scope: AgentManagementScope, document_id: UUID, data: DocumentIconWrite) -> DocumentIconWrite:
    db = get_db()
    await document_tags.lock_tree(scope.user_id)
    await document_sharing.document_actor(document_id, scope)
    row = await db.scalar(select(DocumentIcon).where(
        DocumentIcon.user_id == scope.user_id, DocumentIcon.document_id == document_id,
    ))
    if row is None:
        row = DocumentIcon(user_id=scope.user_id, document_id=document_id)
        db.add(row)
    row.icon = data.icon
    await db.commit()
    return data
