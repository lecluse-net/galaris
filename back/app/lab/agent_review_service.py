"""Attributed agent assessments displayed alongside canonical benchmark results."""

from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from .models import LabAgentReview, LabEvaluationRunCase
from .schemas import AgentReviewRead


async def list_run_reviews(run_id: UUID) -> list[AgentReviewRead]:
    rows = await get_db().scalars(
        select(LabAgentReview)
        .join(LabEvaluationRunCase, LabEvaluationRunCase.id == LabAgentReview.result_id)
        .where(LabEvaluationRunCase.run_id == run_id)
        .order_by(LabAgentReview.created_at, LabAgentReview.id)
    )
    return [AgentReviewRead.model_validate(row) for row in rows]
