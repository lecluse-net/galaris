"""Create independent judgment campaigns over persisted candidate outputs."""

from copy import deepcopy
from uuid import UUID
from sqlalchemy import func, select

from app.llm import llm_service, model_usages
from core.database import get_db
from .transactions import publish
from core.i18n import tr
from .models import (
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabJudgmentCampaign,
    LabJudgmentResult,
)
from .schemas import (
    EvaluationMechanism,
    EvaluationRejudge,
    EvaluationRunRead,
    JudgmentCampaignRead,
    JudgmentResultRead,
)
from .mechanism_rubrics import get_rubric
from .inference_profile import model_binding


async def list_campaigns(run_id: UUID) -> list[JudgmentCampaignRead]:
    campaigns = (
        await get_db().scalars(
            select(LabJudgmentCampaign)
            .where(
                LabJudgmentCampaign.run_id == run_id,
            )
            .order_by(LabJudgmentCampaign.sequence.desc())
        )
    ).all()
    results = (
        await get_db().scalars(
            select(LabJudgmentResult)
            .join(LabJudgmentCampaign)
            .where(
                LabJudgmentCampaign.run_id == run_id,
            )
            .order_by(LabJudgmentResult.created_at)
        )
    ).all()
    return [
        JudgmentCampaignRead(
            **JudgmentCampaignRead.model_validate(campaign).model_dump(exclude={"results"}),
            results=[
                JudgmentResultRead.model_validate(row)
                for row in results
                if row.campaign_id == campaign.id
            ],
        )
        for campaign in campaigns
    ]


async def rejudge(
    mechanism: EvaluationMechanism, run_id: UUID, data: EvaluationRejudge
) -> EvaluationRunRead:
    run = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset)
        .where(
            LabEvaluationRun.id == run_id,
            LabEvaluationDataset.mechanism == mechanism,
        )
        .with_for_update()
    )
    if run is None:
        raise LookupError("Benchmark not found")
    if run.status in {"queued", "running"}:
        raise ValueError("Wait for the active benchmark to finish")
    if run.max_cost is not None and run.candidate_cost + run.judge_cost >= run.max_cost:
        raise ValueError(await tr("evaluation_api.errors.budget_exhausted"))
    candidates = (
        await get_db().scalars(
            select(LabEvaluationRunCase).where(
                LabEvaluationRunCase.run_id == run.id,
            )
        )
    ).all()
    if not candidates:
        raise ValueError("No saved candidate output to judge")
    judge = (
        await llm_service.get_llm(data.judge_llm_id)
        if data.judge_llm_id is not None
        else await llm_service.get_profile_llm(model_usages.LAB)
    )
    if judge is None or "chat" not in judge.service_capabilities:
        raise ValueError("Select an available chat model for the judge")
    snapshot = {
        "id": judge.id,
        "code": judge.code,
        "label": judge.label,
        "model": judge.llm_name,
        "provider": judge.provider.name,
        "binding": model_binding(judge),
    }
    get_db().add(
        LabJudgmentCampaign(
            run_id=run.id,
            judge_llm_id=judge.id,
            sequence=1
            + int(
                await get_db().scalar(
                    select(func.coalesce(func.max(LabJudgmentCampaign.sequence), 0)).where(
                        LabJudgmentCampaign.run_id == run.id
                    )
                )
                or 0
            ),
            configuration={
                "model": snapshot,
                "rubric": deepcopy(get_rubric(mechanism).prompt_value()),
                "pass_threshold": 75,
                "reasoning_effort": await llm_service.get_profile_reasoning_effort(
                    model_usages.LAB
                ),
            },
        )
    )
    for result in candidates:
        result.judge_output = None
        result.score_percent = None
        result.verdict = None
        result.score_details = {**result.score_details, "judge_status": "pending"}
    run.judge_llm_id = judge.id
    run.judge_llm_snapshot = snapshot
    run.phase, run.status = "judgment", "queued"
    run.stop_reason = None
    run.judged_cases = 0
    run.cancel_requested = False
    run.finished_at = None
    run.score_percent = None
    run.analysis_markdown = None
    run.lease_token = None
    run.lease_expires_at = None
    await publish()
    await get_db().refresh(run)
    from app.task import scheduler

    scheduler.wake()
    return EvaluationRunRead.model_validate(run)


async def resume(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunRead:
    """Resume missing publications using the original immutable snapshots."""
    run = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset)
        .where(
            LabEvaluationRun.id == run_id,
            LabEvaluationDataset.mechanism == mechanism,
        )
        .with_for_update()
    )
    if run is None:
        raise LookupError("Benchmark not found")
    if run.status != "cancelled":
        raise ValueError("Only a cancelled benchmark can be resumed")
    run.phase = "execution" if run.completed_cases < run.total_cases else "judgment"
    run.status = "queued"
    run.cancel_requested = False
    run.finished_at = None
    run.lease_token = None
    run.lease_expires_at = None
    campaign = await get_db().scalar(
        select(LabJudgmentCampaign)
        .where(
            LabJudgmentCampaign.run_id == run.id,
        )
        .order_by(LabJudgmentCampaign.sequence.desc())
        .limit(1)
    )
    if campaign is not None:
        campaign.status = "queued"
        campaign.finished_at = None
    await publish()
    await get_db().refresh(run)
    from app.task import scheduler

    scheduler.wake()
    return EvaluationRunRead.model_validate(run)
