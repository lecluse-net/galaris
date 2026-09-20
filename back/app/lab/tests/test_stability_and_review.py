"""Observable guarantees for repeated benchmarks, budgets and independent review."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.lab import mechanism_evaluation_service as service, run_inference, human_review_service
from app.lab.judgment_service import rejudge, resume
from app.lab.mechanism_rubrics import get_rubric
from app.lab.models import (
    LabEvaluationCase,
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
)
from app.lab.schemas import (
    EvaluationDatasetUpdate,
    MechanismCaseUpdate,
    EvaluationRunStart,
    EvaluationRejudge,
    HumanReviewCreate,
    MechanismJudgeOutput,
)
from app.llm import LLM, LLMProvider
from core.user import UserModel


@pytest_asyncio.fixture
async def benchmark(db, monkeypatch):
    provider = LLMProvider(name=f"lab-{uuid4()}", base_url="https://example.test", is_active=True)
    db.add(provider)
    await db.flush()
    llm = LLM(
        llm_provider_id=provider.id,
        provider=provider,
        code=f"model-{uuid4()}",
        llm_name="model",
        label="Hidden candidate",
        service_capabilities=["chat"],
    )
    dataset = LabEvaluationDataset(
        name=f"stability-{uuid4()}", mechanism="briefing", purpose="validation"
    )
    db.add_all([llm, dataset])
    await db.flush()
    case = LabEvaluationCase(
        dataset_id=dataset.id,
        name="Report",
        categories=["ambiguity", "incident"],
        input_data={"variable_value": "Prepare a report"},
        expected_output={"result": "Reference", "choices": []},
    )
    db.add(case)
    await db.commit()
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=llm))
    monkeypatch.setattr(service.llm_service, "get_profile_llm", AsyncMock(return_value=llm))
    monkeypatch.setattr(
        service.llm_service,
        "get_profile_reasoning_effort_for_agent_id",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        service.llm_service, "get_profile_reasoning_effort", AsyncMock(return_value=None)
    )
    calls = []

    async def candidate(*args, **kwargs):
        calls.append("candidate")
        return {
            "result": f"Result {len(calls)}",
            "choices": [
                {"kind": "other", "identifier": "verify", "reason": "Verify the supplied evidence"}
            ],
        }, 0.1

    async def judge(**kwargs):
        calls.append("judge")
        return MechanismJudgeOutput(
            explanation="Automatic assessment",
            confidence_percent=90,
            dimensions=[
                {"code": dim.code, "score_percent": 90, "assessment": "Supported"}
                for dim in get_rubric("briefing").dimensions
            ],
        ), 0.02

    monkeypatch.setattr(run_inference, "evaluate_mechanism", candidate)
    monkeypatch.setattr(run_inference, "_judge", judge)
    return dataset, llm, calls


@pytest.mark.asyncio
async def test_dataset_roles_and_item_categories_survive_edits_and_duplication(db, benchmark):
    dataset, _, _ = benchmark
    saved = await service.update_dataset(
        "briefing",
        dataset.id,
        EvaluationDatasetUpdate(revision=dataset.revision, name=dataset.name, purpose="holdout"),
    )
    assert saved.purpose == "holdout"
    saved = await service.update_dataset(
        "briefing",
        dataset.id,
        EvaluationDatasetUpdate(
            revision=saved.revision, name=saved.name, description="Legacy client edit"
        ),
    )
    assert saved.purpose == "holdout"
    case = (await service.list_cases("briefing", dataset.id))[0]
    edited = await service.update_case(
        "briefing",
        case.id,
        MechanismCaseUpdate(
            revision=case.revision,
            input_data=case.input_data,
            expected_output=case.expected_output,
            categories=["multilingual", "incident", "incident"],
        ),
    )
    assert edited.categories == ["multilingual", "incident"]
    duplicate = await service.duplicate_case("briefing", case.id)
    assert duplicate.categories == edited.categories
    unchanged = await service.update_case(
        "briefing",
        case.id,
        MechanismCaseUpdate(
            revision=edited.revision,
            input_data=edited.input_data,
            expected_output=edited.expected_output,
        ),
    )
    assert unchanged.categories == edited.categories


@pytest.mark.asyncio
async def test_repetitions_resume_without_duplicates_and_preserve_coverage(db, benchmark):
    dataset, llm, calls = benchmark
    started = await service.start_run(
        "briefing", dataset.id, EvaluationRunStart(llm_id=llm.id, repetitions=3)
    )
    run = await db.get(LabEvaluationRun, started.id)
    assert run.total_cases == 3 and run.repetitions == 3
    assert run.configuration_snapshot["dataset_purpose"] == "validation"
    assert all(row["categories"] == ["ambiguity", "incident"] for row in run.case_snapshots)
    await service.process_runs()
    await service.cancel_run("briefing", run.id)
    await service.process_runs()
    await resume("briefing", run.id)
    for _ in range(5):
        await service.process_runs()
    await db.refresh(run)
    assert calls == ["candidate"] * 3 + ["judge"] * 3
    assert run.status == "completed"
    assert run.candidate_cost == pytest.approx(0.3)
    assert run.judge_cost == pytest.approx(0.06)
    results = (
        await db.scalars(select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run.id))
    ).all()
    assert sorted(row.repetition for row in results) == [1, 2, 3]
    assert len({row.actual_output["result"] for row in results}) == 3
    await rejudge("briefing", run.id, EvaluationRejudge())
    for _ in range(3):
        await service.process_runs()
    assert calls.count("candidate") == 3
    assert calls.count("judge") == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("budget, candidate_count, judge_count", [(0.15, 2, 0), (0.31, 3, 1)])
async def test_budget_stops_before_next_evaluation_and_preserves_outputs(
    db, benchmark, budget, candidate_count, judge_count
):
    dataset, llm, calls = benchmark
    run = await service.start_run(
        "briefing", dataset.id, EvaluationRunStart(llm_id=llm.id, repetitions=3, max_cost=budget)
    )
    for _ in range(8):
        await service.process_runs()
    detail = await service.get_run("briefing", run.id)
    assert calls == ["candidate"] * candidate_count + ["judge"] * judge_count
    assert detail.stop_reason == "budget_exhausted" and detail.status == "partial"
    assert len(detail.results) == candidate_count
    assert detail.judged_cases == judge_count
    with pytest.raises(ValueError, match="budget exhausted"):
        await rejudge("briefing", run.id, EvaluationRejudge())


@pytest.mark.asyncio
async def test_review_is_blind_immutable_and_isolated_by_reviewer_and_campaign(
    db, benchmark, monkeypatch
):
    dataset, llm, _ = benchmark
    run = await service.start_run("briefing", dataset.id, EvaluationRunStart(llm_id=llm.id))
    await service.process_runs()
    await service.process_runs()
    reviewers = [
        UserModel(email=f"review-{uuid4()}@example.test", hashed_password="unused")
        for _ in range(2)
    ]
    db.add_all(reviewers)
    await db.commit()
    monkeypatch.setattr(human_review_service, "get_current_user_id", lambda: reviewers[0].id)
    queue = await human_review_service.review_queue("briefing", run.id)
    assert queue.items[0].judge is None and queue.items[0].assessment is None
    assert "Hidden candidate" not in queue.model_dump_json()
    assert "Automatic assessment" not in queue.model_dump_json()
    data = HumanReviewCreate(
        result_id=queue.items[0].result_id,
        campaign_id=queue.campaign_id,
        dimensions=[
            {"code": dim.code, "score_percent": 50, "assessment": "Missing evidence"}
            for dim in get_rubric("briefing").dimensions
        ],
        explanation="Insufficient support",
    )
    bad = data.model_copy(update={"dimensions": data.dimensions[:-1]})
    with pytest.raises(ValueError, match="exactly once"):
        await human_review_service.submit_review("briefing", run.id, bad)
    revealed = await human_review_service.submit_review("briefing", run.id, data)
    assert revealed.items[0].human_score == 50
    assert revealed.items[0].human_verdict == "fail"
    assert revealed.items[0].judge.score_percent == 90
    assert revealed.items[0].judge.verdict == "pass"
    with pytest.raises(ValueError, match="already submitted"):
        await human_review_service.submit_review("briefing", run.id, data)
    monkeypatch.setattr(human_review_service, "get_current_user_id", lambda: reviewers[1].id)
    assert (await human_review_service.review_queue("briefing", run.id)).items[0].judge is None
    with pytest.raises(LookupError):
        await human_review_service.review_queue("planner", run.id)
    monkeypatch.setattr(human_review_service, "get_current_user_id", lambda: reviewers[0].id)
    await rejudge("briefing", run.id, EvaluationRejudge())
    assert (await human_review_service.review_queue("briefing", run.id)).items[0].assessment is None
    assert (await human_review_service.review_queue("briefing", run.id, queue.campaign_id)).items[
        0
    ].human_score == 50
