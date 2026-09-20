from uuid import uuid4

from app.agent.contracts import AIMessage, AIResult, AgentUsage, normalize_tool_name
from app.task.models import TaskStatus
from app.task.schemas import Task


def test_ai_result_keeps_cost_but_drops_empty_trace_message() -> None:
    result = AIResult(prompt="prompt")

    result.add_message(AIMessage(type="text", content="", cost=0.42, execution_time=1.5))

    assert result.cost == 0.42
    assert result.execution_time == 1.5
    assert result.messages == []


def test_cumulative_message_snapshots_replace_without_double_counting() -> None:
    result = AIResult(prompt="prompt")
    first = AIMessage(
        type="text", content="Bon", stream_id="answer", stream_mode="snapshot",
        cost=0.1, execution_time=1, usage=AgentUsage(output_tokens=1),
    )
    result.add_message(first)
    complete = first.model_copy(update={
        "content": "Bonjour", "cost": 0.2, "execution_time": 2,
        "usage": AgentUsage(output_tokens=2),
    })
    result.add_message(complete)
    result.add_message(complete)
    assert len(result.messages) == 1
    assert result.messages[0].content == result.result == "Bonjour"
    assert result.cost == 0.2
    assert result.execution_time == 2
    assert result.usage.output_tokens == 2

    result.add_message(AIMessage(type="text", content=" ", stream_id="answer"))
    result.add_message(AIMessage(type="text", content="!", stream_id="answer"))
    assert result.messages[0].content == result.result == "Bonjour !"


def test_ai_result_keeps_tool_message_with_arguments_only() -> None:
    result = AIResult(prompt="prompt")

    result.add_message(
        AIMessage(
            type="tool",
            tool_name="lookup",
            content="",
            tool_arguments={"query": "x"},
        )
    )

    assert len(result.messages) == 1
    assert result.messages[0].tool_name == "lookup"


def test_normalize_tool_name_removes_mcp_namespace_and_keeps_tool_name() -> None:
    assert (
        normalize_tool_name("mcp__galaris__messenger_room_send_message")
        == "messenger_room_send_message"
    )
    assert (
        normalize_tool_name("messenger_room_send_message")
        == "messenger_room_send_message"
    )
    assert normalize_tool_name("galaris_task_get") == "task_get"
    assert normalize_tool_name("mcp__galaris__galaris_task_get") == "task_get"
    assert normalize_tool_name("messenger_reply") == "messenger_reply"

    result = AIResult(prompt="prompt")
    result.add_message(
        AIMessage(
            type="tool",
            tool_name="mcp__galaris__messenger_room_send_message",
            content="Message sent.",
        )
    )

    assert result.tools_used == ["messenger_room_send_message"]
    assert result.messages[0].tool_name == "messenger_room_send_message"


def test_task_schema_derives_await_coordination_fields() -> None:
    task_id = uuid4()
    resolved_by = uuid4()

    task = Task(
        id=task_id,
        label="Request to Orion",
        status=TaskStatus.SUCCESS,
        paused=False,
        ai=False,
        cost=0.0,
        data={
            "awaiting_reply": {"peer_user_id": "orion", "room_id": "room-1"},
            "resolved_by_task_id": str(resolved_by),
        },
    )

    assert task.coordination_type == "await_reply"
    assert task.is_coordination is True
    assert task.execution_expected is False
    assert task.resolved_by_task_id == resolved_by
