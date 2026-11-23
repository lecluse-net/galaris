"""Document MCP ownership limits, applied in addition to resource ACLs."""

from uuid import UUID

from sqlalchemy import select

from app.services.facade import administration_scope
from core.database import get_db

from .models import Document


async def require_document_tool_scope(agent_id: int, document_id: UUID | None = None) -> None:
    scope = await administration_scope(agent_id, "document")
    scope.require_administration()
    if document_id is None:
        return
    row = (await get_db().execute(select(Document.owner_agent_id).where(
        Document.id == document_id, Document.node_kind == "document",
    ))).one_or_none()
    # Human ownership remains governed by the document's ACL.
    if row is None or (row.owner_agent_id is not None and not scope.allows(row.owner_agent_id)):
        raise PermissionError("Document not found in the current Document scope.")
