from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.agent.models import Agent, Title
from app.task.models import Task, TaskStatus
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_child_summary_keeps_readable_delegations_without_execution_payloads(client):
    credentials = {"email": f"subtasks-{uuid4().hex}@example.com", "password": "Synthetic-task-password-42!"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    async with get_db_session() as db:
        user_id = await db.scalar(select(UserModel.id).where(UserModel.email == credentials["email"]))
        assert user_id is not None
        other_user = UserModel(email=f"outside-subtasks-{uuid4().hex}@example.com",
            hashed_password=encrypt_password(credentials["password"]), is_active=True)
        db.add(other_user)
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "TASK_ACCESS"))
        role = Role(code=f"subtasks-{uuid4().hex}", privileges=[privilege])
        db.add(role)
        await db.flush()
        await db.execute(delete(Assignment).where(Assignment.user_id == user_id))
        db.add(Assignment(user_id=user_id, role_id=role.id, is_default=True))

        title = Title(label="Synthetic role", gender="X")
        db.add(title)
        await db.flush()
        owner, teammate, outsider = [Agent(user_id=identity, title_id=title.id, code=f"subtask-{uuid4().hex}",
            first_name="Synthetic", last_name=f"Worker {index}") for index, identity in enumerate((user_id, user_id, other_user.id))]
        db.add_all([owner, teammate, outsider])
        await db.flush()
        parent = Task(label="Synthetic parent", agent_id=owner.id, status=TaskStatus.EXEC)
        db.add(parent)
        await db.flush()
        marker = {"peer_display": "Synthetic peer"}
        metadata = {
            "plan_step": 2,
            "pause_reasons": ["user"],
            "awaiting_reply": marker,
            "resolves_await": str(uuid4()),
            "objective_blocker": "Synthetic blocker",
        }
        checkpoint = "Synthetic execution checkpoint. " * 40_000
        child = Task(
            label="Synthetic delegated task", objective="<p>Check synthetic data</p>",
            parent_id=parent.id, source_task_id=parent.id, agent_id=teammate.id, requester_agent_id=owner.id,
            status=TaskStatus.SUCCESS, paused=True, cost=0.2,
            data={**metadata, "_agent_run_checkpoint": checkpoint}, execution_result={"result": checkpoint},
        )
        foreign_child = Task(label="Synthetic foreign child", parent_id=parent.id, agent_id=outsider.id)
        db.add_all([
            child,
            foreign_child,
            Task(label="Synthetic deleted child", parent_id=parent.id, agent_id=teammate.id,
                 deleted_at=datetime.now(timezone.utc)),
            Task(label="Synthetic causal link only", source_task_id=parent.id, agent_id=teammate.id),
        ])
        await db.flush()
        parent_id, child_id, foreign_id = parent.id, child.id, foreign_child.id

    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    path = f"/api/tasks/{parent_id}/children"
    response = await client.get(path, params={"summary": "true"})
    assert response.status_code == 200
    row, = response.json()
    assert row["id"] == str(child_id)
    assert row["label"] == "Synthetic delegated task"
    assert row["objective"] == "<p>Check synthetic data</p>"
    assert row["outcome"] == "BLOCKED"
    assert row["paused"] is True
    assert row["cost"] == 0.2
    assert {key: row["data"][key] for key in metadata} == metadata
    assert "_agent_run_checkpoint" not in row["data"]
    assert "execution_result" not in row

    full = await client.get(path)
    full_child, = full.json()
    assert full_child["id"] == str(child_id)
    assert full_child["data"]["_agent_run_checkpoint"] == checkpoint
    assert (await client.get(f"/api/tasks/{foreign_id}/children", params={"summary": "true"})).status_code == 404
