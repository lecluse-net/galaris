"""Read cost evidence without loading prompts, model output or parent task totals."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.sql.selectable import Subquery

from core.database import get_db
from .models import LLMCall, LLMCallCost
from .cost_accounting import CallCost, CostSummary, call_cost, summarize_costs


def _cost_rows() -> Subquery:
    fields = ("id", "task_id", "conversation_round_id", "status", "purpose", "cost",
              "inference_cost", "cost_estimated", "is_subscription", "correlation_ref")
    retained = select(*(getattr(LLMCallCost, name) for name in fields), LLMCallCost.evidence.label("usage"))
    historical = select(*(getattr(LLMCall, name) for name in fields), LLMCall.usage).where(
        ~select(LLMCallCost.id).where(LLMCallCost.id == LLMCall.id).exists())
    return retained.union_all(historical).subquery("physical_costs")


async def task_cost_evidence(task_ids: tuple[UUID, ...]) -> dict[UUID, list[CallCost]]:
    grouped: dict[UUID, list[CallCost]] = defaultdict(list)
    if not task_ids:
        return grouped
    source = _cost_rows()
    columns = (source.c.id, source.c.status, source.c.purpose, source.c.cost,
               source.c.inference_cost, source.c.cost_estimated, source.c.is_subscription, source.c.usage)
    direct = select(source.c.task_id, *columns).where(source.c.task_id.in_(task_ids))
    from app.conversation import ConversationTaskLink
    from .purposes import LLMCallPurpose

    candidate_rounds = select(ConversationTaskLink.round_id).where(ConversationTaskLink.task_id.in_(task_ids))
    unique_rounds = (select(ConversationTaskLink.round_id)
        .where(ConversationTaskLink.round_id.in_(candidate_rounds))
        .group_by(ConversationTaskLink.round_id)
        .having(func.count(func.distinct(ConversationTaskLink.task_id)) == 1))
    preparations = (select(ConversationTaskLink.task_id, *columns)
        .join(source, source.c.conversation_round_id == ConversationTaskLink.round_id)
        .where(ConversationTaskLink.task_id.in_(task_ids), ConversationTaskLink.round_id.in_(unique_rounds),
               source.c.task_id.is_(None), source.c.purpose == LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE.value)
        .distinct())
    rows = (await get_db().execute(direct.union_all(preparations))).mappings()
    for row in rows:
        grouped[row["task_id"]].append(call_cost(call_id=row["id"], status=row["status"],
            purpose=row["purpose"], cost=row["cost"], inference_cost=row["inference_cost"],
            cost_estimated=row["cost_estimated"], is_subscription=row["is_subscription"], usage=row["usage"]))
    return grouped


def costs_by_purpose(calls: list[CallCost]) -> dict[str, CostSummary]:
    groups: dict[str, list[CallCost]] = defaultdict(list)
    for row in calls:
        groups[row.purpose or "unknown"].append(row)
    return {purpose: summarize_costs(rows) for purpose, rows in sorted(groups.items())}


async def correlated_cost_evidence(prefix: str) -> list[CallCost]:
    source = _cost_rows()
    rows = (await get_db().execute(select(source).where(source.c.correlation_ref.startswith(prefix)))).mappings()
    return [call_cost(call_id=row["id"], status=row["status"], purpose=row["purpose"],
        cost=row["cost"], inference_cost=row["inference_cost"], cost_estimated=row["cost_estimated"],
        is_subscription=row["is_subscription"], usage=row["usage"]) for row in rows]
