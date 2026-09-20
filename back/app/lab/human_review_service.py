"""Blind review payloads never disclose model identities or unreviewed judgments."""

from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from core.i18n import tr
from core.user import get_current_user_id
from .models import (
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabHumanReview,
    LabJudgmentCampaign,
    LabJudgmentResult,
)
from .mechanism_rubrics import MechanismRubric
from .schemas import (
    EvaluationMechanism,
    HumanReviewCreate,
    HumanReviewItem,
    HumanReviewQueue,
    JudgmentResultRead,
)


async def _reviewer() -> int:
    reviewer = get_current_user_id()
    if reviewer is None:
        raise ValueError(await tr("evaluation_api.errors.review_authentication"))
    return reviewer


async def _run(mechanism: EvaluationMechanism, run_id: UUID) -> LabEvaluationRun:
    run = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset)
        .where(
            LabEvaluationRun.id == run_id,
            LabEvaluationDataset.mechanism == mechanism,
        )
    )
    if run is None:
        raise LookupError(await tr("evaluation_api.errors.run_not_found"))
    return run


async def _campaign(
    mechanism: EvaluationMechanism, run_id: UUID, campaign_id: UUID | None = None
) -> LabJudgmentCampaign:
    await _run(mechanism, run_id)
    query = select(LabJudgmentCampaign).where(LabJudgmentCampaign.run_id == run_id)
    if campaign_id is not None:
        query = query.where(LabJudgmentCampaign.id == campaign_id)
    campaign = await get_db().scalar(query.order_by(LabJudgmentCampaign.sequence.desc()).limit(1))
    if campaign is None:
        raise LookupError(await tr("evaluation_api.errors.review_campaign_missing"))
    return campaign


async def review_queue(
    mechanism: EvaluationMechanism, run_id: UUID, campaign_id: UUID | None = None
) -> HumanReviewQueue:
    reviewer = await _reviewer()
    run = await _run(mechanism, run_id)
    campaign = await _campaign(mechanism, run_id, campaign_id)
    results = (
        await get_db().scalars(
            select(LabEvaluationRunCase)
            .where(
                LabEvaluationRunCase.run_id == run_id,
                LabEvaluationRunCase.error.is_(None),
                LabEvaluationRunCase.actual_output.is_not(None),
            )
            .order_by(LabEvaluationRunCase.created_at)
        )
    ).all()
    reviews = {
        row.result_id: row
        for row in (
            await get_db().scalars(
                select(LabHumanReview).where(
                    LabHumanReview.campaign_id == campaign.id,
                    LabHumanReview.reviewer_id == reviewer,
                )
            )
        ).all()
    }
    judgments = {
        row.result_id: row
        for row in (
            await get_db().scalars(
                select(LabJudgmentResult).where(
                    LabJudgmentResult.campaign_id == campaign.id,
                )
            )
        ).all()
    }
    items: list[HumanReviewItem] = []
    for result in results:
        review = reviews.get(result.id)
        judgment = judgments.get(result.id)
        items.append(
            HumanReviewItem(
                result_id=result.id,
                name=str(result.case_snapshot.get("name", "")),
                repetition=result.repetition,
                input=result.case_snapshot["input_data"],
                reference=result.case_snapshot.get("expected_output"),
                output=result.actual_output,
                assessment=review.assessment if review else None,
                human_score=review.score_percent if review else None,
                human_verdict=review.verdict if review else None,
                judge=JudgmentResultRead.model_validate(judgment) if review and judgment else None,
            )
        )
    return HumanReviewQueue(
        campaign_id=campaign.id,
        rubric=campaign.configuration["rubric"],
        parameters=run.configuration_snapshot.get("parameters", {}),
        items=items,
    )


async def submit_review(
    mechanism: EvaluationMechanism, run_id: UUID, data: HumanReviewCreate
) -> HumanReviewQueue:
    reviewer = await _reviewer()
    campaign = await _campaign(mechanism, run_id, data.campaign_id)
    # Serialize a reviewer's duplicate submissions, without locking across human interaction.
    result = await get_db().scalar(
        select(LabEvaluationRunCase)
        .where(
            LabEvaluationRunCase.id == data.result_id,
            LabEvaluationRunCase.run_id == run_id,
        )
        .with_for_update()
    )
    if result is None or result.error or result.actual_output is None:
        raise LookupError(await tr("evaluation_api.errors.review_output_missing"))
    existing = await get_db().scalar(
        select(LabHumanReview.id).where(
            LabHumanReview.result_id == result.id,
            LabHumanReview.campaign_id == campaign.id,
            LabHumanReview.reviewer_id == reviewer,
        )
    )
    if existing is not None:
        raise ValueError(await tr("evaluation_api.errors.review_submitted"))
    rubric = MechanismRubric.from_snapshot(mechanism, campaign.configuration["rubric"])
    scores = {item.code: item.score_percent for item in data.dimensions}
    if (
        len(scores) != len(data.dimensions)
        or set(scores) != {dim.code for dim in rubric.dimensions}
        or not all(isfinite(score) for score in scores.values())
    ):
        raise ValueError(await tr("evaluation_api.errors.review_dimensions"))
    score = sum(scores[dim.code] * dim.weight / 100 for dim in rubric.dimensions)
    if data.critical_failures:
        score = min(score, rubric.critical_failure_cap_percent)
    checks: list[dict[str, Any]] = result.score_details.get("checks", [])
    critical = any(not check.get("passed") and check.get("critical") for check in checks)
    verdict = (
        "fail"
        if critical
        or data.critical_failures
        or score < float(campaign.configuration.get("pass_threshold", 75))
        else "pass"
    )
    get_db().add(
        LabHumanReview(
            result_id=result.id,
            campaign_id=campaign.id,
            reviewer_id=reviewer,
            assessment=data.model_dump(mode="json", exclude={"result_id", "campaign_id"}),
            score_percent=score,
            verdict=verdict,
        )
    )
    await get_db().commit()
    return await review_queue(mechanism, run_id, campaign.id)
