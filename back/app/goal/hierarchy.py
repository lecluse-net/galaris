"""Visible Goal branches with inherited classification and stable tree ordering."""

from collections.abc import Collection
from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.sql.selectable import CTE

from app.agent import Agent
from core.user import get_current_user_id

from .models import Goal, GoalCategory


def goal_hierarchy(
    *,
    agent_ids: Collection[int] | None,
    sort_by: Literal["agent", "title"] | None,
    descending: bool,
) -> CTE:
    """Derive category and DFS order before list filters and pagination.

    Only visible ancestors participate. A child whose parent is outside the scope
    remains readable, but neither inherits hidden metadata nor uses its own category.
    Callers outer-join this projection so malformed legacy cycles remain readable
    as unclassified Goals rather than disappearing from the list.
    """
    category = select(GoalCategory.id).where(
        GoalCategory.id == Goal.category_id,
        GoalCategory.created_by == (get_current_user_id() or -1),
        GoalCategory.deleted_at.is_(None),
    ).correlate(Goal).scalar_subquery()
    sort_key = (
        select(func.lower(func.concat_ws(" ", Agent.first_name, Agent.last_name)))
        .where(Agent.id == Goal.agent_id).correlate(Goal).scalar_subquery()
        if sort_by == "agent" else func.lower(Goal.title)
    )
    nodes_query = select(
        Goal.id.label("goal_id"), Goal.parent_goal_id,
        category.label("category_id"),
        func.row_number().over(order_by=(
            sort_key.desc().nullslast() if descending else sort_key.asc().nullslast(),
            func.lower(Goal.title), Goal.id,
        )).label("position"),
    ).where(Goal.deleted_at.is_(None))
    if agent_ids is not None:
        nodes_query = nodes_query.where(
            Goal.agent_id.in_(agent_ids),
            or_(Goal.referrer_agent_id.is_(None), Goal.referrer_agent_id.in_(agent_ids)),
        )
    nodes = nodes_query.cte("visible_goal_nodes")
    parent = nodes.alias("visible_goal_parent")
    roots = select(
        nodes.c.goal_id,
        case((nodes.c.parent_goal_id.is_(None), nodes.c.category_id), else_=None)
        .label("effective_category_id"),
        array([nodes.c.position]).label("sort_path"),
    ).where(~select(parent.c.goal_id).where(parent.c.goal_id == nodes.c.parent_goal_id).exists())
    tree = roots.cte("visible_goal_hierarchy", recursive=True)
    return tree.union_all(select(
        nodes.c.goal_id, tree.c.effective_category_id,
        (tree.c.sort_path + array([nodes.c.position])).label("sort_path"),
    ).select_from(nodes.join(tree, nodes.c.parent_goal_id == tree.c.goal_id)))
