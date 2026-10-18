"""Source pickers preserve their projections without per-task reads or trace payloads."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.agent import Agent
from app.agent.models import Title
from app.lab import mechanism_evaluation_service as mechanisms
from app.llm import LLMCall
from app.task import Task, TaskStatus
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


def planner_call(**values):
    return LLMCall(
        provider_name="synthetic",
        requested_model="synthetic-reference",
        system_prompt="You are the Planner. You receive an objective",
        prompt="Task: prepare and deliver a synthetic report",
        status="completed",
        tool_calls=[{"name": "final_result", "arguments": {
            "brief": {"objective": "Prepare and verify a synthetic report."}, "steps": [],
        }}],
        **values,
    )


@pytest.mark.asyncio
async def test_source_picker_bounds_queries_and_avoids_unused_traces(db):
    now = datetime.now(timezone.utc)
    tasks = [Task(label=f"Synthetic source {index}", status=TaskStatus.SUCCESS) for index in range(41)]
    db.add_all(tasks)
    await db.flush()
    calls = [planner_call(task_id=task.id, created_at=now - timedelta(seconds=index),
                          reasoning="r" * 100_000,
                          request_messages=[{"role": "user", "content": "m" * 100_000}])
             for index, task in enumerate(tasks)]
    db.add_all(calls)
    await db.commit()
    expected = [(call.id, task.id, task.label) for call, task in zip(calls, tasks)]
    db.expunge_all()
    connection = await db.connection()
    statements = []
    loaded = {"tasks": 0, "unused_trace_bytes": 0}

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    def materialized(_session, instance):
        if isinstance(instance, Task):
            loaded["tasks"] += 1
        if isinstance(instance, LLMCall):
            if "reasoning" not in inspect(instance).unloaded:
                loaded["unused_trace_bytes"] += len(instance.reasoning.encode())
            if "request_messages" not in inspect(instance).unloaded:
                loaded["unused_trace_bytes"] += len(json.dumps(instance.request_messages).encode())

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    event.listen(Session, "loaded_as_persistent", materialized)
    try:
        items = await mechanisms.list_source_candidates("planner", limit=50)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
        event.remove(Session, "loaded_as_persistent", materialized)
    assert [(item.call_id, item.task_id, item.label) for item in items] == expected
    assert all(item.source_kind == "llm_call" and item.source_id == item.call_id for item in items)
    report = {"sources": len(items), "queries": len(statements), **loaded}
    destination = Path(__file__).resolve().parents[4] / "artifacts/lab-source-reads.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert report["queries"] == 1, report
    assert report["tasks"] == report["unused_trace_bytes"] == 0, report


@pytest.mark.asyncio
async def test_source_picker_keeps_fallbacks_validation_search_and_limits(db):
    now = datetime.now(timezone.utc)
    task = Task(label="Synthetic visible source", status=TaskStatus.SUCCESS)
    deleted = Task(label="Synthetic removed source", status=TaskStatus.SUCCESS)
    db.add_all([task, deleted])
    await db.flush()
    deleted.soft_delete()
    valid = [planner_call(task_id=task.id, created_at=now - timedelta(seconds=3),
                          effective_model="synthetic-effective"),
             planner_call(created_at=now - timedelta(seconds=2)),
             planner_call(task_id=deleted.id, created_at=now - timedelta(seconds=1))]
    invalid = planner_call(created_at=now)
    invalid.response_text = "not valid JSON"
    failed = planner_call(created_at=now)
    failed.status = "failed"
    unrelated = planner_call(created_at=now)
    unrelated.system_prompt = "Synthetic unrelated mechanism"
    db.add_all([*valid, invalid, failed, unrelated])
    await db.commit()
    expected_ids = [item.id for item in reversed(valid)]
    first_id = valid[0].id
    task_label = task.label
    db.expunge_all()
    items = await mechanisms.list_source_candidates("planner", limit=50)
    assert [item.call_id for item in items] == expected_ids
    assert items[-1].label == task_label
    assert items[-1].model == "synthetic-effective"
    assert all(item.label.startswith("planner · ") for item in items[:2])
    assert (await mechanisms.list_source_candidates("planner", limit=1)) == items[:1]
    assert [item.call_id for item in await mechanisms.list_source_candidates(
        "planner", search=" synthetic-effective ",
    )] == [first_id]
    assert await mechanisms.list_source_candidates("planner", search="unmatched synthetic term") == []
    assert await mechanisms.list_source_candidates("planner", agent_ids=[]) == []
    assert await mechanisms.list_source_candidates("planner") == items


@pytest.mark.asyncio
async def test_source_http_preserves_permissions_and_manager_scope(client):
    password = "synthetic-source-reader-password"
    async with get_db_session() as db:
        privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["PLANNER_EVALUATION_ACCESS", "AGENT_MANAGE_ALL"],
        )))).all())
        role = Role(code="synthetic-source-reader", privileges=[
            privilege for privilege in privileges if privilege.code == "PLANNER_EVALUATION_ACCESS"
        ])
        global_role = Role(code="synthetic-global-source-reader", privileges=privileges)
        hashed_password = encrypt_password(password)
        users = [UserModel(email=f"source-reader-{index}@example.com", hashed_password=hashed_password,
                           is_active=True) for index in range(3)]
        title = Title(label="Synthetic source reader", gender="N")
        db.add_all([role, global_role, title, *users])
        await db.flush()
        db.add_all([Assignment(user_id=users[0].id, role_id=role.id, is_default=True),
                    Assignment(user_id=users[1].id, role_id=global_role.id, is_default=True)])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-source-reader-{index}",
                        first_name="Synthetic", last_name=f"Reader {index}", job_title="Source reader")
                  for index, user in enumerate(users[:2])]
        db.add_all(agents)
        await db.flush()
        tasks = [Task(label=f"Synthetic managed source {index}", agent_id=agent.id)
                 for index, agent in enumerate(agents)]
        db.add_all(tasks)
        await db.flush()
        calls = [planner_call(task_id=task.id) for task in tasks]
        direct_call = planner_call(agent_id=agents[0].id)
        db.add_all([*calls, direct_call])
        await db.flush()
        own_ids = {str(calls[0].id), str(direct_call.id)}
        all_ids = {str(call.id) for call in [*calls, direct_call]}
    path = "/api/evaluation/planner/candidates"
    assert (await client.get(path)).status_code == 401
    headers = []
    for index in range(3):
        login = await client.post("/api/auth/login-json", json={
            "email": f"source-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert (await client.get(path, headers=headers[2])).status_code == 403
    for index, expected in enumerate((own_ids, all_ids)):
        response = await client.get(path, headers=headers[index])
        assert response.status_code == 200, response.text
        assert {item["call_id"] for item in response.json()} == expected
        assert (await client.get(path, headers=headers[index])).json() == response.json()
    assert (await client.get("/api/evaluation/goal_tracking/candidates", headers=headers[0])).status_code == 403
