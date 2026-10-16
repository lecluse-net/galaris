"""Live personal work remains recognizable across conversation rooms."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.conversation.contracts import ConversationTurn
from app.conversation.facade import active_work_snapshot
from app.harness.conversation import _system_prompt
from app.process.models import ProcessDefinition, ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from app.task.models import Task, TaskStatus
from app.tools.models import Tool
from core.params import Params, prompt_default


@pytest.mark.asyncio
async def test_live_work_prompt_keeps_old_waits_and_excludes_finished_stopped_and_other_agents(
    db: AsyncSession,
) -> None:
    title = Title(label="Synthetic activity", gender="X")
    tool = Tool(code=f"active-work-{uuid4().hex}", label="Synthetic engine", connection_schema={})
    db.add_all([title, tool])
    await db.flush()
    agents = [Agent(title_id=title.id, first_name=name, last_name="Synthetic", code=uuid4().hex)
        for name in ("Owner", "Other")]
    db.add_all(agents)
    await db.flush()
    owner, other = agents
    old = datetime.now(timezone.utc) - timedelta(days=90)
    tasks = [
        Task(agent_id=owner.id, label="Old question", objective="<p>Which fictional planet?</p>",
            status=TaskStatus.DISPATCH, paused=True, created_at=old,
            message_group_id="another-synthetic-room", data={"pause_reasons": ["clarify"],
                "clarification_questions": ["Which fictional planet?"]}),
        Task(agent_id=owner.id, label="Executing", status=TaskStatus.EXEC, lease_token=uuid4()),
        Task(agent_id=owner.id, label="Queued", status=TaskStatus.CREATE),
        Task(agent_id=owner.id, label="Manual hold", status=TaskStatus.DISPATCH, paused=True,
            data={"pause_reasons": ["user", "await"]}),
        Task(agent_id=owner.id, label="Stopping", status=TaskStatus.EXEC, cancel_requested=True),
        Task(agent_id=other.id, label="Other agent", status=TaskStatus.EXEC),
        *[Task(agent_id=owner.id, label=f"Finished {status.value}", status=status,
            data={"working_set": {"resources": "must not parse historical data"}})
            for status in (TaskStatus.SUCCESS, TaskStatus.ERROR)],
    ]
    definition = ProcessDefinition(agent_id=owner.id, tool_id=tool.id,
        engine_process_id=uuid4().hex, label="Synthetic workflow")
    db.add_all([*tasks, definition])
    await db.flush()
    runs: dict[str, ProcessRun] = {}
    for label, status, metadata, agent_id in [
        ("Running process", "running", {}, owner.id),
        ("Human question", "running", {}, owner.id),
        ("Participant process", "waiting", {}, other.id),
        ("Completed process", "success", {}, owner.id),
        ("Failed process", "error", {}, owner.id),
        ("Cancelled process", "cancelled", {}, owner.id),
        ("Stopping process", "cancelling", {}, owner.id),
        ("Cancellation requested", "running", {"cancel_requested": True}, owner.id),
        ("Paused process", "running", {"paused": True}, owner.id),
        ("Other process", "running", {}, other.id),
    ]:
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent_id,
            engine_code="galaris" if label == "Human question" else "fake",
            correlation_id=uuid4().hex, callback_token=uuid4().hex, status=status,
            created_at=old, engine_metadata={"native": metadata},
            launch_snapshot={"process_label": label, "workflow_id": "synthetic-workflow",
                "participant_agents": [owner.id] if label == "Participant process" else [agent_id]})
        db.add(run)
        runs[label] = run
    await db.flush()
    occurrence = ProcessNodeRun(run_id=runs["Human question"].id, node_key="ask",
        occurrence="ask:0", status="waiting", context={}, started_at=old)
    db.add(occurrence)
    await db.flush()
    db.add(ProcessNodeAttempt(node_run_id=occurrence.id, status="human_waiting",
        prompt="Supply the fictional launch code.", input={}))
    await db.flush()

    work = await active_work_snapshot(owner.id)
    by_label = {item["label"]: item for item in work}
    assert set(by_label) == {"Old question", "Executing", "Queued", "Running process", "Human question", "Participant process"}
    assert by_label["Old question"]["operational_state"] == "WAITING"
    assert by_label["Executing"]["operational_state"] == "RUNNING"
    assert by_label["Queued"]["operational_state"] == "QUEUED"
    assert by_label["Human question"]["operational_state"] == "WAITING"
    turn = ConversationTurn(room_id=uuid4(), round_id=uuid4(), agent_id=owner.id,
        language="en", objective="The launch code is imaginary-42.", messages=(), active_work=work,
        # Historical room context must not reintroduce stopped/finished work.
        linked_work=({"task_id": "finished", "status": "SUCCESS", "label": "Excluded history"},
            {"task_id": "held", "status": "EXEC", "pause_reasons": ["user"], "label": "Excluded hold"}))
    for executor in ("conversation", "voice"):
        prompt = _system_prompt(turn, SimpleNamespace(code="synthetic"), executor=executor,
            tool_advertisement="", process_advertisement="",
            action_policy=prompt_default(Params.AI_CONVERSATION_ACTION_POLICY) or "")
        assert "Which fictional planet?" in prompt
        assert "Supply the fictional launch code." in prompt
        assert f"galaris://task/{tasks[0].id}" in prompt
        assert str(runs["Human question"].id) in prompt
        assert "Excluded history" not in prompt and "Excluded hold" not in prompt
        assert "current message and attachments" in prompt

    tasks[0].status = TaskStatus.SUCCESS
    runs["Human question"].status = "cancelled"
    await db.flush()
    refreshed = await active_work_snapshot(owner.id)
    assert "Old question" not in {item["label"] for item in refreshed}
    assert "Human question" not in {item["label"] for item in refreshed}


@pytest.mark.asyncio
async def test_active_work_api_enforces_privileges_scope_and_pagination(client) -> None:
    from sqlalchemy import select
    from core.authorize.models import Assignment, Privilege, Role, RolePrivilege
    from core.database import get_db_session
    from core.user import UserModel
    from core.user.user_service import encrypt_password

    suffix = uuid4().hex
    password = "Synthetic-active-work-password-42!"
    async with get_db_session() as db:
        users = [UserModel(email=f"active-work-{i}-{suffix}@example.com", is_active=True,
            hashed_password=encrypt_password(password)) for i in range(4)]
        roles = [Role(code=f"active-work-{i}-{suffix}") for i in range(3)]
        title = Title(label="Synthetic monitoring", gender="X")
        tool = Tool(code=f"monitor-{suffix}", label="Synthetic engine", connection_schema={})
        db.add_all([*users, *roles, title, tool])
        await db.flush()
        privileges = {p.code: p.id for p in await db.scalars(select(Privilege).where(
            Privilege.code.in_(["TASK_ACCESS", "PROCESS_READ"])))}
        assert len(privileges) == 2
        for index, codes in enumerate((["TASK_ACCESS", "PROCESS_READ"], ["TASK_ACCESS"], ["PROCESS_READ"])):
            db.add_all(RolePrivilege(role_id=roles[index].id, privilege_id=privileges[code]) for code in codes)
        for index, user in enumerate(users):
            db.add(Assignment(user_id=user.id, role_id=roles[max(0, index - 1)].id, is_default=True))
        agent = Agent(user_id=users[0].id, title_id=title.id, first_name="Monitor", last_name="Synthetic", code=suffix)
        db.add(agent)
        await db.flush()
        definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id,
            engine_process_id=suffix, label="Synthetic monitoring process")
        db.add(definition)
        await db.flush()
        db.add_all(Task(agent_id=agent.id, label=f"Pending {index}", status=TaskStatus.CREATE) for index in range(2))
        db.add(Task(agent_id=agent.id, label="Finished", status=TaskStatus.SUCCESS))
        for engine in ("galaris", "n8n"):
            db.add(ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code=engine,
                correlation_id=uuid4().hex, callback_token=uuid4().hex, status="waiting",
                launch_snapshot={"process_label": f"Synthetic {engine}", "workflow_id": suffix}))
        await db.commit()
        agent_id = agent.id
        emails = [user.email for user in users]
    url = f"/api/conversations/agents/{agent_id}/active-work"
    assert (await client.get(url)).status_code == 401
    for index, expected in ((1, 404), (2, 403), (3, 403), (0, 200)):
        login = await client.post("/api/auth/login-json", json={"email": emails[index], "password": password})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.get(url, headers=headers)
        assert response.status_code == expected, response.text
        if expected != 200:
            continue
        payload = response.json()
        assert payload["agent_id"] == agent_id and payload["total"] == 4
        assert payload["page_size"] == 50
        assert {item["kind"] for item in payload["items"]} == {"task", "process"}
        assert {item["engine_code"] for item in payload["items"] if item["kind"] == "process"} == {"galaris", "n8n"}
        assert all(item["operational_state"] in {"QUEUED", "WAITING"} for item in payload["items"])
        first = await client.get(url, params={"page_size": 2}, headers=headers)
        second = await client.get(url, params={"page_size": 2, "page": 2}, headers=headers)
        assert first.status_code == second.status_code == 200
        assert {item["id"] for item in first.json()["items"]}.isdisjoint(item["id"] for item in second.json()["items"])
        assert (await client.get(url, params={"page_size": 500}, headers=headers)).status_code == 200
        assert (await client.get(url, params={"page_size": 501}, headers=headers)).status_code == 422
        assert (await client.get(f"/api/conversations/agents/{agent_id + 1000000}/active-work", headers=headers)).status_code == 404
