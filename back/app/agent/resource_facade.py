"""Governed profile resources for agent runtimes; HTML remains unchanged."""

from __future__ import annotations
from typing import Any, Literal
from sqlalchemy import Select, select
from sqlalchemy.orm import aliased, defer
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


def _profile_query(actor_agent_id: int) -> Select[tuple[Agent, bool]]:
    """Use the shared directory policy, independently of dialogue/admin rights."""
    actor = aliased(Agent)
    return (select(Agent, Agent.avatar.is_not(None))
            .options(defer(Agent.avatar, raiseload=True))
            .where(Agent.deleted_at.is_(None), select(actor.id).where(
                actor.id == actor_agent_id, actor.deleted_at.is_(None)).exists())
            .execution_options(populate_existing=True))


def _profile(agent: Agent, has_avatar: bool) -> dict[str, Any]:
    return {
        "id": agent.id,
        "title": f"{agent.first_name} {agent.last_name}",
        "job_title": agent.job_title,
        "job_description": agent.job_description,
        "personality": agent.personality,
        "media_type": "text/html",
        "content_profile": "rich-text",
        "content_profile_version": 1,
        "resource_uri": f"galaris://agent/{agent.id}",
        "avatar_uri": f"galaris://agent/{agent.id}/avatar" if has_avatar else None,
    }


async def read_agent_resource(agent_id: int, *, actor_agent_id: int) -> dict[str, Any] | None:
    row = (await get_db().execute(_profile_query(actor_agent_id).where(Agent.id == agent_id))).one_or_none()
    return _profile(*row) if row is not None else None


async def read_agent_avatar_resource(agent_id: int, *, actor_agent_id: int) -> tuple[bytes, str] | None:
    """Read the live photo only when the same actor can read the profile."""
    if await read_agent_resource(agent_id, actor_agent_id=actor_agent_id) is None:
        return None
    content = await get_db().scalar(select(Agent.avatar).where(
        Agent.id == agent_id, Agent.deleted_at.is_(None)))
    if content is None:
        return None
    # Older installations can still contain the pre-normalization formats.
    media_type = "image/jpeg"
    if content.startswith(b"\x89PNG"):
        media_type = "image/png"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        media_type = "image/gif"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        media_type = "image/webp"
    return content, media_type


async def list_agent_resources(
    *, actor_agent_id: int, query: str = "", offset: int = 0, limit: int = 50
) -> list[dict[str, Any]]:
    statement = _profile_query(actor_agent_id)
    if query:
        statement = statement.where((Agent.first_name + " " + Agent.last_name).icontains(query, autoescape=True))
    rows = await get_db().execute(statement.order_by(Agent.id).offset(offset).limit(limit))
    return [_profile(*row) for row in rows]
