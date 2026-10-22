from io import BytesIO
import inspect
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
import httpx

from app.llm.trace import agent_run_id_from_messages
from bridge.deepseek_harness import runtime_adapter


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("allowed", [False, True, None])
def test_human_wait_keeps_http_alive_and_dispatches_once(tmp_path, monkeypatch, native, allowed):
    """A slow human decision must outlive the client's HTTP idle deadline."""
    import json
    import time
    from app.harnesses import RuntimeActor

    monkeypatch.setattr(runtime_adapter, "_CONTROL_HEARTBEAT_SECONDS", 0.01, raising=False)
    monkeypatch.setenv("GALARIS_MCP_TOKEN", "synthetic-token")
    server = runtime_adapter.HarnessHTTPServer(("127.0.0.1", 0), _config(tmp_path))
    actor = RuntimeActor("a" * 64, tmp_path / "actor.json", "synthetic")
    pending, decision = threading.Event(), threading.Event()
    calls, effects = [], []

    def authorize(*_args, **_kwargs):
        calls.append("call")
        pending.set()
        assert decision.wait(3)
        if allowed:
            effects.append("effect")
        return allowed

    def mcp(_body):
        result = authorize()
        return 200, json.dumps({"jsonrpc": "2.0", "id": 7,
            "result": {"content": [{"type": "text", "text": "allowed" if result else "denied"}],
                       "isError": not result}}).encode()

    actor.approvals = SimpleNamespace(mcp=mcp, authorize=authorize, run_context="synthetic-context",
                                      cancelled=threading.Event())
    server.runs.actors[actor.identifier] = actor
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = f"/local/{actor.identifier}" if native else f"/mcp/{actor.identifier}"
        body = {"callback": "one", "name": "write", "arguments": {}} if native else {
            "jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "write"}}
        with httpx.Client(timeout=0.1, trust_env=False) as client:
            with client.stream("POST", f"http://127.0.0.1:{server.server_port}{path}", json=body,
                               headers={"Authorization": "Bearer synthetic-token", "X-Galaris-Run-Context": "synthetic-context"}) as response:
                assert response.status_code == 200
                assert pending.wait(1)
                chunks = response.iter_bytes()
                if allowed is None:
                    next(chunks)
                    response.close()
                    assert actor.approvals.cancelled.wait(1)
                    assert calls == ["call"] and effects == []
                    return
                received = bytearray()
                started = time.monotonic()
                while time.monotonic() - started < 0.2:
                    received.extend(next(chunks))
                    assert effects == []
                decision.set()
                for chunk in chunks:
                    received.extend(chunk)
                if native:
                    assert json.loads(received)["allowed"] is allowed
                else:
                    payloads = [json.loads(line[5:]) for line in received.decode().splitlines() if line.startswith("data:")]
                    assert len(payloads) == 1 and payloads[0]["id"] == 7
                    assert payloads[0]["result"]["isError"] is not allowed
        assert calls == ["call"]
        assert effects == (["effect"] if allowed else [])
    finally:
        decision.set()
        server.shutdown()
        server.server_close()
        thread.join()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_runtime_identity_fails_before_sdk_with_a_safe_diagnostic(tmp_path, monkeypatch, status):
    import asyncio
    import hashlib
    from urllib.error import HTTPError
    from unittest.mock import Mock

    from app.agent import AgentRunEnvelopeV1, AgentRunIdentityV1, ResolvedExecutionTarget
    from app.harnesses import OpenAIHarnessClient

    def reject(_self):
        raise HTTPError("https://example.test/private?credential=synthetic-secret", status,
                        "synthetic-secret-response", None, None)

    monkeypatch.setattr(runtime_adapter.ActionApprovals, "validate", reject)
    monkeypatch.setenv("GALARIS_MCP_URL", "https://example.test/api/mcp/synthetic")
    monkeypatch.setenv("GALARIS_MCP_TOKEN", "synthetic-secret")
    sdk = Mock(side_effect=AssertionError("SDK must not start after a preflight rejection"))
    monkeypatch.setattr(runtime_adapter, "run_completion", sdk)
    server = runtime_adapter.HarnessHTTPServer(("127.0.0.1", 0), _config(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = "synthetic-run-context"
    envelope = AgentRunEnvelopeV1(
        identity=AgentRunIdentityV1(run_id=uuid4()),
        target=ResolvedExecutionTarget(provider_code="deepseek_harness", target_ref=f"harness:{uuid4()}",
                                       metadata={"model": "synthetic-model"}),
        agent_id=7, agent_code="synthetic", effort="standard", objective="Synthetic work",
        model_id=1, model_code="synthetic-model", model_name="Synthetic",
    )
    client = OpenAIHarnessClient(base_url=f"http://127.0.0.1:{server.server_port}/v1", token="secret", run_context=context)
    try:
        result = await asyncio.wait_for(client.control_run(
            envelope, runtime_run_id=hashlib.sha256(context.encode()).hexdigest(), start=True,
        ), timeout=5)
        assert result.success is False
        assert result.metadata["runtime_status"] == "failed"
        assert result.failure is not None
        assert result.failure.code == "configuration" and result.failure.effects == "none"
        assert result.failure.retry == "never"
        assert str(status) in result.result and "No model call or action was started" in result.result
        assert "synthetic-secret" not in result.model_dump_json()
        sdk.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


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


@pytest.mark.parametrize("managed", [False, True])
def test_completion_uses_one_isolated_session_and_final_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    managed: bool,
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
            assert options["env"]["GALARIS_MODEL"] == options["model"]
            assert options["request_timeout_seconds"] == (None if managed else 30.0)

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
        actor_id="synthetic-actor" if managed else "",
    )

    assert completion.content == "Done"
    assert completion.finish_reason == "stop"
    assert completion.id.startswith("chatcmpl-dsh-")
    assert len(calls) == 1
    assert calls[0][1] == completion.id
    assert (tmp_path / "sessions" / completion.id).is_dir()


@pytest.mark.parametrize("unavailable_starts", [1, 3])
def test_mcp_startup_is_retried_before_any_model_execution(tmp_path, monkeypatch, unavailable_starts):
    starts, runs, closes = [], [], []

    class SDKBoundary:
        def __init__(self, **_options):
            starts.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closes.append(self)

        def run(self, _prompt, **_options):
            runs.append(self)
            return SimpleNamespace(final_response="Done", finish_reason="completed")

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: SDKBoundary)
    def execute():
        return runtime_adapter.run_completion(
            {"model": "synthetic", "messages": [{"role": "user", "content": "Do the work"}]},
            _config(tmp_path), mcp_ready=lambda: len(starts) > unavailable_starts)

    if unavailable_starts == 3:
        with pytest.raises(RuntimeError, match="MCP catalogue"):
            execute()
        assert not runs
    else:
        assert execute().content == "Done"
        assert runs == [starts[-1]]
    assert len(starts) == min(unavailable_starts + 1, 3)
    assert closes == starts


@pytest.mark.parametrize("failure", [
    {"status": 502}, {"status": 503}, {"status": 504},
    {"code": "SERVER"}, {"code": "RATE_LIMIT"}, {"code": "TIMEOUT"}, {"code": "TRANSPORT"},
])
def test_transient_provider_error_continues_same_session_without_replaying_tool(tmp_path, monkeypatch, failure):
    calls = []
    effects = []

    class RecoveringHarness:
        def __init__(self, **_options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def close(self):
            pass

        def run(self, prompt, *, session_id):
            calls.append((prompt, session_id))
            if len(calls) == 1:
                effects.append("acknowledged write")
                return SimpleNamespace(final_response="Partial response", finish_reason="error", events=[
                    {"type": "tool/call", "data": {"callId": "write-1"}},
                    {"type": "tool/result", "data": {"message": {
                        "source": {"kind": "tool", "callId": "write-1"},
                        "content": [{"type": "tool-result", "toolCallId": "write-1", "isError": False}],
                    }}},
                    {"type": "turn/end", "data": {"reason": {"kind": "error", "error": failure}}},
                ])
            return SimpleNamespace(final_response="Finished", finish_reason="completed", events=[])

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: RecoveringHarness)
    completion = runtime_adapter.run_completion({
        "model": "executor-model", "messages": [{"role": "user", "content": "Do the work"}],
        "galaris_network_retry": {"max_attempts": 3, "base_seconds": 0, "max_seconds": 0},
    }, _config(tmp_path))

    assert completion.content == "Finished"
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]
    assert calls[0][0] != calls[1][0]
    assert effects == ["acknowledged write"]


@pytest.mark.parametrize("failure,unfinished,attempts,blocked", [
    ({"status": 400}, False, 1, False), ({"status": 502}, True, 1, False),
    ({"status": 502}, False, 3, False), ({"status": 502}, False, 1, True),
    ({"code": "AUTH"}, False, 1, False), ({"code": "SERVER"}, True, 1, False),
    ({"code": "SERVER"}, False, 1, True), ({"status": 401, "code": "SERVER"}, False, 1, False),
])
def test_provider_error_does_not_publish_partial_success_or_replay_unknown_tool(tmp_path, monkeypatch, failure, unfinished, attempts, blocked):
    calls = []

    class FailedHarness:
        def __init__(self, **_options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def close(self):
            pass

        def run(self, prompt, *, session_id):
            calls.append(session_id)
            return SimpleNamespace(final_response="Partial response", finish_reason="error", events=[
                *([{"type": "tool/call", "data": {"callId": "unconfirmed-write"}}] if unfinished else []),
                {"type": "turn/end", "data": {"reason": {"kind": "error", "error": failure}}},
            ])

    monkeypatch.setattr(runtime_adapter, "_harness_factory", lambda: FailedHarness)
    with pytest.raises(RuntimeError):
        runtime_adapter.run_completion({
            "model": "executor-model", "messages": [{"role": "user", "content": "Do the work"}],
            "galaris_network_retry": {"max_attempts": 3, "base_seconds": 0, "max_seconds": 0},
        }, _config(tmp_path), can_continue=lambda: not blocked)
    assert len(calls) == attempts
    assert len(set(calls)) == 1


def test_cancellation_interrupts_network_retry_wait():
    active = runtime_adapter.ActiveRun()
    waiting = threading.Event()
    outcome = []

    def wait():
        waiting.set()
        outcome.append(active.wait_for_retry(60))

    worker = threading.Thread(target=wait)
    worker.start()
    assert waiting.wait(1)
    active.cancel()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert outcome == [False]


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


@pytest.mark.parametrize("nested_result", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_stream_adapter_emits_text_reasoning_and_completed_tools(
    nested_result: bool, failed: bool,
) -> None:
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
    content = [{"type": "text", "text": "Read denied" if failed else "Loaded"}]
    # The pinned SDK's ToolResultMessage has a source and a tool-result block.
    # Keep the former flat representation covered for older runtime events.
    message = {
        "role": "user",
        "source": {"kind": "tool", "callId": "call-1"},
        "content": [{"type": "tool-result", "toolCallId": "call-1",
                     "content": content, "isError": failed}],
    } if nested_result else {
        "toolCallId": "call-1", "content": content, "isError": failed,
    }
    tool = adapter.consume(notification({
        "type": "tool/result",
        "data": {"message": message},
    }))

    assert text[0].kind == "text"
    assert text[0].payload["content"] == "Working"
    assert thinking[0].payload["tool_name"] == "thinking"
    assert thinking[0].payload["content"] == "Inspect files"
    assert tool[0].payload["tool_name"] == "file_read"
    assert tool[0].payload["tool_arguments"] == {"path": "README.md"}
    assert tool[0].payload["content"] == ("Read denied" if failed else "Loaded")
    assert tool[0].payload["tool_result"] == message
    assert tool[0].payload["success"] is not failed
    assert tool[0].payload["tool_call_external_id"] == "call-1"


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
