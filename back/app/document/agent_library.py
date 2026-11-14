"""Agent/keyword navigation derives from readable document ownership."""

from datetime import datetime, timezone

from sqlalchemy import func, or_, select

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
    rows = await get_db().execute(select(Document.owner_agent_id, title, Document.keywords, Agent.avatar.is_not(None))
        .outerjoin(Agent, Agent.id == Document.owner_agent_id).where(
            or_(readable_item_for_agents_clause(scope.agent_ids), human_document_clause(scope.user_id)),
            Document.node_kind == "document", Document.document_type.in_(("text", "data")),
            Document.owner_agent_id.is_not(None),
            or_(Document.valid_from.is_(None), Document.valid_from <= now),
            or_(Document.valid_until.is_(None), Document.valid_until > now),
        ))
    groups: dict[int, DocumentAgentBranch] = {}
    keywords_by_owner: dict[int, set[str]] = {}
    for identity, label, keywords, has_avatar in rows.tuples():
        if identity is None:
            continue
        branch = groups.setdefault(identity, DocumentAgentBranch(id=identity, title=str(label), has_avatar=bool(has_avatar),
            keywords=[], document_count=0, without_keywords_count=0))
        branch.document_count += 1
        branch.without_keywords_count += int(not keywords)
        keywords_by_owner.setdefault(identity, set()).update(keywords)
    for identity, branch in groups.items():
        branch.keywords = sorted(keywords_by_owner[identity], key=str.casefold)
    return sorted(groups.values(), key=lambda branch: (branch.title.casefold(), branch.id))
