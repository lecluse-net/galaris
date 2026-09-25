"""Claim one candidate or judgment item; inference receives detached values."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

from sqlalchemy import or_, select
from core.database import get_db
from .mechanism_registry import MECHANISMS
from .mechanism_rubrics import get_rubric
from .models import (
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabJudgmentCampaign,
    LabJudgmentResult,
)
from .schemas import EvaluationMechanism
from .run_contracts import ClaimResult, RunClaim

_LEASE_SECONDS = 900


async def claim_next_run() -> ClaimResult:
    now = datetime.now(timezone.utc)
    run = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset, LabEvaluationDataset.id == LabEvaluationRun.dataset_id)
        .where(
            LabEvaluationDataset.mechanism.in_(tuple(MECHANISMS)),
            LabEvaluationRun.status.in_({"queued", "running"}),
            or_(
                LabEvaluationRun.lease_expires_at.is_(None),
                LabEvaluationRun.lease_expires_at <= now,
            ),
        )
        .order_by(LabEvaluationRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return ClaimResult(0)
    if run.requester_action is not None:
        from app.tools import McpToolContext
        from .mcp_access import authorize

        try:
            if run.requester_agent_id is None:
                raise PermissionError("The requesting agent was removed.")
            await authorize(McpToolContext(run.requester_agent_id, "internal"), run.requester_action or "lab_run_start")
        except PermissionError:
            run.cancel_requested = True
            run.stop_reason = "authorization_revoked"
    if run.cancel_requested:
        from .run_publication import finish_run

        await finish_run(run)
        return ClaimResult(1)
    if run.max_cost is not None and run.candidate_cost + run.judge_cost >= run.max_cost:
        from .run_publication import finish_run

        run.stop_reason = "budget_exhausted"
        await finish_run(run)
        return ClaimResult(1)
    dataset = await get_db().get(LabEvaluationDataset, run.dataset_id)
    if dataset is None:
        run.status, run.error = "failed", "Evaluation dataset is no longer available"
        run.finished_at = now
        await get_db().commit()
        return ClaimResult(1)
    mechanism = cast(EvaluationMechanism, dataset.mechanism)
    results = list(
        (
            await get_db().scalars(
                select(LabEvaluationRunCase)
                .where(LabEvaluationRunCase.run_id == run.id)
                .order_by(LabEvaluationRunCase.created_at)
            )
        ).all()
    )
    existing_ids = {(str(item.case_snapshot["id"]), item.repetition) for item in results}
    snapshot = (
        next(
            (
                item
                for item in run.case_snapshots
                if (str(item["id"]), item.get("repetition", 1)) not in existing_ids
            ),
            None,
        )
        if run.phase == "execution"
        else None
    )
    campaign: LabJudgmentCampaign | None = None
    result: LabEvaluationRunCase | None = None
    if snapshot is None:
        run.phase = "judgment"
        campaign = await get_db().scalar(
            select(LabJudgmentCampaign)
            .where(LabJudgmentCampaign.run_id == run.id)
            .order_by(LabJudgmentCampaign.sequence.desc())
            .limit(1)
        )
        if campaign is None:
            campaign = LabJudgmentCampaign(
                run_id=run.id,
                judge_llm_id=run.judge_llm_id,
                configuration={
                    "model": deepcopy(run.judge_llm_snapshot),
                    "rubric": deepcopy(
                        run.configuration_snapshot.get("rubric")
                        or get_rubric(mechanism).prompt_value()
                    ),
                    "pass_threshold": 75,
                    "reasoning_effort": run.configuration_snapshot.get("judge_reasoning_effort"),
                },
            )
            get_db().add(campaign)
            await get_db().flush()
        done = set(
            (
                await get_db().scalars(
                    select(LabJudgmentResult.result_id).where(
                        LabJudgmentResult.campaign_id == campaign.id
                    )
                )
            ).all()
        )
        result = next((item for item in results if item.id not in done), None)
        snapshot = result.case_snapshot if result is not None else None
        campaign.status = "running"
    run.status = "running"
    run.started_at = run.started_at or now
    run.lease_token = token = uuid4()
    run.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
    await get_db().commit()
    return ClaimResult(
        1,
        RunClaim(
            run_id=run.id,
            token=token,
            mechanism=mechanism,
            llm_id=run.llm_id,
            judge_llm_id=campaign.judge_llm_id if campaign else run.judge_llm_id,
            created_by=run.created_by,
            configuration_snapshot=deepcopy(run.configuration_snapshot),
            case_snapshot=deepcopy(snapshot),
            phase=run.phase,
            campaign_id=campaign.id if campaign else None,
            result_id=result.id if result else None,
            actual_output=deepcopy(result.actual_output) if result else None,
            candidate_error=result.error if result else None,
            judgment_configuration=deepcopy(campaign.configuration) if campaign else None,
            candidate_checks=deepcopy(result.score_details.get("checks", [])) if result else None,
            llm_snapshot=deepcopy(run.llm_snapshot),
        ),
    )
