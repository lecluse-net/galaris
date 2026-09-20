"""A lost lease or repeated publication must not duplicate results or charges."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.lab.models import LabEvaluationDataset, LabEvaluationCase, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult
from app.lab.run_contracts import CaseEvaluation, RunClaim
from app.lab import run_inference, run_publication


def claim(**changes):
    work = RunClaim(run_id=uuid4(), token=uuid4(), mechanism="briefing", llm_id=2147483647,
        judge_llm_id=2147483647, created_by=None, configuration_snapshot={},
        case_snapshot={"id": str(uuid4()), "resolved_input": {"objective": "Report"}},
        result_id=uuid4(), campaign_id=uuid4(), actual_output={"result": "Saved answer"})
    return replace(work, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"candidate_error": "Provider failed"}, {"actual_output": None}])
async def test_unusable_candidate_is_skipped_without_inventing_score_or_cost(db, changes):
    work = claim(**changes)
    result = await run_inference.evaluate_judgment(work)
    assert result.score_details["judge_status"] == "skipped"
    assert result.actual_output == work.actual_output
    assert result.score_percent is None and result.judge_output is None and result.cost == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("judge_id,message", [(None, "not configured"), (2147483647, "no longer available")])
async def test_missing_judge_preserves_candidate_and_records_failed_judgment(db, judge_id, message):
    work = claim(judge_llm_id=judge_id)
    result = await run_inference.evaluate_judgment(work)
    assert result.score_details["judge_status"] == "failed" and message in result.error
    assert result.actual_output == work.actual_output
    assert result.score_percent is None and result.cost == 0


@pytest.mark.asyncio
async def test_removed_candidate_model_is_reported_without_substitution(db):
    work = claim()
    result = await run_inference.evaluate_claim(work)
    assert "no longer available" in result.error
    assert result.score_details["candidate_status"] == "failed"
    assert result.case_snapshot == work.case_snapshot
    assert result.actual_output is None and result.score_percent is None and result.cost == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["case_snapshot", "result_id", "campaign_id"])
async def test_judgment_refuses_unpersisted_work(field):
    with pytest.raises(ValueError, match="persisted candidate"):
        await run_inference.evaluate_judgment(claim(**{field: None}))


@pytest.mark.asyncio
async def test_inference_requires_a_frozen_case():
    with pytest.raises(ValueError, match="case is required"):
        await run_inference.evaluate_claim(claim(case_snapshot=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_candidate_republication_preserves_original_output_and_billing(db, cancel):
    dataset = LabEvaluationDataset(name=f"publication-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    case = LabEvaluationCase(dataset_id=dataset.id, name="Report")
    run = LabEvaluationRun(dataset_id=dataset.id, status="running", total_cases=2, lease_token=uuid4())
    db.add_all([case, run])
    await db.commit()
    result = CaseEvaluation(case.id, {"id": str(case.id)}, {"result": "Original"}, {}, None, None, 80, 0.25, 1, None)
    await run_publication.publish_case(run.id, run.lease_token, result)
    run.lease_token = uuid4()
    run.cancel_requested = cancel
    await db.commit()
    await run_publication.publish_case(run.id, run.lease_token, replace(result, actual_output={"result": "Duplicate"}, cost=99))
    rows = list(await db.scalars(select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run.id)))
    await db.refresh(run)
    assert len(rows) == run.completed_cases == 1
    assert rows[0].actual_output == {"result": "Original"}
    assert run.cost == run.candidate_cost == 0.25 and run.lease_token is None
    assert run.status == ("cancelled" if cancel else "running")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["candidate", "judgment", "finish"])
async def test_dispossessed_worker_cannot_publish_or_finish_an_owned_run(db, action):
    dataset = LabEvaluationDataset(name=f"lease-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    run = LabEvaluationRun(dataset_id=dataset.id, status="running", total_cases=2, lease_token=uuid4())
    db.add(run)
    await db.commit()
    run_id, owner = run.id, run.lease_token
    work = claim(run_id=run_id)
    evaluation = CaseEvaluation(uuid4(), {}, {"result": "stale"}, {}, None, None, 0, 99, 1, None)
    if action == "candidate":
        await run_publication.publish_case(run_id, work.token, evaluation)
    elif action == "judgment":
        await run_publication.publish_judgment(work, evaluation)
    else:
        await run_publication.finish_owned_run(run_id, work.token)
    await db.refresh(run)
    assert run.status == "running" and run.lease_token == owner and run.cost == 0
    assert await db.scalar(select(func.count()).select_from(LabEvaluationRunCase)) == 0


@pytest.mark.asyncio
async def test_judgment_republication_is_idempotent_and_cancellation_finishes_campaign(db):
    dataset = LabEvaluationDataset(name=f"judgment-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    run = LabEvaluationRun(dataset_id=dataset.id, status="running", phase="judgment", total_cases=2,
        completed_cases=2, candidate_cost=0.5, cost=0.5, lease_token=uuid4())
    db.add(run)
    await db.flush()
    candidate = LabEvaluationRunCase(run_id=run.id, case_snapshot={"id": str(uuid4())}, actual_output={"result": "Saved"})
    campaign = LabJudgmentCampaign(run_id=run.id, status="running")
    db.add_all([candidate, campaign])
    await db.commit()
    work = claim(run_id=run.id, token=run.lease_token, result_id=candidate.id, campaign_id=campaign.id)
    evaluation = CaseEvaluation(uuid4(), {}, candidate.actual_output, {"judge_status": "completed", "verdict": "pass"},
        {"reason": "Original judgment"}, 90, 0, 0.1, 1, None)
    await run_publication.publish_judgment(work, evaluation)
    run.lease_token = uuid4()
    run.cancel_requested = True
    await db.commit()
    await run_publication.publish_judgment(replace(work, token=run.lease_token), replace(evaluation, cost=99, score_percent=0))
    await db.refresh(run)
    await db.refresh(candidate)
    await db.refresh(campaign)
    assert await db.scalar(select(func.count()).select_from(LabJudgmentResult)) == 1
    assert run.cost == pytest.approx(0.6) and run.judge_cost == 0.1 and run.judged_cases == 1
    assert candidate.score_percent == 90 and candidate.actual_output == {"result": "Saved"}
    assert run.status == campaign.status == "cancelled" and campaign.finished_at is not None
