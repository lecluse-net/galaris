"""Fixed outputs isolate observed judge variation without inventing independence."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.lab.judge_repeatability import CampaignEvidence, JudgmentEvidence, read_repeatability, summarize_repeatability
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult
from core.authorize.tests.test_guard_policy_parameters import actor
from core.database import get_db_session


def configuration():
    return {"model": {"code": "synthetic-judge", "binding": "synthetic-model-binding"},
            "rubric": {"version": "synthetic/v1", "dimensions": [{"code": "grounding", "weight": 1}]},
            "pass_threshold": 75, "reasoning_effort": None}


def judgment(campaign, result_id, score, case_key="case-a", **changes):
    return JudgmentEvidence.model_validate({
        "campaign_id": campaign.id, "result_id": result_id, "case_key": case_key,
        "candidate_status": "completed", "status": "completed", "error": None,
        "score_percent": score, "verdict": "pass" if score >= 75 else "fail",
        "rubric_version": "synthetic/v1", **changes,
    })


def test_pairwise_variation_keeps_outputs_fixed_and_source_cases_equally_weighted():
    campaigns = [CampaignEvidence(id=uuid4(), configuration=configuration()) for _ in range(3)]
    rows = []
    # Twenty independently generated candidate outputs of A must not outweigh B.
    for _ in range(20):
        identity = uuid4()
        rows.extend(judgment(campaign, identity, score) for campaign, score in zip(campaigns, [0, 0, 100]))
    identity = uuid4()
    rows.extend(judgment(campaign, identity, 100, "case-b") for campaign in campaigns)
    report = summarize_repeatability(uuid4(), campaigns, rows, 21)
    group = report.groups[0]
    assert group.usable_judgments == group.expected_judgments == 63
    assert group.repeated_outputs == 21 and group.judgment_pairs == 63
    assert group.absolute_score_difference.mean == pytest.approx(100 / 3)
    assert group.verdict_disagreement_percent.mean == pytest.approx(100 / 3)
    assert group.absolute_score_difference.cases == 2
    assert group.absolute_score_difference.observations == 21
    assert not group.absolute_score_difference.sufficient
    # Order and repetition counts do not change uncertainty or the case mean.
    smaller = rows[:3] + rows[-3:]
    other = summarize_repeatability(report.run_id, list(reversed(campaigns)), list(reversed(smaller)), 2).groups[0]
    assert other.configuration_digest == group.configuration_digest
    assert other.absolute_score_difference.mean == group.absolute_score_difference.mean
    assert other.absolute_score_difference.lower == group.absolute_score_difference.lower
    assert other.absolute_score_difference.upper == group.absolute_score_difference.upper


@pytest.mark.parametrize("change", [
    {"status": "failed"}, {"error": "Synthetic judge unavailable"}, {"score_percent": None},
    {"score_percent": float("nan")}, {"score_percent": 101}, {"verdict": "inconclusive"},
    {"rubric_version": "synthetic/v2"}, {"candidate_status": "failed"},
])
def test_unknown_or_failed_judgments_never_imply_repeatability(change):
    campaigns = [CampaignEvidence(id=uuid4(), configuration=configuration()) for _ in range(3)]
    identity = uuid4()
    rows = [judgment(campaigns[0], identity, 0), judgment(campaigns[1], identity, 0, **change)]
    group = summarize_repeatability(uuid4(), campaigns, rows, 1).groups[0]
    assert group.recorded_judgments == 2 and group.usable_judgments == 1
    assert group.missing_judgments == group.unusable_judgments == 1
    assert group.repeated_outputs == group.judgment_pairs == 0
    assert group.absolute_score_difference.mean is None
    assert group.verdict_disagreement_percent.mean is None


@pytest.mark.parametrize("field,value", [
    ("model", {"code": "other-judge", "binding": "other-synthetic-binding"}),
    ("rubric", {"version": "synthetic/v1", "dimensions": [{"code": "grounding", "weight": 2}]}),
    ("pass_threshold", 80), ("reasoning_effort", "high"),
])
def test_configuration_changes_are_separate_experiments(field, value):
    changed = configuration()
    changed[field] = value
    campaigns = [CampaignEvidence(id=uuid4(), configuration=config) for config in (configuration(), changed, {})]
    identity = uuid4()
    rows = [judgment(campaign, identity, 50) for campaign in campaigns]
    report = summarize_repeatability(uuid4(), campaigns, rows, 1)
    assert report.unqualified_campaign_ids == [campaigns[2].id]
    assert len(report.groups) == 2
    assert all(group.absolute_score_difference.mean is None for group in report.groups)
    assert len({group.configuration_digest for group in report.groups}) == 2


@pytest.mark.parametrize("field,value", [
    ("model", {"code": "judge-without-binding"}), ("rubric", {"version": "synthetic/v1"}),
    ("pass_threshold", None), ("pass_threshold", True), ("pass_threshold", float("inf")),
])
def test_incomplete_historical_configurations_are_reported_without_a_metric(field, value):
    config = configuration()
    config[field] = value
    campaign = CampaignEvidence(id=uuid4(), configuration=config)
    report = summarize_repeatability(uuid4(), [campaign], [], 1)
    assert report.groups == [] and report.unqualified_campaign_ids == [campaign.id]


def test_repeated_agreement_retains_uncertainty_and_single_case_has_no_interval():
    campaigns = [CampaignEvidence(id=uuid4(), configuration=configuration()) for _ in range(2)]
    rows = []
    for index in range(20):
        identity = uuid4()
        rows.extend(judgment(campaign, identity, 0, str(index)) for campaign in campaigns)
    group = summarize_repeatability(uuid4(), campaigns, rows, 20).groups[0]
    assert group.verdict_disagreement_percent.sufficient
    assert group.verdict_disagreement_percent.mean == 0
    assert group.verdict_disagreement_percent.upper > 0
    single = summarize_repeatability(uuid4(), campaigns, rows[:2], 1).groups[0]
    assert single.absolute_score_difference.lower is single.absolute_score_difference.upper is None
    assert summarize_repeatability(uuid4(), [], [], 0).groups == []


def test_judgments_of_distinct_candidate_generations_are_not_judge_repetitions():
    campaigns = [CampaignEvidence(id=uuid4(), configuration=configuration()) for _ in range(2)]
    rows = [judgment(campaign, uuid4(), 100) for campaign in campaigns]
    group = summarize_repeatability(uuid4(), campaigns, rows, 2).groups[0]
    assert group.usable_judgments == group.missing_judgments == 2
    assert group.repeated_outputs == group.judgment_pairs == 0
    assert group.verdict_disagreement_percent.mean is None


@pytest.mark.asyncio
async def test_historical_measurements_and_exact_lab_rights_through_http(client):
    async with get_db_session() as db:
        dataset = LabEvaluationDataset(name="Synthetic judge repeatability", mechanism="planner")
        db.add(dataset)
        await db.flush()
        run = LabEvaluationRun(dataset_id=dataset.id, status="completed")
        db.add(run)
        await db.flush()
        saved = LabEvaluationRunCase(run_id=run.id,
            case_snapshot={"input_data": {"variable_value": "Produce a synthetic summary"}, "expected_output": {}},
            actual_output={"text": "Fixed candidate output"}, score_percent=999,
            score_details={"candidate_status": "completed"})
        db.add(saved)
        db.add(LabEvaluationRunCase(run_id=run.id,
            case_snapshot={"input_data": {"variable_value": "Unjudged synthetic input"}, "expected_output": {}},
            score_details={"candidate_status": "completed"}))
        await db.flush()
        for sequence, score in enumerate([0, 100], 1):
            campaign = LabJudgmentCampaign(run_id=run.id, sequence=sequence, configuration=configuration())
            db.add(campaign)
            await db.flush()
            db.add(LabJudgmentResult(campaign_id=campaign.id, result_id=saved.id,
                status="completed", verdict="pass" if score else "fail", score_percent=score,
                output={"rubric_version": "synthetic/v1", "explanation": "Synthetic hidden prose"}))
        await db.commit()
        run_id = run.id
    url = f"/api/evaluation/planner/runs/{run_id}/judge-repeatability"
    assert (await client.get(url)).status_code in {401, 403}
    for code in ("PLANNER_EVALUATION_ACCESS", "PLANNER_EVALUATION_EDIT", "DISPATCHER_EVALUATION_ACCESS"):
        headers, _ = await actor([code])
        response = await client.get(url, headers=headers)
        if code.startswith("DISPATCHER"):
            assert response.status_code == 403, response.text
            continue
        assert response.status_code == 200, response.text
        data = response.json()
        group = data["groups"][0]
        assert group["absolute_score_difference"]["mean"] == 100
        assert group["verdict_disagreement_percent"]["mean"] == 100
        assert group["repeated_outputs"] == 1
        assert group["outputs"] == 2 and group["expected_judgments"] == 4
        assert group["missing_judgments"] == 2
        assert "Fixed candidate output" not in response.text
        assert "Synthetic hidden prose" not in response.text
        assert (await client.get(url.replace(str(run_id), str(uuid4())), headers=headers)).status_code == 404
    headers, _ = await actor(["DISPATCHER_EVALUATION_ACCESS"])
    assert (await client.get(url.replace("/planner/", "/dispatcher/"), headers=headers)).status_code == 404
    async with get_db_session() as db:
        before = deepcopy((await db.get(LabEvaluationRunCase, saved.id)).actual_output)
        assert (await read_repeatability("planner", run_id)).model_dump(mode="json") == data
        assert (await db.get(LabEvaluationRunCase, saved.id)).actual_output == before
