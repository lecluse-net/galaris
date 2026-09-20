from io import BytesIO
import inspect
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.llm.trace import agent_run_id_from_messages
from bridge.deepseek_harness import runtime_adapter


def _config(tmp_path: Path) -> runtime_adapter.AdapterConfig:
    cordis = tmp_path / "cordis.yml"
    cordis.write_text("[]", encoding="utf-8")
    return runtime_adapter.AdapterConfig(
        api_token="secret",
        model="executor-model",
        workspace=tmp_path / "workspace",
        session_root=tmp_path / "sessions",
        cordis=cordis,
        request_timeout_seconds=30.0,
    )


def test_runtime_never_accepts_conversation_round_context() -> None:
    source = inspect.getsource(runtime_adapter)

    assert "galaris_conversation_round_id" not in source
    assert "X-Galaris-Conversation-Round-Id" not in source


def test_prompt_preserves_order_and_marks_system_instructions_as_governing() -> None:
    prompt = runtime_adapter.render_prompt(
        [
            {"role": "system", "content": "Do not publish."},
            {"role": "user", "content": "Prepare the report."},
        ]
    )

    assert "System-role entries are governing instructions" in prompt
    assert prompt.index("Do not publish") < prompt.index("Prepare the report")
    assert "Use Galaris MCP tools" in prompt


def test_prompt_includes_trusted_runtime_correlation() -> None:
    prompt = runtime_adapter.render_prompt(
        [{"role": "user", "content": "Prepare the report."}],
        {"task_id": "task-123", "run_id": "run-456"},
    )

    assert (
        '<galaris_runtime_context>{"task_id":"task-123","run_id":"run-456"}'
        "</galaris_runtime_context>"
    ) in prompt


def test_gateway_can_recover_the_agent_run_from_the_rendered_prompt() -> None:
    run_id = uuid4()
    prompt = runtime_adapter.render_prompt(
        [{"role": "user", "content": "Prepare the report."}],
        {"run_id": str(run_id)},
    )

    assert agent_run_id_from_messages([{"role": "user", "content": prompt}]) == run_id


def test_completion_uses_one_isolated_session_and_final_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeHarness:
        def __init__(self, **options):
            self.options = options
            # The real image test also constructs DeepSeekHarnessConfig: **kwargs
            # mocks alone previously concealed removed SDK configuration fields.
            assert "session_root" not in options and "cordis" not in options
            assert options["profile"] == "sdk"
            assert options["patches"] == (str(tmp_path / "cordis.yml"),)
            assert Path(options["dsh_home"]).parent == tmp_path / "sessions"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, prompt: str, *, session_id: str):
            calls.append((prompt, session_id))
            return SimpleNamespace(final_response="Done", finish_reason="completed")

        def close(self):
            return None

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: FakeHarness)

    completion = runtime_adapter.run_completion(
        {
            "model": "executor-model",
            "messages": [{"role": "user", "content": "Do the work"}],
        },
        _config(tmp_path),
    )

    assert completion.content == "Done"
    assert completion.finish_reason == "stop"
    assert completion.id.startswith("chatcmpl-dsh-")
    assert len(calls) == 1
    assert calls[0][1] == completion.id
    assert (tmp_path / "sessions" / completion.id).is_dir()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, None),
        ("low", "low"),
        ("medium", "high"),
        ("xhigh", "max"),
        ("max", "max"),
    ],
)
def test_completion_maps_only_configured_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: str | None,
    expected: str | None,
) -> None:
    captured: dict[str, object] = {}

    class FakeHarness:
        def __init__(self, **options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, _prompt: str, *, session_id: str):
            return SimpleNamespace(final_response="Done", finish_reason="completed")

        def close(self):
            return None

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: FakeHarness)
    body: dict[str, object] = {
        "model": "executor-model",
        "messages": [{"role": "user", "content": "Do the work"}],
    }
    if configured is not None:
        body["galaris_reasoning_effort"] = configured

    runtime_adapter.run_completion(body, _config(tmp_path))

    env = captured["env"]
    assert isinstance(env, dict)
    assert env.get("DSH_REASONING_EFFORT") == expected


def test_completion_rejects_an_empty_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        runtime_adapter.run_completion(
            {
                "model": "",
                "messages": [{"role": "user", "content": "Do the work"}],
            },
            _config(tmp_path),
        )


def test_completion_subscribes_to_official_sdk_notifications(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    received: list[object] = []
    notification = SimpleNamespace(method="session.status", payload={"status": "busy"})

    class FakeHarness:
        def __init__(self, **_options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, _prompt: str, *, session_id: str, on_notification=None):
            assert session_id.startswith("chatcmpl-dsh-")
            assert on_notification is not None
            on_notification(notification)
            return SimpleNamespace(final_response="Done", finish_reason="completed")

        def close(self):
            return None

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: FakeHarness)

    runtime_adapter.run_completion(
        {
            "model": "executor-model",
            "messages": [{"role": "user", "content": "Do the work"}],
        },
        _config(tmp_path),
        on_notification=received.append,
    )

    assert received == [notification]


def test_stream_adapter_emits_text_reasoning_and_completed_tools() -> None:
    adapter = runtime_adapter.DeepSeekStreamAdapter()

    def notification(event: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            method="session.event",
            payload={"sessionId": "run-1", "event": event},
        )

    text = adapter.consume(notification({
        "type": "assistant/chunk",
        "data": {"chunk": {"type": "text-delta", "index": 0, "text": "Working"}},
    }))
    adapter.consume(notification({
        "type": "assistant/chunk",
        "data": {
            "chunk": {"type": "reasoning-delta", "index": 1, "text": "Inspect "}
        },
    }))
    thinking = adapter.consume(notification({
        "type": "assistant/chunk",
        "data": {
            "chunk": {
                "type": "block-end",
                "index": 1,
                "block": {"type": "reasoning", "text": "Inspect files"},
            }
        },
    }))
    adapter.consume(notification({
        "type": "tool/call",
        "data": {
            "callId": "call-1",
            "name": "file_read",
            "arguments": '{"path":"README.md"}',
        },
    }))
    tool = adapter.consume(notification({
        "type": "tool/result",
        "data": {
            "message": {
                "toolCallId": "call-1",
                "content": [{"type": "text", "text": "Loaded"}],
            }
        },
    }))

    assert text[0].kind == "text"
    assert text[0].payload["content"] == "Working"
    assert thinking[0].payload["tool_name"] == "thinking"
    assert thinking[0].payload["content"] == "Inspect files"
    assert tool[0].payload["tool_name"] == "file_read"
    assert tool[0].payload["tool_arguments"] == {"path": "README.md"}
    assert tool[0].payload["content"] == "Loaded"


def test_http_stream_forwards_sdk_delta_before_the_run_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    delta_written = threading.Event()

    class LiveBuffer(BytesIO):
        def write(self, data: bytes) -> int:
            written = super().write(data)
            if b'"content":"Working"' in data:
                delta_written.set()
            return written

    def fake_completion(
        _body: object,
        _config: object,
        *,
        active: object,
        on_notification,
    ) -> runtime_adapter.Completion:
        del active
        on_notification(SimpleNamespace(
            method="session.event",
            payload={
                "event": {
                    "type": "assistant/chunk",
                    "data": {
                        "chunk": {
                            "type": "text-delta",
                            "index": 0,
                            "text": "Working",
                        }
                    },
                }
            },
        ))
        assert delta_written.wait(timeout=2.0)
        return runtime_adapter.Completion(
            id="run-1",
            model="executor-model",
            content="Working",
            finish_reason="stop",
        )

    monkeypatch.setattr(runtime_adapter, "run_completion", fake_completion)
    output = LiveBuffer()
    handler = SimpleNamespace(
        config=_config(tmp_path),
        wfile=output,
        send_response=lambda _status: None,
        send_header=lambda _name, _value: None,
        end_headers=lambda: None,
    )

    runtime_adapter.HarnessRequestHandler._stream_completion(
        cast(Any, handler),
        {"model": "executor-model"},
    )

    stream = output.getvalue().decode()
    assert stream.index('"content":"Working"') < stream.index(
        "event: galaris.agent-result/v1"
    )
    assert '"result":"Working"' in stream
