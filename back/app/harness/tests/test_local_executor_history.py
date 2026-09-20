from types import SimpleNamespace
from uuid import uuid4

from app.harness.executor import (
    _conversation_history_prompt_block,
    _previous_conversation_messages,
    _scoped_tool_names,
    _task_is_real_time,
)
from app.agent.contracts import BriefingChoice, BriefingResult
from app.agent.contracts import TaskMessageAttachment
from app.task import TaskMessage
from app.task.models import Task, TaskStatus


def _message(
    message_id: str, text: str, sender_id: str, display_name: str = ""
) -> TaskMessage:
    return TaskMessage(
        external_message_id=message_id,
        text=text,
        timestamp=1_700_000_000,
        sender_external_id=sender_id,
        sender_display_name=display_name or sender_id,
    )


def test_local_openai_history_excludes_current_message_from_prompt() -> None:
    task = SimpleNamespace(
        message_platform="openai",
        data={"conversation_id": "conv-1"},
        objective="Respond to this message : What did I ask?",
        messages=[
            _message("openai-0", "Remember alpha", "user-0", "user"),
            _message("openai-1", "I will remember alpha", "galaris-bot", "assistant"),
            _message("openai-2", "What did I ask?", "user-0", "user"),
        ],
    )

    previous = _previous_conversation_messages(task)
    block = _conversation_history_prompt_block(task, "galaris-bot")

    assert [message.text for message in previous] == [
        "Remember alpha",
        "I will remember alpha",
    ]
    assert "Remember alpha" in block
    assert "I will remember alpha" in block
    assert "What did I ask?" not in block
    assert block.startswith("<conversation_history>\n")
    assert "| assistant]" in block
    assert "| user |" not in block
    assert "| assistant |" not in block


def test_local_messenger_history_excludes_current_message_by_id() -> None:
    task = SimpleNamespace(
        message_platform="matrix",
        data={"id": "current"},
        objective="Current text",
        messages=[
            _message("previous", "Earlier text", "alice", "Alice"),
            _message("current", "Current text", "alice", "Alice"),
        ],
    )

    previous = _previous_conversation_messages(task)
    block = _conversation_history_prompt_block(task, "bot")

    assert [message.external_message_id for message in previous] == ["previous"]
    assert "Earlier text" in block
    assert "Current text" not in block


def test_local_history_keeps_file_only_message_with_canonical_uri() -> None:
    room_id = uuid4()
    file_id = uuid4()
    attachment = TaskMessageAttachment(
        id=file_id,
        uri=f"matrix-primary://!room:test/{file_id}",
        name="rapport.pdf",
        mime="application/pdf",
    )
    task = SimpleNamespace(
        message_platform="matrix",
        data={"id": "current"},
        objective="Current text",
        messages=[
            TaskMessage(
                external_message_id="file-only",
                room_id=room_id,
                attachments=[attachment],
            ),
            _message("current", "Current text", "alice", "Alice"),
        ],
    )

    previous = _previous_conversation_messages(task)
    block = _conversation_history_prompt_block(task, "bot")

    assert [message.external_message_id for message in previous] == ["file-only"]
    assert "[file: rapport.pdf]" in block
    assert f"matrix-primary://!room:test/{file_id}" in block


def test_local_history_is_strictly_bounded_for_multi_tool_runs() -> None:
    messages = [
        _message(f"m{index}", f"message-{index} " + "x" * 1200, "alice", "Alice")
        for index in range(35)
    ]
    task = SimpleNamespace(
        message_platform="matrix",
        data={"id": "current"},
        objective="Current text",
        messages=[*messages, _message("current", "Current text", "alice", "Alice")],
    )

    block = _conversation_history_prompt_block(task, "bot")

    assert "5 older message(s) omitted" in block
    assert "message-4" not in block
    assert "message-5" in block
    assert len(block) < 25_000


def test_executor_tool_scope_combines_plan_and_briefing_choices() -> None:
    task = Task(
        label="Scoped",
        status=TaskStatus.BRIEFING,
        data={"plan_tools": ["search_web"]},
    )
    task.set_briefing_result(
        BriefingResult(
            result="Write and deliver.",
            choices=[
                BriefingChoice(kind="tool", identifier="file_write"),
                BriefingChoice(kind="process", identifier="document_generation"),
            ],
        )
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert {
        "search_web",
        "file_write",
        "process_list",
        "process_get",
        "process_start",
        "process_list_runs",
        "process_get_run",
        "process_analyze_run",
    } <= names
    assert "messenger_room_send_message" not in names
    assert {"file_list", "file_info", "file_read"} <= names


def test_intermediate_plan_leaf_cannot_access_delivery_tools() -> None:
    task = Task(
        label="Intermediate",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={
            "plan_tools": ["file_write", "messenger_room_send_file"],
            "delivery_policy": "forbidden",
        },
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert "file_write" in names
    assert "messenger_room_send_file" not in names


def test_final_plan_leaf_gets_only_explicit_delivery_tool() -> None:
    task = Task(
        label="Final delivery",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={
            "plan_tools": ["messenger_room_send_file"],
            "delivery_policy": "required",
        },
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert "messenger_room_send_file" in names
    assert "messenger_room_send_message" not in names


def test_delivery_recovery_exposes_exact_recorded_tool_only() -> None:
    task = Task(
        label="Retry final delivery",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={
            "plan_tools": ["messenger_room_send_file"],
            "delivery_policy": "required",
            "delivery_recovery": {"status": "running"},
        },
    )

    names = _scoped_tool_names(task)

    assert names == {"messenger_room_send_file"}


def test_scoped_document_mutation_keeps_read_companion() -> None:
    task = Task(
        label="Scoped document",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={"plan_tools": ["file_edit"]},
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert {"file_edit", "file_info", "file_read"} <= names


def test_scoped_mail_send_keeps_memory_contact_lookup_companions() -> None:
    task = Task(
        label="Send Mail",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={"plan_tools": ["mail_send"]},
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert {"mail_send", "file_search", "file_read"} <= names


def test_goal_agent_referrer_keeps_task_run_in_a_scoped_plan() -> None:
    task = Task(
        label="Goal leaf",
        objective="Advance one planned step.",
        status=TaskStatus.DISPATCH,
        parent_id=uuid4(),
        data={
            "plan_tools": ["search_web"],
            "goal_referrer_type": "AGENT",
            "goal_referrer_agent_id": 42,
        },
    )

    names = _scoped_tool_names(task)

    assert names is not None
    assert "task_run" in names


def test_only_voice_tasks_enable_real_time_model_settings() -> None:
    assert _task_is_real_time(SimpleNamespace(data={"voice_call": True})) is True
    assert _task_is_real_time(SimpleNamespace(data={"voice_call": False})) is False
    assert _task_is_real_time(SimpleNamespace(data={})) is False
    assert _task_is_real_time(None) is False
