"""HTTP contract for descriptive, paginated Lab comparisons."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from .schemas import EvaluationRunRead

ComparisonAxis = Literal["model", "prompt", "parameters"]
ComparisonFocus = Literal["all", "critical", "verdict", "dimension"]


class ComparisonDimension(BaseModel):
    code: str
    pairs: int
    decreased: int
    increased: int
    equal: int
    mean_delta: float


class ComparisonRisks(BaseModel):
    assessed_pairs: int = 0
    introduced_critical: int = 0
    pass_to_fail: int = 0
    dimensions: list[ComparisonDimension] = Field(default_factory=list[ComparisonDimension])


class PairedMetric(BaseModel):
    pairs: int
    left_median: float | None
    right_median: float | None
    median_delta: float | None


class ComparisonPerformance(BaseModel):
    first_output: PairedMetric
    cost: PairedMetric
    duration: PairedMetric
    quality: PairedMetric


class ComparisonSummary(BaseModel):
    cases: int
    observations: int
    matched: int
    missing_left: int
    missing_right: int
    ambiguous: int
    unjudged: int
    failed: int
    increased: int | None
    decreased: int | None
    equal: int | None


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
    introduced_critical: bool | None = None
    pass_to_fail: bool | None = None
    dimension_deltas: dict[str, float] = Field(default_factory=dict[str, float])
    left_first_output_seconds: float | None = None
    right_first_output_seconds: float | None = None


class RunComparison(BaseModel):
    axis: ComparisonAxis
    comparable: bool
    differences: list[str]
    blockers: list[str]
    left: EvaluationRunRead
    right: EvaluationRunRead
    items: list[ComparisonItem]
    next_offset: int | None
    summary: ComparisonSummary
    risks: ComparisonRisks | None = None
    performance: ComparisonPerformance | None = None
