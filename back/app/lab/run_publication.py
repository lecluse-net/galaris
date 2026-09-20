"""Fence candidate and judgment publication against lease loss and cancellation."""

from uuid import UUID
from datetime import datetime, timezone
from typing import cast
from dataclasses import asdict

from sqlalchemy import select
from core.database import get_db
from .models import LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult
from .run_contracts import CaseEvaluation, RunClaim


async def lock_owned_run(run_id: UUID, token: UUID) -> LabEvaluationRun | None:
    run = await get_db().scalar(
        select(LabEvaluationRun)
        .where(LabEvaluationRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None or run.lease_token != token or run.status != "running":
        await get_db().rollback()
        return None
    return run


async def finish_run(run: LabEvaluationRun) -> None:
    results = list(
        (
            await get_db().scalars(
                select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run.id)
            )
        ).all()
    )
    run.completed_cases = len(results)
    judged = [row for row in results if row.score_percent is not None]
    run.score_percent = (
        sum(cast(float, row.score_percent) for row in judged) / len(judged) if judged else None
    )
    run.structured_score_percent = (
        sum(row.structured_score_percent for row in results) / len(results) if results else None
    )
    errors = sum(bool(row.error) for row in results)
    incomplete = len(results) < run.total_cases or any(row.score_percent is None for row in results)
    run.status = (
        "cancelled"
        if run.cancel_requested
        else "partial"
        if run.stop_reason == "budget_exhausted"
        else "failed"
        if results and errors == len(results)
        else "partial"
        if errors or incomplete
        else "completed"
    )
    run.phase = "finished"
    run.finished_at = datetime.now(timezone.utc)
    run.lease_token = None
    run.lease_expires_at = None
    campaign = await get_db().scalar(
        select(LabJudgmentCampaign)
        .where(LabJudgmentCampaign.run_id == run.id)
        .order_by(LabJudgmentCampaign.sequence.desc())
        .limit(1)
    )
    if campaign is not None and campaign.status in {"queued", "running"}:
        campaign.status = run.status
        campaign.finished_at = run.finished_at
    await get_db().commit()


async def finish_owned_run(run_id: UUID, token: UUID) -> None:
    run = await lock_owned_run(run_id, token)
    if run is not None:
        await finish_run(run)


async def publish_case(run_id: UUID, token: UUID, result: CaseEvaluation) -> None:
    run = await lock_owned_run(run_id, token)
    if run is None:
        return
    existing = await get_db().scalar(
        select(LabEvaluationRunCase.id).where(
            LabEvaluationRunCase.run_id == run_id,
            LabEvaluationRunCase.case_snapshot["id"].astext == str(result.case_id),
            LabEvaluationRunCase.repetition == int(result.case_snapshot.get("repetition", 1)),
        )
    )
    if existing is None:
        get_db().add(
            LabEvaluationRunCase(
                run_id=run_id,
                repetition=int(result.case_snapshot.get("repetition", 1)),
                **asdict(result),
            )
        )
        run.completed_cases += 1
        run.candidate_cost += result.cost
        run.cost += result.cost
    run.lease_token = None
    run.lease_expires_at = None
    await get_db().flush()
    if run.cancel_requested:
        await finish_run(run)
    else:
        if run.completed_cases >= run.total_cases:
            run.phase = "judgment"
        await get_db().commit()


async def publish_judgment(work: RunClaim, evaluation: CaseEvaluation) -> None:
    run = await lock_owned_run(work.run_id, work.token)
    if run is None:
        return
    if work.campaign_id is None or work.result_id is None:
        raise ValueError("Judgment publication requires a campaign and candidate result")
    existing = await get_db().scalar(
        select(LabJudgmentResult.id).where(
            LabJudgmentResult.campaign_id == work.campaign_id,
            LabJudgmentResult.result_id == work.result_id,
        )
    )
    if existing is None:
        verdict = str(evaluation.score_details.get("verdict", "inconclusive"))
        get_db().add(
            LabJudgmentResult(
                campaign_id=work.campaign_id,
                result_id=work.result_id,
                status=str(evaluation.score_details["judge_status"]),
                verdict=verdict,
                output=evaluation.judge_output,
                score_percent=evaluation.score_percent,
                cost=evaluation.cost,
                duration=evaluation.duration,
                error=evaluation.error,
            )
        )
        candidate = await get_db().get(LabEvaluationRunCase, work.result_id)
        if candidate is None:
            raise LookupError("Candidate result disappeared")
        candidate.judge_output = evaluation.judge_output
        candidate.score_percent = evaluation.score_percent
        candidate.verdict = verdict
        candidate.score_details = {**candidate.score_details, **evaluation.score_details}
        run.judged_cases += 1
        run.judge_cost += evaluation.cost
        run.cost += evaluation.cost
    run.lease_token = None
    run.lease_expires_at = None
    await get_db().flush()
    if run.cancel_requested or run.judged_cases >= run.completed_cases:
        await finish_run(run)
    else:
        await get_db().commit()
