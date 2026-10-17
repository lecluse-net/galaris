"""Find explicit Dataset references in current, accessible native Documents."""

from typing import Any
from sqlalchemy import func, or_, select
from app.agent import AgentManagementScope
from core.database import get_db
from core.authorize import check_privilege
from core.user import get_user_record
from .models import Document, MemoryItem
from .access import human_document_clause, readable_item_for_agents_clause


async def find_dataset_document_usages(uris: tuple[str, ...], actor: AgentManagementScope,
    offset: int, limit: int) -> dict[str, Any]:
    required = ["MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN"]
    if not await check_privilege(await get_user_record(actor.user_id), required, get_db()):
        return {"total": 0, "items": []}
    query = select(Document, MemoryItem).join(MemoryItem, MemoryItem.id == Document.memory_item_id).where(
        Document.document_type == "html",
        or_(human_document_clause(actor.user_id), readable_item_for_agents_clause(actor.agent_ids)),
        or_(*(Document.content.contains(uri, autoescape=True) for uri in uris),
            *(MemoryItem.metadata_["dataset_attachments"].contains([uri]) for uri in uris)))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    rows: list[tuple[Document, MemoryItem]] = list((await get_db().execute(query.order_by(Document.id).offset(offset).limit(limit))).tuples().all()) if limit else []
    return {"total": total, "items": [{"id": f"document:{doc.id}", "label": item.title,
        "relation": "document_reference", "url": f"/documents?document_id={doc.id}",
        "uri": f"document://{doc.id}", "last_used_at": None} for doc, item in rows]}
