"""Bounded Goal awareness for the agent's current text conversation."""

from sqlalchemy import select

from app.agent.contracts import AgentContextContribution, AgentContextRequest
from core.database import get_db
from .models import Goal, GoalStatus


_CONVERSATION_GOAL_LIMIT = 12


async def conversation_goal_context(request: AgentContextRequest) -> AgentContextContribution:
    if request.conversation_round_id is None:
        return AgentContextContribution()
    rows = (await get_db().execute(
        select(Goal.id, Goal.title, Goal.status, Goal.next_cycle_at)
        .where(
            Goal.agent_id == request.agent.id,
            Goal.status == GoalStatus.ACTIVE,
            Goal.deleted_at.is_(None),
        )
        .order_by(Goal.next_cycle_at.asc().nulls_last(), Goal.id)
        .limit(_CONVERSATION_GOAL_LIMIT + 1)
    )).all()
    return AgentContextContribution(turn_data={"active_goals": {
        "items": [
            {
                "uri": f"galaris://goal/{row.id}",
                "title": row.title,
                "status": row.status.value,
                "next_cycle_at": row.next_cycle_at.isoformat() if row.next_cycle_at else None,
            }
            for row in rows[:_CONVERSATION_GOAL_LIMIT]
        ],
        "truncated": len(rows) > _CONVERSATION_GOAL_LIMIT,
    }})
