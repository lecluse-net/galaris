"""Governed profile resources for agent runtimes; HTML remains unchanged."""

from __future__ import annotations
from typing import Any
from core.database import get_db
from .models import Agent


async def read_agent_resource(agent_id: int, *, actor_agent_id: int) -> dict[str, Any] | None:
    if agent_id != actor_agent_id:
        return None
    agent = await get_db().get(Agent, agent_id)
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
