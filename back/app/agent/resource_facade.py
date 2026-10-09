"""Governed profile resources for agent runtimes; HTML remains unchanged."""

from __future__ import annotations
from typing import Any, Literal
from sqlalchemy import select
from core.database import get_db
from .models import Agent


async def require_delegated_resource_access(
    requester_agent_id: int, agent_id: int, uri: str, access: Literal["read", "write"],
) -> None:
    """Require existing resource grants for both the delegator and the recipient."""
    from app.file_share import ResourceContext, resource_accessible, resource_info
    await resource_info(ResourceContext(agent_id=requester_agent_id, runtime="internal"), uri)
    if not await resource_accessible(ResourceContext(agent_id=agent_id, runtime="internal"), uri, access):
        raise PermissionError("The recipient lacks the required resource capability.")


async def read_agent_resource(agent_id: int, *, actor_agent_id: int) -> dict[str, Any] | None:
    if agent_id != actor_agent_id:
        return None
    agent = await get_db().scalar(select(Agent).where(
        Agent.id == agent_id, Agent.deleted_at.is_(None),
    ).execution_options(populate_existing=True))
    if agent is None:
        return None
    return {
        "id": agent.id,
        "title": f"{agent.first_name} {agent.last_name}",
        "job_title": agent.job_title,
        "job_description": agent.job_description,
        "personality": agent.personality,
        "media_type": agent.profile_media_type,
        "content_profile": "rich-text",
        "content_profile_version": 1,
        "resource_uri": f"galaris://agent/{agent.id}",
    }


async def list_agent_resources(
    *, actor_agent_id: int, query: str = "", offset: int = 0, limit: int = 50
) -> list[dict[str, Any]]:
    if offset > 0 or limit < 1:
        return []
    profile = await read_agent_resource(actor_agent_id, actor_agent_id=actor_agent_id)
    if profile is None or query.casefold() not in str(profile["title"]).casefold():
        return []
    return [profile]
