"""Dataset catalogues batch case counts without changing their public projections."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select

from app.lab import dispatcher_evaluation_service as dispatcher
from app.lab import mechanism_evaluation_service as mechanisms
from app.lab.models import LabEvaluationCase, LabEvaluationDataset
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["dispatcher", "task_analysis"])
async def test_dataset_counts_stay_batched_scoped_and_fresh(db, mechanism):
    async def listing():
        return await dispatcher.list_datasets() if mechanism == "dispatcher" else await mechanisms.list_datasets(mechanism)

    now = datetime.now(timezone.utc)
    reports = []
    ids = []
    for start, stop in ((0, 1), (1, 41), (41, 501)):
        datasets = [LabEvaluationDataset(mechanism=mechanism, name=f"Synthetic catalogue {index:02d}",
                                         description=f"Description {index}", purpose="holdout" if index % 2 else "work",
                                         parameters={"synthetic": index}, configuration={"retained": index},
                                         created_at=now, updated_at=now - timedelta(seconds=index))
                    for index in range(start, stop)]
        db.add_all(datasets)
        await db.flush()
        ids.extend(dataset.id for dataset in datasets)
        for index, dataset in enumerate(datasets, start=start):
            if index % 3 == 0:
                continue
            cases = [LabEvaluationCase(dataset_id=dataset.id, name=f"Synthetic case {offset}",
                                       readiness=readiness, enabled=enabled)
                     for offset, (readiness, enabled) in enumerate((
                         ("ready", True), ("ready", False), ("draft", True), ("ready", True),
                     ))]
            db.add_all(cases)
            cases[-1].soft_delete()
        await db.commit()
        db.expunge_all()
        statements = []
        connection = await db.connection()

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        try:
            items = await listing()
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
        assert [item.id for item in items] == ids
        for index, item in enumerate(items):
            assert (item.case_count, item.ready_case_count) == ((0, 0) if index % 3 == 0 else (3, 1))
            assert item.parameters == {"synthetic": index} and item.configuration == {"retained": index}
            assert item.description == f"Description {index}"
        reports.append({"datasets": stop, "queries": len(statements)})

    hidden = LabEvaluationDataset(mechanism=mechanism, name="Synthetic deleted catalogue")
    other = LabEvaluationDataset(mechanism="goal_tracking", name="Synthetic other mechanism")
    db.add_all([hidden, other])
    await db.flush()
    hidden.soft_delete()
    db.add_all([LabEvaluationCase(dataset_id=hidden.id, name="Hidden case"),
                LabEvaluationCase(dataset_id=other.id, name="Unrelated case"),
                LabEvaluationCase(dataset_id=ids[0], name="New ready case")])
    await db.commit()
    refreshed = await listing()
    assert [item.id for item in refreshed] == ids
    assert (refreshed[0].case_count, refreshed[0].ready_case_count) == (1, 1)

    destination = Path(__file__).resolve().parents[4] / f"artifacts/lab-dataset-reads-{mechanism}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reports, indent=2) + "\n")
    assert all(report["queries"] <= 1 + (report["datasets"] + 499) // 500 for report in reports), reports


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["planner", "topic_classification", "memory_extraction"])
async def test_batch_counts_keep_legacy_configuration_resolution(db, mechanism):
    row = LabEvaluationDataset(mechanism=mechanism, name="Synthetic legacy configuration",
                               configuration={}, prompt_suffix="Synthetic suffix")
    db.add(row)
    await db.commit()
    expected = await mechanisms.dataset_read(row)
    assert expected.configuration and expected.prompt_suffix == "Synthetic suffix"
    assert await mechanisms.list_datasets(mechanism) == [expected]
    row.soft_delete()
    await db.commit()
    assert await mechanisms.list_datasets(mechanism) == []


@pytest.mark.asyncio
async def test_dataset_http_preserves_mechanism_permissions_and_counts(client):
    password = "synthetic-lab-reader-password"
    async with get_db_session() as db:
        privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["DISPATCHER_EVALUATION_ACCESS", "EVALUATION_ACCESS"],
        )))).all())
        role = Role(code="synthetic-lab-reader", privileges=privileges)
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"dataset-reader-{index}@example.com", hashed_password=password_hash,
                           is_active=True) for index in range(2)]
        db.add_all([role, *users])
        await db.flush()
        db.add(Assignment(user_id=users[0].id, role_id=role.id, is_default=True))
        for mechanism in ("dispatcher", "task_analysis"):
            dataset = LabEvaluationDataset(mechanism=mechanism, name=f"Synthetic HTTP {mechanism}")
            db.add(dataset)
            await db.flush()
            db.add(LabEvaluationCase(dataset_id=dataset.id, name="Synthetic ready case"))
    paths = ("/api/evaluation/dispatcher/datasets", "/api/evaluation/task_analysis/datasets")
    for path in paths:
        assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(2):
        login = await client.post("/api/auth/login-json", json={
            "email": f"dataset-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    for path in paths:
        assert (await client.get(path, headers=headers[1])).status_code == 403
        response = await client.get(path, headers=headers[0])
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["case_count"] == response.json()[0]["ready_case_count"] == 1
        assert (await client.get(path, headers=headers[0])).json() == response.json()
    assert (await client.get("/api/evaluation/planner/datasets", headers=headers[0])).status_code == 403
