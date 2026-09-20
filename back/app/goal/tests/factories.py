"""Goal test factories that preserve the production document invariant."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.goal import get_goal_document_store
from app.goal.models import Goal


async def make_goal(
    *,
    title: str,
    description: str,
    agent_id: int,
    tracking_content: str = "",
    **values: Any,
) -> Goal:
    goal_id = uuid4()
    store = get_goal_document_store()
    description_document_id = await store.create(
        goal_id=goal_id,
        owner_agent_id=agent_id,
        kind="description",
        goal_title=title,
        content=description,
    )
    tracking_document_id = await store.create(
        goal_id=goal_id,
        owner_agent_id=agent_id,
        kind="tracking",
        goal_title=title,
        content=tracking_content,
    )
    return Goal(
        id=goal_id,
        title=title,
        description_document_id=description_document_id,
        tracking_document_id=tracking_document_id,
        agent_id=agent_id,
        **values,
    )


__all__ = ["make_goal"]
