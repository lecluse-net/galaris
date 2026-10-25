"""A causal Task tree is costed from physical calls, never summed parent rollups."""

from typing import Literal
from collections.abc import Collection
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select

from core.database import get_db
from app.llm.facade import CostSummary, costs_by_purpose, summarize_costs, task_cost_evidence
from .models import Task


class TaskCostReport(BaseModel):
    scope: Literal["recorded_calls"] = "recorded_calls"
    task_uri: str
    tasks: int
    tasks_without_calls: int
    restricted: bool
    summary: CostSummary
    by_purpose: dict[str, CostSummary]
    # Task SUCCESS is orchestration state, not an independent business verifier.
    verified_success: bool | None = None
    cost_per_success: float | None = None


async def cost_report(task_id: UUID, agent_ids: Collection[int] | None) -> TaskCostReport:
    lineage = select(Task.id).where(Task.id == task_id).cte("cost_lineage", recursive=True)
    lineage = lineage.union(select(Task.id).join(lineage, or_(
        Task.parent_id == lineage.c.id, Task.source_task_id == lineage.c.id)))
    rows = (await get_db().execute(select(Task.id, Task.agent_id)
        .where(Task.id.in_(select(lineage.c.id)))
        .execution_options(include_historized=True))).all()
    allowed = tuple(identity for identity, agent in rows if agent_ids is None or agent in agent_ids)
    evidence = await task_cost_evidence(allowed)
    calls = [call for group in evidence.values() for call in group]
    return TaskCostReport(task_uri=f"galaris://task/{task_id}", tasks=len(allowed),
        tasks_without_calls=sum(not evidence.get(identity) for identity in allowed),
        restricted=len(rows) != len(allowed), summary=summarize_costs(calls),
        by_purpose=costs_by_purpose(calls))
