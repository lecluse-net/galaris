from uuid import uuid4

import pytest

from app.lab.cost_report import economics
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase
from app.llm.models import LLMCall
from app.llm.cost_accounting import call_cost, summarize_costs


def snapshot(identity, cost):
    return summarize_costs([call_cost(call_id=identity, cost=cost, inference_cost=cost,
        cost_estimated=False, is_subscription=False, status="completed", usage={})]).model_dump(mode="json")


@pytest.mark.asyncio
async def test_full_run_cost_includes_failures_orphan_calls_and_survives_trace_cleanup(db, monkeypatch):
    from unittest.mock import AsyncMock
    from app.llm import llm_call_service
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    dataset = LabEvaluationDataset(name="Synthetic accounting", mechanism="task_executor")
    db.add(dataset)
    await db.flush()
    run = LabEvaluationRun(dataset_id=dataset.id, status="completed", total_cases=2)
    db.add(run)
    await db.flush()
    paid, orphan = uuid4(), uuid4()
    result = LabEvaluationRunCase(run_id=run.id, cost=.2, verdict="pass", score_percent=90,
        case_snapshot={}, score_details={"candidate_status": "completed", "judge_status": "completed",
            "checks": [{"passed": True, "critical": True}], "candidate_cost_accounting": snapshot(paid, .2)},
        judge_output={"rubric_version": "synthetic/v1", "critical_failures": []})
    failed = LabEvaluationRunCase(run_id=run.id, cost=.3, error="Synthetic paid failure",
        case_snapshot={}, score_details={"candidate_status": "failed", "candidate_cost_accounting": snapshot(uuid4(), .3)})
    db.add_all([result, failed, LLMCall(id=paid, cost=.2, inference_cost=.2, cost_estimated=False, status="completed",
        correlation_ref=f"lab://run/{run.id}/candidate/published"),
        LLMCall(id=orphan, cost=.4, inference_cost=.4, cost_estimated=False, status="error",
        correlation_ref=f"lab://run/{run.id}/candidate/lost-lease")])
    await db.flush()
    await db.commit()
    await llm_call_service.finalize_call(orphan, trace={"usage": {"cost": .4}}, status="error")
    report = await economics(run)
    assert report.benchmark_successes == report.failed_candidates == 1
    assert report.candidate.recorded_cost == pytest.approx(.9)
    assert report.cost_per_success == pytest.approx(.9)
    assert report.candidate.calls == 3  # Published call appears in both sources, once in the report.
    await db.delete(await db.get(LLMCall, paid))
    await db.delete(await db.get(LLMCall, orphan))
    await db.flush()
    assert (await economics(run)).cost_per_success == pytest.approx(.9)
    result.score_details = {**result.score_details, "candidate_cost_accounting": {}}
    await db.flush()
    missing = await economics(run)
    assert missing.cost_per_success is None and missing.unavailable_reason == "incomplete_costs"
    result.verdict = "fail"
    await db.flush()
    assert (await economics(run)).unavailable_reason == "no_success"


@pytest.mark.asyncio
async def test_late_provider_receipt_replaces_an_unknown_terminal_snapshot(db, monkeypatch):
    from unittest.mock import AsyncMock
    from app.llm import llm_call_service
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    dataset = LabEvaluationDataset(name="Synthetic late receipt", mechanism="task_executor")
    db.add(dataset)
    await db.flush()
    run = LabEvaluationRun(dataset_id=dataset.id, status="completed", total_cases=1)
    db.add(run)
    await db.flush()
    call = LLMCall(status="running", correlation_ref=f"lab://run/{run.id}/candidate/late")
    db.add(call)
    await db.flush()
    unknown = summarize_costs([call_cost(call_id=call.id, cost=0, inference_cost=0,
        cost_estimated=True, is_subscription=False, status="cancelled", usage={})])
    db.add(LabEvaluationRunCase(run_id=run.id, cost=0, verdict="pass", score_percent=90,
        case_snapshot={}, score_details={"candidate_status": "completed", "judge_status": "completed",
            "checks": [{"passed": True}], "candidate_cost_accounting": unknown.model_dump(mode="json")},
        judge_output={"rubric_version": "synthetic/v1", "critical_failures": []}))
    await db.commit()
    assert (await economics(run)).cost_per_success is None
    await llm_call_service.finalize_call(call.id, trace={"usage": {"cost": .4}})
    report = await economics(run)
    assert report.candidate.calls == 1
    assert report.cost_per_success == pytest.approx(.4)
