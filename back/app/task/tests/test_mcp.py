from datetime import datetime, timezone
from inspect import signature
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.task import mcp as task_mcp
from app.task.models import Task, TaskStatus
from app.tools.mcp_loader import McpToolContext


async def _persist_inspected_task(db, task):
    from app.agent.models import Agent, Title

    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    db.add(Agent(id=task.agent_id, code=f"inspection-{uuid4()}", first_name="Agent", last_name="Inspection", title_id=title.id))
    await db.flush()
    db.add(task)
    await db.flush()


def test_task_get_requires_one_canonical_selector_and_is_replay_safe() -> None:
    parameters = signature(task_mcp.mcp_get_task).parameters
    assert list(parameters) == ["ctx", "task_id"]
    assert parameters["task_id"].default is parameters["task_id"].empty
    definition = task_mcp.mcp_get_task.__galaris_mcp_tool__
    assert definition.effect_policy == "read"
    assert definition.concurrency_policy == "safe"


def _task(**kw: Any) -> Task:
    defaults = dict(
        id=uuid4(),
        label="Task",
        objective="Objective",
        status=TaskStatus.EXEC,
        plan=None,
        data={"language": "en"},
        cost=0.0,
        parent_id=None,
        agent_id=7,
        feedback=None,
        execution_result=None,
    )
    defaults.update(kw)
    return Task(**defaults)


def test_task_outcome_distinguishes_a_skipped_plan_leaf_from_its_error_phase() -> None:
    skipped = _task(
        status=TaskStatus.ERROR,
        data={"plan_skipped": True},
    )
    failed = _task(status=TaskStatus.ERROR)

    assert task_mcp._task_outcome(skipped) == "SKIPPED"  # pyright: ignore[reportPrivateUsage]
    assert task_mcp._task_outcome(failed) == "ERROR"  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_create_task_never_auto_approves(monkeypatch: pytest.MonkeyPatch) -> None:
    """An agent-created MCP task never carries auto_approve, preventing privilege escalation."""
    added: list[Task] = []

    class _DB:
        def add(self, task: Task) -> None:
            added.append(task)

    monkeypatch.setattr(task_mcp, "get_db", lambda: _DB())

    await task_mcp.create_task(
        requester_agent_id=1,
        agent_id=2,
        label="Do something",
        objective="Delegated objective",
    )

    assert len(added) == 1
    assert added[0].auto_approve is False


@pytest.mark.asyncio
async def test_create_task_nests_under_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delegated task is a direct child marked delegated so its creator waits for it."""
    added: list[Task] = []
    topic_id = uuid4()
    contact_memory_item_id = uuid4()

    class _DB:
        def add(self, task: Task) -> None:
            added.append(task)

        async def scalar(self, _query: object) -> Task:
            return source

        async def get(self, _model: object, _id: object) -> Task:
            return source

    grandparent_id = uuid4()
    source = _task(
        parent_id=grandparent_id,
        topic_id=topic_id,
        contact_memory_item_id=contact_memory_item_id,
    )  # Task owned by the calling agent.

    monkeypatch.setattr(task_mcp, "get_db", lambda: _DB())
    from app.task import task_service

    monkeypatch.setattr(task_service, "get_db", lambda: _DB())
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=source))

    await task_mcp.create_task(
        requester_agent_id=1,
        agent_id=2,
        label="Delegation",
        objective="Delegated objective",
        source_task_id=source.id,
    )

    assert len(added) == 1
    assert added[0].source_task_id == source.id
    assert added[0].parent_id == source.id  # Direct child of its creator.
    assert (added[0].data or {}).get("delegated") is True
    assert added[0].topic_id == topic_id
    assert added[0].contact_memory_item_id == contact_memory_item_id


@pytest.mark.asyncio
async def test_delegation_blocked_when_creator_user_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task paused by a human cannot create a subtask."""
    from app.task import task_service

    held = _task(paused=True, data={"pause_reasons": ["user"]})
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=held))
    msg = await task_mcp._delegation_blocked_message(held.id)  # pyright: ignore[reportPrivateUsage]
    assert msg is not None and "pause" in msg.lower()

    # Automatic child waiting is not a human pause, so delegation is allowed.
    waiting = _task(paused=True, data={"pause_reasons": ["child"]})
    monkeypatch.setattr(task_service, "get_by_id", AsyncMock(return_value=waiting))
    assert await task_mcp._delegation_blocked_message(waiting.id) is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_task_run_raises_when_delegation_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "core.database.database.get_db_session",
        lambda: _Session(),
    )
    monkeypatch.setattr(
        task_mcp,
        "_delegation_blocked_message",
        AsyncMock(return_value="Delegation blocked."),
    )

    with pytest.raises(ValueError, match="Delegation blocked"):
        await task_mcp.mcp_run_task(
            McpToolContext(agent_id=7, runtime="hermes", task_id=uuid4()),
            agent_id=8,
            label="Subtask",
            objective="Execute",
        )


@pytest.mark.asyncio
async def test_task_run_returns_canonical_task_uri(
    monkeypatch: pytest.MonkeyPatch,
    db,
) -> None:
    from core.team import TeamModel
    from app.agent.models import Agent, Title
    from app.agent.dialogue_service import set_agent_membership

    team = TeamModel(name="Delegation team")
    title = Title(label="Mx", gender="M")
    db.add_all([team, title])
    await db.flush()
    db.add_all([Agent(id=aid, code=f"peer-{aid}", first_name="Peer", last_name=str(aid), title_id=title.id) for aid in (7, 8)])
    await db.flush()
    await set_agent_membership(team.id, 7, True)
    await set_agent_membership(team.id, 8, True)

    task_id = uuid4()
    monkeypatch.setattr(
        task_mcp,
        "_delegation_blocked_message",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        task_mcp,
        "_delegation_target_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(task_mcp, "run_task", AsyncMock(return_value=str(task_id)))
    monkeypatch.setattr("app.task.runner.go_next", lambda *_args, **_kwargs: None)

    result = await task_mcp.mcp_run_task(
        McpToolContext(agent_id=7, runtime="hermes", task_id=uuid4()),
        agent_id=8,
        label="Subtask",
        objective="Execute",
    )

    assert result == f"galaris://task/{task_id}"

    await set_agent_membership(team.id, 8, False)
    with pytest.raises(PermissionError):
        await task_mcp.mcp_run_task(
            McpToolContext(agent_id=7, runtime="hermes", task_id=uuid4()),
            agent_id=8, label="Denied", objective="Execute",
        )
    task_mcp.run_task.assert_awaited_once()

    from sqlalchemy import select
    from app.connection import Connection
    from app.tools import ToolModel

    admin_tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris_admin"))
    db.add(Connection(agent_id=7, tool_id=admin_tool.id, active=True))
    await db.flush()
    result = await task_mcp.mcp_run_task(
        McpToolContext(agent_id=7, runtime="internal"),
        agent_id=8, label="Administrative delegation", objective="Execute",
    )
    assert result == f"galaris://task/{task_id}"
    assert task_mcp.run_task.await_count == 2


@pytest.mark.asyncio
async def test_task_run_rejects_a_missing_target_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        task_mcp,
        "_delegation_blocked_message",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        task_mcp,
        "_delegation_target_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(task_mcp, "_context_language", AsyncMock(return_value="en"))
    run_task = AsyncMock()
    monkeypatch.setattr(task_mcp, "run_task", run_task)

    with pytest.raises(ValueError, match="Agent 17 does not exist"):
        await task_mcp.mcp_run_task(
            McpToolContext(agent_id=7, runtime="internal", task_id=uuid4()),
            agent_id=17,
            label="Missing peer",
            objective="Review the implementation.",
        )

    run_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_run_rejects_self_delegation_before_creating_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("core.database.database.get_db_session", lambda: _Session())
    run_task = AsyncMock()
    monkeypatch.setattr(task_mcp, "run_task", run_task)
    monkeypatch.setattr(task_mcp, "_context_language", AsyncMock(return_value="en"))

    with pytest.raises(ValueError, match="Self-delegation rejected"):
        await task_mcp.mcp_run_task(
            McpToolContext(agent_id=2, runtime="hermes", task_id=uuid4()),
            agent_id=2,
            label="Ask Vega",
            objective="Ask Vega to choose.",
        )

    run_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_task_refuses_current_root(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _task()
    ctx = McpToolContext(agent_id=7, runtime="internal", task_id=target.id)
    monkeypatch.setattr(task_mcp, "_resolve_task", AsyncMock(return_value=target))
    monkeypatch.setattr(task_mcp, "_current_root_id", AsyncMock(return_value=target.id))
    monkeypatch.setattr(task_mcp, "_context_language", AsyncMock(return_value="en"))

    with pytest.raises(ValueError, match="Self-stop"):
        await task_mcp.stop_task(ctx, task_id=str(target.id))


@pytest.mark.asyncio
async def test_stop_task_marks_root_and_children_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _task(status=TaskStatus.DISPATCH, paused=True)
    child = _task(parent_id=root.id, status=TaskStatus.DISPATCH)
    done = _task(parent_id=root.id, status=TaskStatus.SUCCESS)
    updated: list[Task] = []

    async def fake_children(parent_id):
        return [child, done] if parent_id == root.id else []

    async def fake_update(_task_id, task):
        updated.append(task)
        return task

    monkeypatch.setattr(task_mcp, "_resolve_task", AsyncMock(return_value=root))
    monkeypatch.setattr(task_mcp, "_current_root_id", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(task_mcp, "_children", fake_children)
    monkeypatch.setattr("app.task.task_service.update", fake_update)
    monkeypatch.setattr("app.task.scheduler.cancel", lambda _task_id: False)
    monkeypatch.setattr("app.task.scheduler.wake", lambda *args, **kwargs: None)

    result = await task_mcp.stop_task(
        McpToolContext(agent_id=root.agent_id, runtime="internal"),
        task_id=f"galaris://task/{root.id}",
        reason="planning is too expensive",
    )

    assert result["stopped"] is True
    assert result["resource_uri"] == f"galaris://task/{root.id}"
    assert result["stopped_task_uris"] == [
        f"galaris://task/{root.id}",
        f"galaris://task/{child.id}",
    ]
    assert {task.id for task in updated} == {root.id, child.id}
    assert root.status == TaskStatus.ERROR
    assert child.status == TaskStatus.ERROR
    assert done.status == TaskStatus.SUCCESS
    assert "planning is too expensive" in (root.feedback or "")


@pytest.mark.asyncio
async def test_get_task_exposes_manual_pause(monkeypatch: pytest.MonkeyPatch, db) -> None:
    task_id = uuid4()
    task = _task(
        id=task_id,
        status=TaskStatus.PLAN,
        paused=True,
        data={"pause_reasons": ["user"]},
    )
    monkeypatch.setattr(
        task_mcp,
        "_get_task_light",
        AsyncMock(return_value={
            "id": task_id,
            "label": "Report",
            "agent_id": 7,
            "requester_agent_id": None,
            "ai": True,
            "status": TaskStatus.PLAN,
            "paused": True,
            "objectives": "Write a report",
            "objectives_chars": 18,
            "feedback": None,
            "feedback_chars": 0,
        }),
    )
    monkeypatch.setattr(task_mcp, "_get_agents_light", AsyncMock(return_value={}))
    monkeypatch.setattr(task_mcp, "_resolve_task", AsyncMock(return_value=task))
    from app.task import task_service

    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.agent.planner_service.get_progress",
        AsyncMock(return_value={"current": "Research", "percent": 40}),
    )

    await _persist_inspected_task(db, task)
    result = await task_mcp.get_task(task_id)

    assert result["paused"] is True
    assert result["resource_uri"] == f"galaris://task/{task_id}"
    assert result["status"] == "PLAN"
    assert result["operational_state"] == "PAUSED"
    assert result["progress"]["current"] == "Research"
    assert result["latest_attempt"] is None
    assert result["latest_llm_call"] is None
    assert result["execution_context"] == {"effort": "standard"}


@pytest.mark.asyncio
async def test_get_task_exposes_structured_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
    db,
) -> None:
    task_id = uuid4()
    task = _task(
        id=task_id,
        status=TaskStatus.ERROR,
        execution_result={
            "prompt": "Create and deliver a file",
            "result": "A long aggregate whose tail is not part of compact feedback",
            "success": False,
            "metadata": {
                "failure_code": "UNMET_DELIVERY_CONTRACT",
                "failure_reason": "No durable delivery receipt was recorded.",
            },
        },
    )
    monkeypatch.setattr(
        task_mcp,
        "_get_task_light",
        AsyncMock(return_value={
            "id": task_id,
            "label": "Report",
            "agent_id": 7,
            "requester_agent_id": None,
            "ai": True,
            "status": TaskStatus.ERROR,
            "paused": False,
            "objectives": "Create and deliver a file",
            "objectives_chars": 25,
            "feedback": "Aggregate",
            "feedback_chars": 9,
        }),
    )
    monkeypatch.setattr(task_mcp, "_get_agents_light", AsyncMock(return_value={}))
    monkeypatch.setattr(task_mcp, "_resolve_task", AsyncMock(return_value=task))
    diagnostics_db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, None]))
    monkeypatch.setattr(task_mcp, "get_db", lambda: diagnostics_db)
    from app.task import task_service

    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.agent.planner_service.get_progress",
        AsyncMock(return_value=None),
    )

    await _persist_inspected_task(db, task)
    result = await task_mcp.get_task(task_id)

    assert result["failure_code"] == "UNMET_DELIVERY_CONTRACT"
    assert result["failure_reason"] == "No durable delivery receipt was recorded."
    assert result["failure_source"] == "execution_metadata"
    assert result["execution_context"]["success"] is False


@pytest.mark.asyncio
async def test_get_task_exposes_actionable_unstructured_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
    db,
) -> None:
    task_id = uuid4()
    attempt_id = uuid4()
    llm_call_id = uuid4()
    run_id = uuid4()
    started_at = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 8, 17, 9, 2, tzinfo=timezone.utc)
    task = _task(
        id=task_id,
        status=TaskStatus.ERROR,
        effort="high",
        attempt_count=3,
        last_error="The scheduler stored the aggregate result as its last error.",
        execution_result={
            "prompt": "Prepare editorial proposals",
            "result": "A useful partial proposal.",
            "success": False,
            "tools_used": ["file_read", "file_read"],
            "messages": [
                {
                    "type": "text",
                    "content": "Provider stream closed before the terminal event.",
                    "success": False,
                }
            ],
            "metadata": {
                "run_id": str(run_id),
                "runtime_status": "failed",
                "driver_code": "internal",
                "model_code": "editorial-model",
                "private_debug_payload": "must not be exposed",
            },
        },
    )
    latest_attempt = SimpleNamespace(
        id=attempt_id,
        attempt_number=3,
        phase="DISPATCH",
        status="ERROR",
        retryable=False,
        error="Attempt ended with an unsuccessful execution result.",
        started_at=started_at,
        finished_at=finished_at,
    )
    latest_llm_call = SimpleNamespace(
        id=llm_call_id,
        status="failed",
        provider_name="openai",
        effective_model="gpt-test",
        requested_model="gpt-fallback",
        finish_reason="length",
        error="Provider response was incomplete.",
        started_at=started_at,
        completed_at=finished_at,
        duration=120.0,
    )
    diagnostics_db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[latest_attempt, latest_llm_call])
    )
    monkeypatch.setattr(task_mcp, "get_db", lambda: diagnostics_db)
    monkeypatch.setattr(
        task_mcp,
        "_get_task_light",
        AsyncMock(return_value={
            "id": task_id,
            "label": "Editorial proposal",
            "agent_id": 7,
            "requester_agent_id": None,
            "ai": False,
            "status": TaskStatus.ERROR,
            "paused": False,
            "objectives": "Prepare editorial proposals",
            "objectives_chars": 27,
            "feedback": "A useful partial proposal.",
            "feedback_chars": 26,
        }),
    )
    monkeypatch.setattr(task_mcp, "_get_agents_light", AsyncMock(return_value={}))
    monkeypatch.setattr(task_mcp, "_resolve_task", AsyncMock(return_value=task))
    from app.task import task_service

    monkeypatch.setattr(task_service, "get_children", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.agent.planner_service.get_progress",
        AsyncMock(return_value=None),
    )

    await _persist_inspected_task(db, task)
    result = await task_mcp.get_task(task_id)

    assert result["failure_code"] is None
    assert result["failure_reason"] == "Provider stream closed before the terminal event."
    assert result["failure_source"] == "execution_message"
    assert result["last_error"] == (
        "The scheduler stored the aggregate result as its last error."
    )
    assert result["attempt_count"] == 3
    assert result["latest_attempt"] == {
        "id": str(attempt_id),
        "attempt_number": 3,
        "phase": "DISPATCH",
        "status": "ERROR",
        "retryable": False,
        "error": "Attempt ended with an unsuccessful execution result.",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    assert result["latest_llm_call"]["id"] == str(llm_call_id)
    assert result["latest_llm_call"]["status"] == "failed"
    assert result["latest_llm_call"]["finish_reason"] == "length"
    assert result["latest_llm_call"]["error"] == "Provider response was incomplete."
    assert result["execution_context"] == {
        "run_id": str(run_id),
        "runtime_status": "failed",
        "driver_code": "internal",
        "model_code": "editorial-model",
        "effort": "high",
        "success": False,
        "tools_used": ["file_read"],
    }


def test_terminal_diagnostics_distinguish_deadline_from_earlier_tool_failure() -> None:
    assert task_mcp._actionable_attempt_failure(  # pyright: ignore[reportPrivateUsage]
        "TimeoutError: Task action exceeded its configured deadline of 1800 seconds."
    ) == "TimeoutError: Task action exceeded its configured deadline of 1800 seconds."
    assert task_mcp._actionable_attempt_failure(  # pyright: ignore[reportPrivateUsage]
        "The action returned a failed result."
    ) is None


@pytest.mark.asyncio
async def test_terminal_diagnostics_never_hide_the_only_recorded_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(
        status=TaskStatus.ERROR,
        last_error=None,
        attempt_count=1,
        execution_result={
            "prompt": "Do the work",
            "result": "The runtime returned only this terminal failure.",
            "success": False,
        },
    )
    diagnostics_db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, None]))
    monkeypatch.setattr(task_mcp, "get_db", lambda: diagnostics_db)

    diagnostics = await task_mcp._terminal_error_diagnostics(  # pyright: ignore[reportPrivateUsage]
        task,
        task.get_execution_result(),
    )

    assert diagnostics["failure_reason"] == (
        "The runtime returned only this terminal failure."
    )
    assert diagnostics["failure_source"] == "execution_result"
