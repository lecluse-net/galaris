"""Whole-run economic evidence, including failed and unpublished paid attempts."""

from math import isclose
from typing import Literal, Any, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from core.database import get_db
from app.llm.facade import CallCost, CostSummary, correlated_cost_evidence, summarize_costs
from .models import LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult


class RunEconomics(BaseModel):
    scope: Literal["isolated_mechanism"] = "isolated_mechanism"
    observations: int
    expected_observations: int
    benchmark_successes: int
    failed_candidates: int
    unverified: int
    candidate: CostSummary
    judge: CostSummary
    cost_per_success: float | None
    unavailable_reason: str | None


def comparable_cost(details: dict[str, Any], recorded: float) -> bool:
    try:
        summary = CostSummary.model_validate(details.get("candidate_cost_accounting"))
    except ValidationError:
        return False
    return (summary.quality in {"exact", "estimated"} and summary.total_cost is not None
            and isclose(summary.total_cost, recorded, abs_tol=1e-12))


def _snapshot_entries(value: object, identity: UUID, recorded: float, status: str) -> list[CallCost]:
    try:
        snapshot = CostSummary.model_validate(value)
    except ValidationError:
        snapshot = None
    if (snapshot is not None and isclose(snapshot.recorded_cost, recorded, abs_tol=1e-12)
            and (snapshot.entries or snapshot.total_cost == 0)):
        if snapshot.entries:
            return snapshot.entries
        quality = snapshot.quality
    else:
        quality = "unknown"
    # A historical numeric total is retained but cannot establish complete cost coverage.
    return [CallCost(call_id=identity, status=status, cost=recorded, inference_cost=None,
                     quality=quality, inference_quality="unknown", source="result_snapshot")]


async def economics(run: LabEvaluationRun) -> RunEconomics:
    Result = LabEvaluationRunCase
    rows = (await get_db().execute(select(
        Result.id, Result.cost, Result.error, Result.verdict, Result.score_percent,
        Result.score_details["candidate_status"].astext.label("candidate_status"),
        Result.score_details["judge_status"].astext.label("judge_status"),
        Result.score_details["checks"].label("checks"),
        Result.score_details["candidate_cost_accounting"].label("accounting"),
        Result.judge_output["rubric_version"].astext.label("rubric"),
        Result.judge_output["critical_failures"].label("critical_failures"),
    ).where(Result.run_id == run.id))).mappings().all()
    candidate: dict[UUID, CallCost] = {}
    successes = failed = unverified = 0
    for row in rows:
        entries = _snapshot_entries(row["accounting"], row["id"], row["cost"],
                                     "error" if row["error"] else "completed")
        candidate.update((entry.call_id, entry) for entry in entries)
        if row["error"] or row["candidate_status"] == "failed":
            failed += 1
        elif (row["candidate_status"] == "completed" and row["judge_status"] == "completed"
              and row["rubric"] and row["score_percent"] is not None
              and isinstance(row["checks"], list) and row["checks"]
              and isinstance(row["critical_failures"], list)
              and row["verdict"] in {"pass", "fail"}):
            checks = row["checks"]
            if (row["verdict"] == "pass" and not row["critical_failures"]
                    and all(isinstance(check, dict) and cast(dict[str, Any], check).get("passed") is True for check in checks)):
                successes += 1
            elif row["verdict"] == "pass":
                unverified += 1
        else:
            unverified += 1

    judgments = (await get_db().execute(select(
        LabJudgmentResult.id, LabJudgmentResult.cost, LabJudgmentResult.status,
        LabJudgmentResult.output["_cost_accounting"].label("accounting"),
    ).join(LabJudgmentCampaign, LabJudgmentCampaign.id == LabJudgmentResult.campaign_id)
      .where(LabJudgmentCampaign.run_id == run.id))).mappings().all()
    judge: dict[UUID, CallCost] = {}
    for row in judgments:
        entries = _snapshot_entries(row["accounting"], row["id"], row["cost"],
                                    "completed" if row["status"] in {"completed", "skipped"} else "error")
        judge.update((entry.call_id, entry) for entry in entries)

    for stage, target in (("candidate", candidate), ("judge", judge)):
        # Persisted snapshots survive trace cleanup; live traces also retain calls
        # paid by a worker that lost its lease before it could publish a result.
        for entry in await correlated_cost_evidence(f"lab://run/{run.id}/{stage}/"):
            # A later authoritative receipt can refine a terminal estimate or
            # unknown amount. The retained register governs those refinements.
            target[entry.call_id] = entry
    candidate_summary = summarize_costs(candidate.values())
    judge_summary = summarize_costs(judge.values())
    reason = ("no_success" if not successes else "incomplete_execution" if len(rows) != run.total_cases
              or run.status not in {"completed", "partial", "failed", "cancelled"}
              else "incomplete_verification" if unverified else "incomplete_costs"
              if candidate_summary.total_cost is None else None)
    return RunEconomics(observations=len(rows), expected_observations=run.total_cases,
        benchmark_successes=successes, failed_candidates=failed, unverified=unverified,
        candidate=candidate_summary, judge=judge_summary,
        cost_per_success=(candidate_summary.total_cost / successes
                          if reason is None and candidate_summary.total_cost is not None else None),
        unavailable_reason=reason)
