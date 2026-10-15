"""Retained references in tool traces; this is evidence, not a dependency registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from sqlalchemy import String, cast, func, or_, select
from core.database import get_db
from core.authorize import check_privilege
from core.user import get_user_record
from .models import LLMCall

if TYPE_CHECKING:
    from app.agent import AgentManagementScope


async def find_dataset_agent_usages(uris: tuple[str, ...], actor: AgentManagementScope, offset: int, limit: int) -> dict[str, Any]:
    if not await check_privilege(await get_user_record(actor.user_id), "AGENT_ACCESS", get_db()):
        return {"total": 0, "items": []}
    from app.agent import Agent

    query = select(Agent.id, Agent.first_name, Agent.last_name, Agent.code, func.max(LLMCall.created_at).label("last_used_at"))
    query = query.join(LLMCall, LLMCall.agent_id == Agent.id).where(or_(
        *(cast(LLMCall.tool_calls, String).contains(uri, autoescape=True) for uri in uris)))
    if actor.agent_ids is not None:
        query = query.where(Agent.id.in_(actor.agent_ids))
    query = query.group_by(Agent.id)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    items: list[dict[str, Any]] = []
    if limit:
        rows = (await get_db().execute(query.order_by(func.max(LLMCall.created_at).desc(), Agent.id).offset(offset).limit(limit))).all()
        items = [{"id": f"agent:{row.id}", "label": f"{row.first_name} {row.last_name}".strip() or row.code,
            "relation": "agent_trace", "url": f"/agent/{row.id}",
            "last_used_at": row.last_used_at.isoformat()} for row in rows]
    return {"total": total, "items": items}
