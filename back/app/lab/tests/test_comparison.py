"""All Labs expose the same read-only comparison of persisted evidence."""

from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.lab.access import MECHANISM_PRIVILEGES
from app.lab.assertions import LabMechanismReadPrivilegeAssertion
from app.lab.contracts import CONTRACTS
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign
from app.lab.comparison_summary import summarize
from app.lab.router import compare_benchmarks
from core.authorize import AssertionContext
from core.database import get_db_session


@pytest.mark.asyncio
async def test_summary_counts_distinct_cases_repetitions_judgments_and_errors(db):
    dataset = LabEvaluationDataset(name="Synthetic summary", mechanism="briefing")
    db.add(dataset)
    await db.flush()
    before, after = [LabEvaluationRun(dataset_id=dataset.id, status="completed") for _ in range(2)]
    db.add_all([before, after])
    await db.flush()
    assert (await summarize(before.id, after.id, comparable=True)).observations == 0
    for repetition, scores in enumerate([(0, 20), (30, 0), (0, 0), (10, 20), (10, 20), (0, 10)], 1):
        for run, score in zip((before, after), scores):
            db.add(LabEvaluationRunCase(run_id=run.id, repetition=repetition,
                case_snapshot={"input_data": {"question": "same"}, "expected_output": {"answer": "same"}},
                score_percent=score, judge_output=None if repetition == 4 else {"explanation": "Synthetic evidence"},
                error="Synthetic failed execution" if repetition == 5 and run is after else None))
    await db.flush()
    result = await summarize(before.id, after.id, comparable=True)
    assert result.cases == 1 and result.observations == result.matched == 6
    assert result.increased == 2
    assert result.decreased == result.equal == result.unjudged == result.failed == 1
    reversed_result = await summarize(after.id, before.id, comparable=True)
    assert reversed_result.increased == result.decreased
    assert reversed_result.decreased == result.increased
    blocked = await summarize(before.id, after.id, comparable=False)
    assert blocked.increased is blocked.decreased is blocked.equal is None
    assert blocked.matched == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
@pytest.mark.parametrize("granted", [True, False])
async def test_comparison_requires_read_or_edit_of_exact_lab(monkeypatch, mechanism, granted):
    check = AsyncMock(return_value=granted)
    monkeypatch.setattr("app.lab.assertions.check_privilege", check)
    assert compare_benchmarks._authorize_meta["assertion"] is LabMechanismReadPrivilegeAssertion
    user, db = SimpleNamespace(), SimpleNamespace()
    assert await LabMechanismReadPrivilegeAssertion().assert_(AssertionContext(user=user, db=db, params={"mechanism": mechanism})) is granted
    check.assert_awaited_once_with(user, list(MECHANISM_PRIVILEGES[mechanism]), db)


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", list(CONTRACTS))
@pytest.mark.parametrize("duplicate_side", ["left", "right"])
async def test_http_comparison_preserves_evidence_and_missing_scores(client, mechanism, duplicate_side):
    url = f"/api/evaluation/{mechanism}/runs/compare"
    params = {"left_run_id": str(uuid4()), "right_run_id": str(uuid4())}
    assert (await client.get(url, params=params)).status_code in {401, 403}
    credentials = {"email": "comparison-reader@example.com", "password": "synthetic-comparison-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    async with get_db_session() as db:
        datasets = [LabEvaluationDataset(name=name, mechanism=mechanism) for name in ("Before", "After")]
        db.add_all(datasets)
        await db.flush()
        runs = [LabEvaluationRun(dataset_id=dataset.id, status="completed", configuration_snapshot={"fingerprints": {"corpus": "same", "candidate": "same"}}, total_cases=11, completed_cases=11) for dataset in datasets]
        db.add_all(runs)
        await db.flush()
        for run in runs:
            db.add(LabJudgmentCampaign(run_id=run.id, configuration={"judge": "synthetic"}))
        for index in range(11):
            snapshot = {"name": f"Case {index}", "input_data": {"variable_value": str(index)}, "expected_output": {"result": "Reference"}}
            created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
            db.add(LabEvaluationRunCase(run_id=runs[0].id, case_snapshot=snapshot, score_percent=0, actual_output={"result": "Before answer"}, cost=0.2, duration=2, created_at=created_at))
            if index != 1:
                db.add(LabEvaluationRunCase(run_id=runs[1].id, case_snapshot=snapshot, score_percent=None if index == 2 else 20, actual_output={"result": "After answer"}, cost=0.1, duration=1, created_at=created_at))
        await db.commit()
        params = {"left_run_id": str(runs[0].id), "right_run_id": str(runs[1].id), "limit": 10}
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["comparable"] is True
    assert data["next_offset"] == 10
    second = (await client.get(url, params={**params, "offset": 10})).json()
    assert second["next_offset"] is None
    assert data["summary"] == second["summary"]
    assert data["summary"]["cases"] == data["summary"]["observations"] == 11
    assert data["summary"]["matched"] == data["summary"]["unjudged"] == 10
    assert data["summary"]["missing_right"] == 1
    assert data["summary"]["increased"] == 0  # A score without a judgment is not a gain.
    items = {item["name"]: item for item in data["items"] + second["items"]}
    assert len(items) == 11
    assert items["Case 0"]["left_score"] == 0
    assert items["Case 0"]["score_delta"] == 20
    assert items["Case 0"]["cost_delta"] == pytest.approx(-0.1)
    assert items["Case 0"]["duration_delta"] == -1
    assert items["Case 0"]["left_output"] == {"result": "Before answer"}
    assert items["Case 0"]["right_output"] == {"result": "After answer"}
    assert items["Case 1"]["pairing"] == "missing"
    assert items["Case 1"]["right_output"] is None
    assert items["Case 2"]["score_delta"] is None
    assert items["Case 2"]["right_score"] is None
    assert (await client.get(url, params={**params, "limit": 500})).status_code == 200
    for invalid in ({"limit": 501}, {"offset": -1}, {"axis": "unknown"}):
        assert (await client.get(url, params={**params, **invalid})).status_code == 422
    other = "dispatcher" if mechanism != "dispatcher" else "briefing"
    assert (await client.get(f"/api/evaluation/{other}/runs/compare", params=params)).status_code == 404
    assert (await client.get(url, params={**params, "right_run_id": str(uuid4())})).status_code == 404

    # The affected case is outside the first page. Different repetitions are
    # separate evidence; duplicating the same repetition makes pairing ambiguous.
    async with get_db_session() as db:
        original = await db.get(LabEvaluationRunCase, UUID(items["Case 10"][f"{duplicate_side}_result_id"]))
        for repetition in (original.repetition + 1, original.repetition + 2):
            db.add(LabEvaluationRunCase(run_id=original.run_id, repetition=repetition,
                case_snapshot=original.case_snapshot, score_percent=10))
        missing = await db.get(LabEvaluationRunCase, UUID(items["Case 1"]["left_result_id"]))
        db.add(LabEvaluationRunCase(run_id=missing.run_id, repetition=missing.repetition,
            case_snapshot=missing.case_snapshot, score_percent=0))
        await db.commit()
    assert (await client.get(url, params=params)).json()["comparable"] is True
    async with get_db_session() as db:
        original = await db.get(LabEvaluationRunCase, original.id)
        db.add(LabEvaluationRunCase(run_id=original.run_id, repetition=original.repetition,
            case_snapshot=original.case_snapshot, score_percent=10))
        await db.commit()

    for reverse in (False, True):
        pair = {**params}
        if reverse:
            pair["left_run_id"], pair["right_run_id"] = pair["right_run_id"], pair["left_run_id"]
        for offset, limit in ((0, 10), (10, 10), (0, 500), (999, 10)):
            response = await client.get(url, params={**pair, "offset": offset, "limit": limit})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["comparable"] is False
            assert page["blockers"] == ["ambiguous_case_pairing"]
            assert page["summary"]["cases"] == 11
            assert page["summary"]["observations"] == 13
            assert page["summary"]["ambiguous"] == 1
            assert page["summary"]["increased"] is None
            for item in page["items"]:
                if item["name"] == "Case 10" and item["repetition"] == original.repetition:
                    assert item["pairing"] == "ambiguous"
                    assert item["right_result_id"] is None
                    assert item["score_delta"] is None
                    assert item["cost_delta"] is None
                    assert item["duration_delta"] is None
                    assert item["right_output"] is None
