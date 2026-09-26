"""All Labs expose the same read-only comparison of persisted evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.lab.access import MECHANISM_PRIVILEGES
from app.lab.assertions import LabMechanismReadPrivilegeAssertion
from app.lab.contracts import CONTRACTS
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign
from app.lab.router import compare_benchmarks
from core.authorize import AssertionContext
from core.database import get_db_session


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
async def test_http_comparison_preserves_evidence_and_missing_scores(client, mechanism):
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
            db.add(LabEvaluationRunCase(run_id=runs[0].id, case_snapshot=snapshot, score_percent=0, actual_output={"result": "Before answer"}, cost=0.2, duration=2))
            if index != 1:
                db.add(LabEvaluationRunCase(run_id=runs[1].id, case_snapshot=snapshot, score_percent=None if index == 2 else 20, actual_output={"result": "After answer"}, cost=0.1, duration=1))
        await db.commit()
        params = {"left_run_id": str(runs[0].id), "right_run_id": str(runs[1].id), "limit": 10}
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["comparable"] is True
    assert data["next_offset"] == 10
    second = (await client.get(url, params={**params, "offset": 10})).json()
    assert second["next_offset"] is None
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
