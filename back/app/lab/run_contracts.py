"""Detached values crossing claim, inference and publication phases."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .schemas import EvaluationMechanism


@dataclass(frozen=True)
class RunClaim:
    run_id: UUID
    token: UUID
    mechanism: EvaluationMechanism
    llm_id: int | None
    judge_llm_id: int | None
    created_by: int | None
    configuration_snapshot: dict[str, Any]
    case_snapshot: dict[str, Any] | None
    phase: str = "execution"
    campaign_id: UUID | None = None
    result_id: UUID | None = None
    actual_output: Any = None
    candidate_error: str | None = None
    judgment_configuration: dict[str, Any] | None = None
    candidate_checks: list[dict[str, Any]] | None = None
    llm_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class ClaimResult:
    processed: int
    work: RunClaim | None = None


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: UUID
    case_snapshot: dict[str, Any]
    actual_output: Any
    score_details: dict[str, Any]
    judge_output: dict[str, Any] | None
    score_percent: float | None
    structured_score_percent: float
    cost: float
    duration: float
    error: str | None
