"""Automatic Topic/keyword navigation over the live document library."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select

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
    rows = await get_db().execute(select(Document.topic_id, Document.keywords).where(
        or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id)),
        Document.node_kind == "document", Document.document_type.in_(("text", "data")),
        Document.topic_id.is_not(None),
        or_(Document.valid_from.is_(None), Document.valid_from <= now),
        or_(Document.valid_until.is_(None), Document.valid_until > now),
    ))
    groups: dict[UUID, list[list[str]]] = {}
    for topic_id, keywords in rows.tuples():
        if topic_id is not None:
            groups.setdefault(topic_id, []).append(keywords)
    return [DocumentTopicGroup(
        id=identity,
        keywords=sorted({keyword for values in documents for keyword in values}, key=str.casefold),
        document_count=len(documents),
        without_keywords_count=sum(not values for values in documents),
    ) for identity, documents in groups.items()]


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
