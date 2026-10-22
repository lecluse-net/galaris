from uuid import uuid4
import json

import pytest
from pydantic import ValidationError

from app.agent import AIMessage, AgentLiveEvent, ExecutionResult
from app.task import run_events
from app.task.trace_projection import project_tool_payload


@pytest.mark.parametrize("value", ['é"\\' * 10_000, {"nested": ["payload" * 100] * 100}])
def test_tool_detail_preview_is_bounded_redacted_and_does_not_mutate_the_source(value):
    original = {"query": "Synthetic query", "password": "synthetic-secret", "output": value}
    preview = project_tool_payload(original)
    encoded = json.dumps(preview, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= 4_000
    assert "synthetic-secret" not in encoded.decode()
    assert preview["truncated"] is True
    assert original["password"] == "synthetic-secret"
    assert original["output"] == value


@pytest.mark.asyncio
async def test_live_run_projection_is_room_scoped_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def emit(*args: object, **kwargs: object) -> None:
        emitted.append((args, kwargs))

    monkeypatch.setattr(run_events.websocket, "emit", emit)
    task_id = uuid4()
    await run_events.publish_task_run(
        AgentLiveEvent(
            task_id=task_id,
            run_id=uuid4(),
            sequence=2,
            kind="message",
            message=AIMessage(
                type="tool",
                content="x" * 10_000,
                tool_name="secret_tool",
                stream_id="codex:reasoning:r1:0",
                tool_arguments={"query": "synthetic query", "secret": "must-not-leak"},
                tool_result={"count": 2, "nested": {"token": "must-not-leak"}},
            ),
        )
    )

    args, kwargs = emitted[0]
    assert args[:2] == ("agent_run", "event")
    assert str(kwargs["room"]) == f"TaskRunRoom:{task_id}"
    data = args[2]
    assert isinstance(data, dict)
    message = data["message"]
    assert isinstance(message, dict)
    assert len(message["content"]) == 8_000
    assert message["stream_id"] == "codex:reasoning:r1:0"
    assert message["tool_arguments"] == {"query": "synthetic query", "secret": "[REDACTED]"}
    assert message["tool_result"] == {"count": 2, "nested": {"token": "[REDACTED]"}}


@pytest.mark.asyncio
async def test_terminal_projection_keeps_authoritative_bounded_tool_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[object] = []

    async def emit(*args: object, **kwargs: object) -> None:
        emitted.append(args[2])

    monkeypatch.setattr(run_events.websocket, "emit", emit)
    result = ExecutionResult(
        prompt="Test",
        system_prompt="Private system instructions",
        result="Terminé",
        messages=[
            AIMessage(
                type="tool", tool_name="image_generate", content="x" * 10_000,
                tool_call_external_id="call-1",
                tool_arguments={"prompt": "Synthetic image", "secret": "must-not-leak"},
                tool_result={"uri": "synthetic://image", "secret": "must-not-leak"},
            ),
            # Legacy/external runtimes may omit the invocation identity.
            AIMessage(type="tool", tool_name="file_info", content="Done"),
        ],
    )
    await run_events.publish_task_run(AgentLiveEvent(
        task_id=uuid4(), run_id=uuid4(), sequence=3, kind="result", result=result,
    ))

    data = emitted[0]
    assert isinstance(data, dict)
    assert data["result"]["prompt"] == ""
    assert data["result"]["system_prompt"] == ""
    messages = data["result"]["messages"]
    assert len(messages) == 2
    assert messages[0]["tool_call_external_id"] == "call-1"
    assert len(messages[0]["content"]) == 8_000
    assert messages[1]["tool_name"] == "file_info"
    assert messages[0]["tool_arguments"] == {"prompt": "Synthetic image", "secret": "[REDACTED]"}
    assert messages[0]["tool_result"] == {"uri": "synthetic://image", "secret": "[REDACTED]"}
    assert len(result.messages[0].content) == 10_000


def test_task_live_contract_accepts_only_ai_messages_and_terminal_results() -> None:
    task_id = uuid4()
    run_id = uuid4()

    with pytest.raises(ValidationError, match="must contain an AIMessage"):
        AgentLiveEvent(
            task_id=task_id,
            run_id=run_id,
            sequence=1,
            kind="message",
        )
    with pytest.raises(ValidationError, match="must contain an ExecutionResult"):
        AgentLiveEvent(
            task_id=task_id,
            run_id=run_id,
            sequence=2,
            kind="result",
        )

    terminal = AgentLiveEvent(
        task_id=task_id,
        run_id=run_id,
        sequence=2,
        kind="result",
        result=ExecutionResult(prompt="Test", result="Terminé"),
    )
    assert terminal.result is not None
    assert terminal.result.result == "Terminé"
