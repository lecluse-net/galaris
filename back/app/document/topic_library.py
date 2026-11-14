"""Automatic Topic/keyword navigation over the live document library."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Text, func, or_, select
from pydantic import TypeAdapter

from app.agent import AgentManagementScope
from core.database import get_db
from core import websocket

from .access import human_document_clause, readable_item_for_agents_clause
from .models import Document
from .query_policy import prepare_document_read
from .schemas import DocumentTopicGroup, DocumentTopicMove


async def catalog(scope: AgentManagementScope) -> list[DocumentTopicGroup]:
    """Read only grouping metadata, never document bodies or history."""
    await prepare_document_read()
    now = datetime.now(timezone.utc)
    visible = select(Document.topic_id, Document.keywords).where(
        or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id)),
        Document.node_kind == "document", Document.document_type.in_(("text", "data")),
        Document.topic_id.is_not(None),
        or_(Document.valid_from.is_(None), Document.valid_from <= now),
        or_(Document.valid_until.is_(None), Document.valid_until > now),
    ).cte("topic_visible_documents").prefix_with("MATERIALIZED")
    counts = select(visible.c.topic_id, func.count().label("document_count"),
        func.count().filter(func.jsonb_array_length(visible.c.keywords) == 0).label("without_keywords_count"))
    counts = counts.group_by(visible.c.topic_id).subquery()
    words = select(visible.c.topic_id, func.jsonb_array_elements_text(visible.c.keywords).label("keyword")).subquery()
    keywords = select(words.c.topic_id, func.jsonb_agg(words.c.keyword.distinct()).cast(Text).label("keywords"))
    keywords = keywords.group_by(words.c.topic_id).subquery()
    rows = await get_db().execute(select(counts, keywords.c.keywords).outerjoin(keywords, counts.c.topic_id == keywords.c.topic_id))
    adapter = TypeAdapter(list[str])
    return [DocumentTopicGroup(
        id=row.topic_id,
        keywords=sorted(adapter.validate_json(row.keywords or "[]"), key=str.casefold),
        document_count=row.document_count,
        without_keywords_count=row.without_keywords_count,
    ) for row in rows]


async def move(identity: UUID, data: DocumentTopicMove, scope: AgentManagementScope) -> None:
    from .topic_assignment import change_assignment
    from .lifecycle import notify_document

    await change_assignment(identity, scope, topic_id=data.topic_id,
        expected_topic_id=data.expected_topic_id, expected_lock_version=data.expected_lock_version,
        keyword_move=(data.source_keyword, data.keyword), clear_keywords=data.clear_keywords)
    await get_db().commit()
    await websocket.emit("document", "update", {"id": str(identity), "node_kind": "document"}, None)
    await notify_document(identity, "index")
    await notify_document(identity, "update")
