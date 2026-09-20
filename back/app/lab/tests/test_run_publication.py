from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.lab.models import (
    LabEvaluationDataset,
    LabEvaluationCase,
    LabEvaluationRun,
    LabEvaluationRunCase,
)
from app.lab import mechanism_evaluation_service as service, run_inference


@pytest.mark.asyncio
@pytest.mark.parametrize("intervention", ["cancel", "replace_lease"])
async def test_publication_observes_concurrent_control(db, monkeypatch, intervention):
    from core.database.database import AsyncSessionLocal

    dataset = LabEvaluationDataset(name=f"publication-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    case = LabEvaluationCase(dataset_id=dataset.id, name="case")
    db.add(case)
    await db.flush()
    run = LabEvaluationRun(
        dataset_id=dataset.id,
        total_cases=1,
        case_snapshots=[
            {
                "id": str(case.id),
                "input_data": {"variable_value": "test"},
                "resolved_input": {"objective": "test"},
                "expected_output": {"result": "ok", "choices": []},
            }
        ],
    )
    db.add(run)
    await db.commit()
    run_id, replacement = run.id, uuid4()
    monkeypatch.setattr(service.llm_service, "get_llm", AsyncMock(return_value=SimpleNamespace()))

    async def evaluate(*args, **kwargs):
        async with AsyncSessionLocal() as independent:
            values = (
                {"cancel_requested": True}
                if intervention == "cancel"
                else {"lease_token": replacement}
            )
            await independent.execute(
                update(LabEvaluationRun).where(LabEvaluationRun.id == run_id).values(**values)
            )
            await independent.commit()
        return {"result": "ok", "choices": []}, 0.1

    monkeypatch.setattr(run_inference, "validate_binding", lambda *args: None)
    monkeypatch.setattr(run_inference, "evaluate_mechanism", evaluate)
    assert await service.process_runs() == 1
    await db.refresh(run)
    results = (
        await db.scalars(select(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == run_id))
    ).all()
    if intervention == "cancel":
        assert run.cancel_requested and run.status == "cancelled", [
            result.error for result in results
        ]
        assert run.completed_cases == len(results) == 1
        assert run.cost == pytest.approx(0.1)
        assert await service.process_runs() == 0
        from app.lab.judgment_service import resume

        unexpected_candidate = AsyncMock(side_effect=AssertionError("Candidate already published"))
        monkeypatch.setattr(run_inference, "evaluate_mechanism", unexpected_candidate)
        await resume("briefing", run.id)
        await service.process_runs()
        await db.refresh(run)
        unexpected_candidate.assert_not_awaited()
        assert run.completed_cases == 1
        assert run.status == "partial"
        assert run.candidate_cost == pytest.approx(0.1)
    else:
        assert run.lease_token == replacement and run.status == "running"
        assert run.completed_cases == len(results) == 0
        assert run.cost == 0


@pytest.mark.asyncio
async def test_claim_detaches_inputs_and_expired_lease_is_recoverable(db):
    from datetime import datetime, timedelta, timezone
    from app.lab.run_claims import claim_next_run

    dataset = LabEvaluationDataset(name=f"claim-{uuid4()}", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    case_id = uuid4()
    run = LabEvaluationRun(
        dataset_id=dataset.id,
        total_cases=1,
        configuration_snapshot={"nested": {"prompt": "frozen"}},
        case_snapshots=[{"id": str(case_id), "input_data": {"text": "frozen"}}],
    )
    db.add(run)
    await db.commit()
    first = await claim_next_run()
    assert first.work is not None
    assert (await claim_next_run()).processed == 0
    run.configuration_snapshot["nested"]["prompt"] = "edited"
    run.case_snapshots[0]["input_data"]["text"] = "edited"
    assert first.work.configuration_snapshot["nested"]["prompt"] == "frozen"
    assert first.work.case_snapshot["input_data"]["text"] == "frozen"
    run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    second = await claim_next_run()
    assert second.work is not None
    assert second.work.run_id == first.work.run_id
    assert second.work.token != first.work.token
    assert (await claim_next_run()).processed == 0
