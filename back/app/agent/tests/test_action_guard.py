"""Execution-error retries and idempotent delivery recovery.

The former action/artifact judgment tests were retired with the requires_action
contract. Successful responses are no longer rejected for missing tool activity.
Durable delivery receipts and actual transport failures retain their own tests.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import executor_service
from app.task.models import Task


def _task(*, data: dict[str, object] | None = None) -> Task:
    return Task(id=uuid4(), label="Recovery", data=data)


@pytest.mark.asyncio
async def test_retry_prompt_carries_previous_failure() -> None:
    task = _task(data={"language": "fr"})
    task.consecutive_failures = 1
    task.last_error = "RuntimeError: provider connection failed."

    prompt = await executor_service.build_task_prompt(task)

    assert "# Previous Attempt Failure" in prompt
    assert "provider connection failed" in prompt


@pytest.mark.asyncio
async def test_first_attempt_prompt_has_no_failure_section() -> None:
    task = _task(data={"language": "fr"})

    prompt = await executor_service.build_task_prompt(task)

    assert "# Previous Attempt Failure" not in prompt


@pytest.mark.asyncio
async def test_delivery_recovery_bypasses_model_and_calls_exact_tool(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.models import Agent, Title
    title = Title(label="Delivery", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(title_id=title.id, first_name="Delivery", last_name="Test", code=f"delivery-{uuid4().hex[:8]}")
    parent = Task(id=uuid4(), label="Delivery parent")
    db.add_all([agent, parent])
    await db.flush()
    execute_tool = AsyncMock(return_value="File sent: final.html")
    monkeypatch.setattr("app.tools.execute_native_mcp_tool", execute_tool)
    task = Task(
        id=uuid4(),
        parent_id=parent.id,
        agent_id=agent.id,
        label="Retry delivery",
        data={
            "plan_tools": ["messenger_room_send_file"],
            "delivery_recovery": {
                "status": "running",
                "tool": "messenger_room_send_file",
                "filename": "final.html",
                "destination": "room-1",
                "runtime": "internal",
            },
        },
    )

    db.add(task)
    await db.commit()
    result = await executor_service._run_delivery_recovery(task)  # pyright: ignore[reportPrivateUsage]

    assert result is not None
    assert result.success is True
    assert result.tools_used == ["messenger_room_send_file"]
    execute_tool.assert_awaited_once_with(
        agent.id,
        runtime="internal",
        task_id=task.id,
        tool_name="messenger_room_send_file",
        arguments={
            "room_id": "room-1",
            "filename": "final.html",
            "message": "",
        },
    )
    await db.refresh(task)
    repeated = await executor_service._run_delivery_recovery(task)
    assert repeated.success is True
    assert repeated.result == result.result
    execute_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_recovery_rejects_broadened_tool_scope() -> None:
    task = Task(
        id=uuid4(),
        parent_id=uuid4(),
        agent_id=7,
        label="Unsafe retry",
        data={
            "plan_tools": ["messenger_room_send_file", "file_write"],
            "delivery_recovery": {
                "status": "running",
                "tool": "messenger_room_send_file",
                "filename": "final.html",
                "destination": "room-1",
            },
        },
    )

    result = await executor_service._run_delivery_recovery(task)  # pyright: ignore[reportPrivateUsage]

    assert result is not None
    assert result.success is False
    assert result.metadata["delivery_recovery"] == "invalid"
