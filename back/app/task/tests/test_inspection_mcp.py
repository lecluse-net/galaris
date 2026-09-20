"""Integration tests for task and LLM-call inspection MCP tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.llm import llm_call_service
from app.llm.mcp import inspect_llm_calls, mcp_llm_call, mcp_llm_calls
from app.llm.models import LLMCall
from app.task.mcp import inspect_tasks, mcp_task, mcp_tasks
from app.task.models import Task, TaskAmendment, TaskAttempt, TaskStatus
from app.tools.mcp_loader import McpToolContext

_CTX = McpToolContext(agent_id=1, runtime="internal")


@pytest.mark.asyncio
async def test_task_get_exposes_latest_attempt_while_work_is_running(db):
    from app.task.mcp import mcp_get_task

    agent = await _agent(db)
    lease = uuid4()
    task = Task(agent_id=agent.id, label="Running", objective="Work", status=TaskStatus.EXEC,
                lease_token=lease, attempt_count=2)
    db.add(task)
    await db.flush()
    attempt = TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", status="CLAIMED",
                          worker_id="worker", lease_token=lease)
    db.add(attempt)
    await db.flush()
    response = await mcp_get_task(McpToolContext(agent_id=agent.id, runtime="internal"), str(task.id))
    assert response["latest_attempt"]["id"] == str(attempt.id)
    assert response["latest_attempt"]["attempt_number"] == response["attempt_count"] == 2
    assert response["activity"]["operational"]["operational_state"] == "RUNNING"
    assert response["activity"]["last_activity_at"] is not None


@pytest.mark.asyncio
async def test_task_access_separates_delegated_reads_from_management_and_live_admin(db):
    from sqlalchemy import select
    from app.connection import Connection
    from app.tools import ToolModel
    from app.task.mcp import mcp_get_task, mcp_stop_task
    from app.task.resource_facade import list_task_resources, read_task_resource
    from core.team import TeamModel
    from app.agent.dialogue_service import set_agent_membership

    owner = await _agent(db)
    peer = await _agent(db)
    team = TeamModel(name="Same team does not grant task management")
    db.add(team)
    await db.flush()
    for agent in (owner, peer):
        await set_agent_membership(team.id, agent.id, True)
    target = Task(agent_id=owner.id, label="Private task", objective="Private objective")
    db.add(target)
    await db.flush()
    ctx = McpToolContext(agent_id=peer.id, runtime="internal")
    uri = f"galaris://task/{target.id}"
    for selector in (uri, str(target.id)[:8]):
        with pytest.raises(PermissionError):
            await mcp_get_task(ctx, selector)
        with pytest.raises(PermissionError):
            await mcp_stop_task(ctx, selector)
    assert await read_task_resource(target.id, actor_agent_id=peer.id) is None
    assert await list_task_resources(actor_agent_id=peer.id) == []

    target.requester_agent_id = peer.id
    await db.flush()
    assert (await mcp_get_task(ctx, uri))["id"] == str(target.id)
    with pytest.raises(PermissionError):
        await mcp_stop_task(ctx, uri)
    target.requester_agent_id = None

    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris_admin"))
    connection = Connection(agent_id=peer.id, tool_id=tool.id, active=False)
    db.add(connection)
    await db.flush()
    with pytest.raises(PermissionError):
        await mcp_stop_task(ctx, uri)
    connection.active = True
    await db.flush()
    assert (await mcp_get_task(ctx, uri))["id"] == str(target.id)
    assert await read_task_resource(target.id, actor_agent_id=peer.id) is not None
    assert [row["id"] for row in await list_task_resources(actor_agent_id=peer.id)] == [str(target.id)]
    connection.active = False
    await db.flush()
    with pytest.raises(PermissionError):
        await mcp_get_task(ctx, uri)
    with pytest.raises(PermissionError):
        await mcp_stop_task(ctx, uri)
    assert target.status == TaskStatus.CREATE
    connection.active = True
    await db.flush()
    assert (await mcp_stop_task(ctx, uri))["stopped"] is True
    assert target.status == TaskStatus.ERROR

    own_task = Task(agent_id=peer.id, label="Own task", objective="Own objective")
    db.add(own_task)
    connection.active = False
    await db.flush()
    assert (await mcp_stop_task(ctx, str(own_task.id)))["stopped"] is True


async def _agent(db: AsyncSession) -> Agent:
    title = Title(label="Mx", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Ada",
        last_name="Lovelace",
        job_title="Analyst",
        code=f"ada-{uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_task_returns_complete_json_with_relations(db: AsyncSession) -> None:
    agent = await _agent(db)
    created_at = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)
    task = Task(
        label="Inspect me",
        objective="Complete objective",
        status=TaskStatus.DISPATCH,
        paused=True,
        agent_id=agent.id,
        data={"language": "en", "key": "value", "pause_reasons": ["await"]},
        created_at=created_at,
    )
    db.add(task)
    await db.flush()
    child = Task(
        label="Child",
        objective="Child objective",
        parent_id=task.id,
        agent_id=agent.id,
        paused=True,
        data={
            "pause_reasons": ["await"],
            "awaiting_reply": {
                "peer_user_id": "sophie",
                "peer_display": "Sophie",
                "deadline": "2026-07-15T09:30:00+00:00",
            },
        },
        created_at=created_at + timedelta(minutes=1),
    )
    call = LLMCall(
        task_id=task.id,
        agent_id=agent.id,
        provider_name="test-provider",
        requested_model="test-model",
        effective_model="test-model",
        request_messages=[{"role": "user", "content": "hello"}],
        prompt="hello",
        response_text="world",
        started_at=created_at + timedelta(minutes=2),
        created_at=created_at + timedelta(minutes=2),
        updated_at=created_at + timedelta(minutes=2),
    )
    dream_call = LLMCall(
        task_id=task.id,
        agent_id=agent.id,
        correlation_ref=f"dream-receipt:{uuid4()}",
        provider_name="dream-provider",
        requested_model="dream-model",
        effective_model="dream-model",
        request_messages=[{"role": "user", "content": "extract memory"}],
        prompt="extract memory",
        response_text='{"operations":[]}',
        started_at=created_at + timedelta(minutes=3),
        created_at=created_at + timedelta(minutes=3),
        updated_at=created_at + timedelta(minutes=3),
    )
    attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=1,
        phase="EXEC",
        status="SUCCESS",
        worker_id="worker-1",
        lease_token=uuid4(),
        data={"checkpoint": "done"},
    )
    amendment = TaskAmendment(
        task_id=task.id,
        source_kind="conversation_round",
        source_id="text:round-1",
        idempotency_key="inspection-amendment-key",
        disposition="AMEND_QUEUED",
        instruction="Also produce a PDF.",
        reason="Same deliverable.",
    )
    db.add_all([child, call, dream_call, attempt, amendment])
    await db.commit()

    task_calls = await llm_call_service.list_calls(task_id=task.id)
    assert [item.id for item in task_calls] == [call.id]

    raw = await mcp_task(McpToolContext(agent_id=agent.id, runtime="internal"), str(task.id))
    payload = json.loads(raw)

    assert payload["id"] == str(task.id)
    assert payload["resource_uri"] == f"galaris://task/{task.id}"
    assert payload["objective"] == "<p>Complete objective</p>"
    assert payload["data"]["key"] == "value"
    assert payload["owner"] == {
        "id": agent.id,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "code": agent.code,
        "job_title": "Analyst",
    }
    assert payload["subtasks"][0]["id"] == str(child.id)
    assert payload["subtasks"][0]["resource_uri"] == f"galaris://task/{child.id}"
    assert payload["subtasks"][0]["objective"] == "<p>Child objective</p>"
    assert payload["llm_calls"] == [str(call.id)]
    assert payload["attempts"][0]["attempt_number"] == 1
    assert payload["amendments"][0]["id"] == str(amendment.id)
    assert payload["amendments"][0]["instruction"] == "Also produce a PDF."
    assert payload["operational_state"] == "WAITING"
    assert payload["waits"][0]["peer_display"] == "Sophie"
    assert payload["waits"][0]["question"] == "Child objective"


@pytest.mark.asyncio
async def test_tasks_filters_inclusive_range_and_owner(db: AsyncSession) -> None:
    agent = await _agent(db)
    start = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
    first = Task(
        label="First",
        objective="At the beginning",
        agent_id=agent.id,
        created_at=start,
    )
    last = Task(
        label="Last",
        objective="At the end",
        agent_id=agent.id,
        created_at=end,
    )
    outside = Task(
        label="Outside",
        objective="Too late",
        agent_id=agent.id,
        created_at=end + timedelta(microseconds=1),
    )
    db.add_all([first, last, outside])
    await db.commit()

    raw = await mcp_tasks(McpToolContext(agent_id=agent.id, runtime="internal"), start, end, limit=1)
    payload = json.loads(raw)

    assert payload == [{
        "id": str(last.id),
        "resource_uri": f"galaris://task/{last.id}",
        "label": "Last",
        "objective": "At the end",
        "owner": {
            "id": agent.id,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "code": agent.code,
            "job_title": "Analyst",
        },
        "created_at": end.isoformat(),
    }]


@pytest.mark.asyncio
async def test_llm_call_and_llm_calls_return_complete_json_and_ids(db: AsyncSession) -> None:
    agent = await _agent(db)
    start = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
    task = Task(
        label="Owner task",
        objective="Task objective",
        agent_id=agent.id,
        created_at=start,
    )
    db.add(task)
    await db.flush()
    first = LLMCall(
        task_id=task.id,
        agent_id=agent.id,
        provider_name="provider",
        requested_model="requested",
        effective_model="effective",
        request_messages=[{"role": "user", "content": "question"}],
        prompt="question",
        system_prompt="system",
        response_text="answer",
        reasoning="reasoning",
        tool_calls=[{"id": "tool-1", "name": "demo", "arguments": {}}],
        usage={"prompt_tokens": 3},
        input_tokens=3,
        output_tokens=4,
        total_tokens=7,
        cost=0.25,
        started_at=start,
        created_at=start,
        updated_at=start,
    )
    last = LLMCall(
        provider_name="provider",
        requested_model="requested",
        effective_model="effective",
        started_at=end,
        created_at=end,
        updated_at=end,
    )
    outside = LLMCall(
        provider_name="provider",
        requested_model="requested",
        effective_model="effective",
        started_at=end + timedelta(microseconds=1),
        created_at=end + timedelta(microseconds=1),
        updated_at=end + timedelta(microseconds=1),
    )
    db.add_all([first, last, outside])
    await db.commit()

    from sqlalchemy import select
    from app.connection import Connection
    from app.tools import ToolModel
    admin_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris_admin"))
    assert admin_tool is not None
    ctx = McpToolContext(agent_id=agent.id, runtime="internal")
    with pytest.raises(PermissionError):
        await mcp_llm_call(ctx, str(first.id))
    with pytest.raises(PermissionError):
        await mcp_llm_calls(ctx, start, end, limit=2)
    connection = Connection(agent_id=agent.id, tool_id=admin_tool.id, active=True)
    db.add(connection)
    await db.commit()
    detail = json.loads(await mcp_llm_call(ctx, str(first.id)))
    ids = json.loads(await mcp_llm_calls(ctx, start, end, limit=2))
    connection.active = False
    await db.commit()
    with pytest.raises(PermissionError):
        await mcp_llm_call(ctx, str(first.id))
    with pytest.raises(PermissionError):
        await mcp_llm_calls(ctx, start, end, limit=2)

    assert detail["id"] == str(first.id)
    assert detail["request_messages"] == [{"role": "user", "content": "question"}]
    assert detail["reasoning"] == "reasoning"
    assert detail["tool_calls"][0]["id"] == "tool-1"
    assert detail["total_tokens"] == 7
    assert detail["task"]["id"] == str(task.id)
    assert detail["task"]["resource_uri"] == f"galaris://task/{task.id}"
    assert detail["task_uri"] == f"galaris://task/{task.id}"
    assert detail["owner"]["id"] == agent.id
    assert ids == [str(last.id), str(first.id)]


@pytest.mark.asyncio
async def test_inspection_ranges_require_timezone_order_and_bounded_limit() -> None:
    aware = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="timezone"):
        await inspect_tasks(datetime(2026, 7, 15, 8, 0), aware)
    with pytest.raises(ValueError, match="earlier"):
        await inspect_llm_calls(aware + timedelta(hours=1), aware)
    with pytest.raises(ValueError, match="between 1 and 100"):
        await inspect_tasks(aware, aware, limit=101)
