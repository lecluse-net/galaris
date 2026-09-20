from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import executor_service
from app.agent.contracts import (
    AIMessage,
    AgentUsage,
    ExecutionResult,
    WorkingResource,
    WorkingSet,
)
from app.task.models import Task, TaskStatus


def test_last_sent_response_prefers_the_terminal_result_over_progress() -> None:
    result = ExecutionResult(
        prompt="Implement the fix.",
        result="The fix is complete and pushed.",
        messages=[
            AIMessage(
                type="tool",
                tool_name="messenger_room_send_message",
                tool_arguments={"room_id": "room-1", "message": "I am starting."},
                content="Message sent.",
            )
        ],
    )

    assert (
        executor_service._last_sent_response(result)  # pyright: ignore[reportPrivateUsage]
        == "The fix is complete and pushed."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,expected", [("messenger_room_send_file", True), ("console_exec", False)])
async def test_empty_output_is_recovered_only_after_current_task_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    expected: bool,
) -> None:
    task_id = uuid4()
    result = ExecutionResult(
        prompt="Send the audio file.",
        result="UnexpectedModelBehavior: Exceeded maximum output retries (2)",
        success=False,
        messages=[
            AIMessage(
                type="tool",
                tool_name=tool_name,
                content="File sent.",
            ),
            AIMessage(
                type="text",
                content="UnexpectedModelBehavior: Exceeded maximum output retries (2)",
                success=False,
            )
        ],
    )
    monkeypatch.setattr(
        executor_service.task_port,
        "get_working_set",
        AsyncMock(
            return_value=WorkingSet(
                resources=[
                    WorkingResource(
                        resource_type="artifact",
                        role="final_artifact",
                        reference="internal://room/audio.mp3",
                        label="audio.mp3",
                        producer_task_id=task_id,
                        metadata={"delivered": True},
                    ),
                    WorkingResource(
                        resource_type="delivery_receipt",
                        role="delivery_receipt:audio.mp3",
                        reference="messenger_room_send_file:room:audio.mp3",
                        producer_task_id=task_id,
                        metadata={"tool": tool_name},
                    ),
                ]
            )
        ),
    )

    recovered = await executor_service.recover_after_verified_delivery(
        type("Task", (), {"task_id": task_id})(),
        result,
        failure_kind="empty_model_output",
    )

    assert recovered is expected
    assert result.success is expected
    if not expected:
        assert result.result == "UnexpectedModelBehavior: Exceeded maximum output retries (2)"
        assert "recovered_after_verified_delivery" not in result.metadata
        assert result.messages[-1].success is False
        return
    assert result.result == "Delivered artifact verified: audio.mp3."
    assert result.metadata["recovered_after_verified_delivery"] is True
    assert [message.tool_name for message in result.messages] == [
        "messenger_room_send_file"
    ]


@pytest.mark.asyncio
async def test_empty_output_without_delivery_receipt_stays_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    result = ExecutionResult(
        prompt="Send it.",
        result="empty",
        success=False,
        messages=[
            AIMessage(
                type="tool",
                tool_name="messenger_room_send_file",
                content="File sent.",
            )
        ],
    )
    monkeypatch.setattr(
        executor_service.task_port,
        "get_working_set",
        AsyncMock(
            return_value=WorkingSet(
                resources=[
                    WorkingResource(
                        resource_type="artifact",
                        role="final_artifact",
                        reference="internal://room/audio.mp3",
                        producer_task_id=task_id,
                        metadata={"delivered": True},
                    )
                ]
            )
        ),
    )

    recovered = await executor_service.recover_after_verified_delivery(
        type("Task", (), {"task_id": task_id})(),
        result,
        failure_kind="empty_model_output",
    )

    assert recovered is False
    assert result.success is False


@pytest.mark.asyncio
async def test_final_cost_uses_attempt_base_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Task(
        id=uuid4(),
        label="Cost",
        status=TaskStatus.EXEC,
        ai=True,
        cost=2.75,
    )
    result = ExecutionResult(
        prompt="p",
        result="failure",
        success=False,
        cost=1.25,
        usage=AgentUsage(input_tokens=123, requests=2, token_quality="exact"),
        metadata={"runtime_run_id": "run-existing", "runtime_status": "failed"},
    )

    monkeypatch.setattr(
        executor_service.task_port,
        "save",
        AsyncMock(return_value=task),
    )
    from app.agent import planner_service
    from app.task import collab

    monkeypatch.setattr(collab, "suspend_on_pending_children", AsyncMock(return_value=False))
    monkeypatch.setattr(collab, "resolve_from_peer_task", AsyncMock())
    monkeypatch.setattr(collab, "maybe_fan_in", AsyncMock())
    monkeypatch.setattr(planner_service, "resume_parent", AsyncMock())

    await executor_service._update_task_after_execution(  # pyright: ignore[reportPrivateUsage]
        task,
        result,
        base_cost=2.75,
    )

    assert task.cost == pytest.approx(4.0)
    assert task.status == TaskStatus.ERROR
    stored = task.get_execution_result()
    assert stored is not None
    assert stored.metadata["runtime_run_id"] == "run-existing"
    assert stored.usage.input_tokens == 123
    assert stored.usage.requests == 2


@pytest.mark.asyncio
async def test_failed_stream_waits_for_children_instead_of_ending_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        id=uuid4(),
        label="Coordination interrompue",
        status=TaskStatus.EXEC,
        ai=True,
        cost=0.0,
    )
    result = ExecutionResult(
        prompt="Ask colleagues, then summarize.",
        result="Client disconnected during streaming",
        success=False,
        tools_used=["task_run"],
    )

    from app.task import collab

    async def suspend_parent(failed_task: Task) -> bool:
        from app.task import task_service
        from app.task.workflow import TaskEvent, transition

        transition(failed_task, TaskEvent.INTERRUPT_EXECUTION)
        task_service.suspend(failed_task, task_service.PAUSE_CHILD)
        return True

    monkeypatch.setattr(collab, "suspend_on_pending_children", suspend_parent)
    monkeypatch.setattr(
        executor_service.task_port,
        "save",
        AsyncMock(return_value=task),
    )
    fan_in = AsyncMock()
    monkeypatch.setattr(collab, "maybe_fan_in", fan_in)

    updated = await executor_service._update_task_after_execution(  # pyright: ignore[reportPrivateUsage]
        task,
        result,
        base_cost=0.0,
    )

    assert updated.status == TaskStatus.DISPATCH
    assert updated.paused is True
    saved_result = updated.get_execution_result()
    assert saved_result is not None
    assert saved_result.success is False
    fan_in.assert_awaited_once_with(task.id)
