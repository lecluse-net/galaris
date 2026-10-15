"""Public bounded Document selection for typed reference fields."""

from typing import Any
from app.agent import AgentManagementScope
from core.user import HumanActor
from core.database import get_db
from sqlalchemy import or_, select

from .models import MemoryItem
from .access import human_document_clause, readable_item_clause, readable_item_for_agents_clause


async def list_selectable_documents(actor: int | HumanActor | AgentManagementScope, *, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    if isinstance(actor, int):
        allowed = readable_item_clause(actor)
    elif isinstance(actor, AgentManagementScope):
        allowed = or_(human_document_clause(actor.user_id), readable_item_for_agents_clause(actor.agent_ids))
    else:
        allowed = human_document_clause(actor.user_id)
    statement = select(MemoryItem).where(MemoryItem.node_kind == "document", MemoryItem.document_type != "dataset", allowed)
    if query:
        statement = statement.where(MemoryItem.title.icontains(query, autoescape=True))
    rows = await get_db().scalars(statement.order_by(MemoryItem.created_at.desc(), MemoryItem.id).limit(limit))
    return [{"value": f"document://{entry.id}", "label": entry.title} for entry in rows]
