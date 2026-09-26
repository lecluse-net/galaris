"""HTTP contract for descriptive, paginated Lab comparisons."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from .schemas import EvaluationRunRead

ComparisonAxis = Literal["model", "prompt", "parameters"]


class ComparisonItem(BaseModel):
    left_result_id: UUID
    right_result_id: UUID | None
    pairing: Literal["matched", "missing", "ambiguous"]
    name: str | None
    repetition: int
    score_delta: float | None
    cost_delta: float | None
    duration_delta: float | None
    left_score: float | None
    right_score: float | None
    left_verdict: str | None
    right_verdict: str | None
    left_cost: float
    right_cost: float | None
    left_duration: float
    right_duration: float | None
    left_checks: dict[str, Any]
    right_checks: dict[str, Any] | None
    left_judgment: dict[str, Any] | None
    right_judgment: dict[str, Any] | None
    input: Any
    reference: Any
    left_output: Any
    right_output: Any
    left_error: str | None
    right_error: str | None


class RunComparison(BaseModel):
    axis: ComparisonAxis
    comparable: bool
    differences: list[str]
    blockers: list[str]
    left: EvaluationRunRead
    right: EvaluationRunRead
    items: list[ComparisonItem]
    next_offset: int | None
