from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.task import call_recovery
from app.task.activity_snapshot import activity_snapshots
from app.task.call_recovery import TaskCallRecoveryCommand, deliver_recovery, request_recovery
from app.task.models import Task, TaskAttempt, TaskStatus
from app.task.task_service import TaskConflictError


async def running_task(db, driver_code="internal"):
    lease, run_id = uuid4(), uuid4()
    task = Task(label="Synthetic stalled model", objective="<p>Verify the report.</p>",
        status=TaskStatus.EXEC, lease_token=lease,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        data={"_agent_run_identity": {"request_run_id": str(run_id), "driver_code": driver_code,
            "local_interrupt": True, "call_recovery": True}})
    db.add(task)
    await db.flush()
    attempt = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", status="CLAIMED",
        worker_id="synthetic-worker", lease_token=lease, data={"agent_checkpoint": {"receipt": "synthetic-saved"}})
    db.add(attempt)
    await db.flush()
    return task, attempt, TaskCallRecoveryCommand(run_id=run_id, request_id=uuid4(), expected_control_version=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("driver_code", ["internal", "synthetic-recovery-driver"])
async def test_command_survives_worker_change_is_idempotent_and_preserves_task_and_effects(db, monkeypatch, accepted, driver_code):
    task, attempt, command = await running_task(db, driver_code)
    boundary = AsyncMock(return_value=accepted)
    monkeypatch.setattr(call_recovery, "request_call_recovery", boundary)
    state = await request_recovery(task.id, command)
    assert state.state == "requested"
    assert await request_recovery(task.id, command) == state
    assert (await activity_snapshots([task]))[0].call_recovery_supported
    assert (await activity_snapshots([task]))[0].call_recovery == state
    boundary.assert_not_awaited()  # The HTTP worker does not own the execution.
    task_id = task.id
    db.expire_all()  # Reload the durable command as its lease owner does.
    await deliver_recovery(task_id, uuid4())
    boundary.assert_not_awaited()
    await db.refresh(task)
    await deliver_recovery(task.id, task.lease_token)
    await deliver_recovery(task.id, task.lease_token)
    boundary.assert_awaited_once_with(driver_code, command.run_id)
    await db.refresh(attempt)
    completed = await request_recovery(task.id, command)
    assert completed.state == ("accepted" if accepted else "refused")
    assert attempt.data["agent_checkpoint"] == {"receipt": "synthetic-saved"}
    assert task.status == TaskStatus.EXEC
    assert not task.paused and not task.cancel_requested
    # An older command cannot interrupt a later generation after a second command.
    next_command = TaskCallRecoveryCommand(run_id=command.run_id, request_id=uuid4(), expected_control_version=1)
    await request_recovery(task.id, next_command)
    with pytest.raises(TaskConflictError):
        await request_recovery(task.id, command)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["run", "lease", "terminal", "paused", "cancelled", "unsupported"])
async def test_old_or_unavailable_execution_is_never_interrupted(db, monkeypatch, change):
    task, attempt, command = await running_task(db)
    await request_recovery(task.id, command)
    boundary = AsyncMock(return_value=True)
    monkeypatch.setattr(call_recovery, "request_call_recovery", boundary)
    original_lease = task.lease_token
    if change == "run":
        task.data = {"_agent_run_identity": {"request_run_id": str(uuid4()), "driver_code": "internal",
            "local_interrupt": True, "call_recovery": True}}
    elif change == "lease":
        task.lease_token = uuid4()
    elif change == "terminal":
        task.status = TaskStatus.SUCCESS
    elif change == "paused":
        task.paused = True
    elif change == "cancelled":
        task.cancel_requested = True
    else:
        task.data = {"_agent_run_identity": {"request_run_id": str(command.run_id), "driver_code": "hermes"}}
    await db.flush()
    await deliver_recovery(task.id, original_lease)
    boundary.assert_not_awaited()
    with pytest.raises(TaskConflictError):
        await request_recovery(task.id, command)
    assert attempt.data["call_recovery"]["state"] == "requested"


@pytest.mark.asyncio
async def test_http_controls_enforce_edit_privilege_agent_scope_and_execution_identity(committed_database, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import delete, select
    from app.agent.models import Agent, Title
    from core import settings
    from core.authorize import Assignment, Privilege, Role
    from core.database import get_db_session, middleware
    from core.user import UserModel
    from core.user.user_service import encrypt_password
    from main import app

    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    credentials = [{"email": f"recovery-{uuid4().hex}@example.com", "password": "Synthetic-call-recovery-42!"} for _ in range(2)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
        async with get_db_session() as db:
            users = [UserModel(email=credential["email"],
                hashed_password=encrypt_password(credential["password"]), is_active=True)
                for credential in credentials]
            db.add_all(users)
            await db.flush()
            for user, code in zip(users, ["TASK_EDIT", "TASK_ACCESS"]):
                privilege = await db.scalar(select(Privilege).where(Privilege.code == code))
                role = Role(code=f"synthetic-recovery-{uuid4().hex}", privileges=[privilege])
                db.add(role)
                await db.flush()
                await db.execute(delete(Assignment).where(Assignment.user_id == user.id))
                db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            title = Title(label="Synthetic title", gender="F")
            db.add(title)
            await db.flush()
            agents = [Agent(user_id=user.id, title_id=title.id, code=f"recovery-{uuid4().hex}",
                first_name="Synthetic", last_name="Worker") for user in users]
            db.add_all(agents)
            await db.flush()
            task, attempt, command = await running_task(db)
            task.agent_id = agents[0].id
            outsider, _, outside_command = await running_task(db)
            outsider.agent_id = agents[1].id
            task_id, attempt_id, outsider_id = task.id, attempt.id, outsider.id
        headers = []
        for credential in credentials:
            http.cookies.clear()
            login = await http.post("/api/auth/login-json", json=credential)
            assert login.status_code == 200, login.text
            headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
        url = f"/api/tasks/{task_id}/recover-call"
        denied = await http.post(url, headers=headers[1], json=command.model_dump(mode="json"))
        assert denied.status_code == 403
        hidden = await http.post(f"/api/tasks/{outsider_id}/recover-call", headers=headers[0], json=outside_command.model_dump(mode="json"))
        assert hidden.status_code == 404
        stale = await http.post(url, headers=headers[0], json={**command.model_dump(mode="json"), "run_id": str(uuid4())})
        assert stale.status_code == 409
        for _ in range(2):
            accepted = await http.post(url, headers=headers[0], json=command.model_dump(mode="json"))
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["state"] == "requested"
            assert accepted.json()["version"] == 1
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            attempt = await db.get(TaskAttempt, attempt_id)
            assert task.status == TaskStatus.EXEC and not task.cancel_requested
            assert attempt.data["agent_checkpoint"] == {"receipt": "synthetic-saved"}
            assert attempt.data["call_recovery"] == accepted.json()

        # Emergency termination preserves authorization, but never rejects an old view.
        from app import agent as agent_domain
        from app.task import task_service

        monkeypatch.setattr(agent_domain, "handle_terminal_task", AsyncMock())
        monkeypatch.setattr(task_service.websocket, "emit", AsyncMock())
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            task.feedback = "Synthetic progress after opening the task"
        stop_url = f"/api/tasks/{task_id}/force-terminate"
        denied = await http.post(stop_url, headers=headers[1], json={"expected_revision": 1})
        assert denied.status_code == 403
        hidden = await http.post(f"/api/tasks/{outsider_id}/force-terminate", headers=headers[0], json={"expected_revision": 1})
        assert hidden.status_code == 404
        for _ in range(2):
            stopped = await http.post(stop_url, headers=headers[0], json={"expected_revision": 1})
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["status"] == "ERROR"
            assert stopped.json()["paused"] is False
        async with get_db_session() as db:
            task = await db.get(Task, task_id)
            attempt = await db.get(TaskAttempt, attempt_id)
            assert task.lease_token is None
            assert attempt.status == "CANCELLED"
