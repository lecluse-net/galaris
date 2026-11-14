"""Agent/keyword navigation derives from readable document ownership."""

from datetime import datetime, timezone

from sqlalchemy import Text, func, or_, select
from pydantic import TypeAdapter

from app.agent import Agent, AgentManagementScope
from core.database import get_db

from .access import human_document_clause, readable_item_for_agents_clause
from .models import Document
from .query_policy import prepare_document_read
from .schemas import DocumentAgentBranch


async def catalog(scope: AgentManagementScope) -> list[DocumentAgentBranch]:
    await prepare_document_read()
    now = datetime.now(timezone.utc)
    title = func.coalesce(func.nullif(func.trim(func.concat(Agent.first_name, " ", Agent.last_name)), ""), Agent.code, "")
    visible = select(Document.owner_agent_id, Document.keywords).where(
            or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id)),
            Document.node_kind == "document", Document.document_type.in_(("text", "data")),
            Document.owner_agent_id.is_not(None),
            or_(Document.valid_from.is_(None), Document.valid_from <= now),
            or_(Document.valid_until.is_(None), Document.valid_until > now),
        ).cte("owner_visible_documents").prefix_with("MATERIALIZED")
    counts = select(visible.c.owner_agent_id, func.count().label("document_count"),
        func.count().filter(func.jsonb_array_length(visible.c.keywords) == 0).label("without_keywords_count"))
    counts = counts.group_by(visible.c.owner_agent_id).subquery()
    words = select(visible.c.owner_agent_id, func.jsonb_array_elements_text(visible.c.keywords).label("keyword")).subquery()
    keywords = select(words.c.owner_agent_id, func.jsonb_agg(words.c.keyword.distinct()).cast(Text).label("keywords"))
    keywords = keywords.group_by(words.c.owner_agent_id).subquery()
    rows = await get_db().execute(select(counts, title.label("title"), Agent.avatar.is_not(None).label("has_avatar"), keywords.c.keywords)
        .outerjoin(Agent, Agent.id == counts.c.owner_agent_id)
        .outerjoin(keywords, keywords.c.owner_agent_id == counts.c.owner_agent_id))
    adapter = TypeAdapter(list[str])
    groups = [DocumentAgentBranch(id=row.owner_agent_id, title=row.title, has_avatar=row.has_avatar,
        keywords=sorted(adapter.validate_json(row.keywords or "[]"), key=str.casefold),
        document_count=row.document_count, without_keywords_count=row.without_keywords_count) for row in rows]
    return sorted(groups, key=lambda branch: (branch.title.casefold(), branch.id))
