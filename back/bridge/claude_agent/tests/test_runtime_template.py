import runpy
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from app.harnesses import runtime_support
from bridge.claude_agent import stream_trace

_RUNTIME_PATH = Path(__file__).parents[1] / "default-agent" / "server.py.txt"
_RUNTIME_SOURCE = _RUNTIME_PATH.read_text(encoding="utf-8")


def test_runtime_publishes_semantic_thinking_and_authoritative_final_text() -> None:
    assert "trace.consume(event)" in _RUNTIME_SOURCE
    assert '"result": final_text' in _RUNTIME_SOURCE
    assert 'yield "tool", thinking' in _RUNTIME_SOURCE


def test_runtime_maps_claude_model_families_to_galaris_text_tiers() -> None:
    assert '"ANTHROPIC_DEFAULT_HAIKU_MODEL": "ultra-low"' in _RUNTIME_SOURCE
    assert '"ANTHROPIC_DEFAULT_SONNET_MODEL": "low"' in _RUNTIME_SOURCE
    assert '"ANTHROPIC_DEFAULT_OPUS_MODEL": "standard"' in _RUNTIME_SOURCE
    assert '"ANTHROPIC_DEFAULT_FABLE_MODEL": "high"' in _RUNTIME_SOURCE


def test_runtime_keeps_task_effort_separate_from_reasoning_effort() -> None:
    assert 'request.headers.get("X-Galaris-Effort"' not in _RUNTIME_SOURCE
    assert '"X-Galaris-Reasoning-Effort", ""' in _RUNTIME_SOURCE
    assert "X-Galaris-Conversation-Round-Id" not in _RUNTIME_SOURCE
    assert '"minimal": "low"' in _RUNTIME_SOURCE
    assert '"max": "max"' in _RUNTIME_SOURCE
    assert '}.get(reasoning_effort),' in _RUNTIME_SOURCE


@pytest.mark.asyncio
async def test_managed_claude_uses_galaris_permissions_and_allows_hundreds_of_calls(monkeypatch, tmp_path):
    sdk = ModuleType("claude_agent_sdk")
    sdk.ClaudeAgentOptions = lambda **options: SimpleNamespace(can_use_tool=None, **options)
    sdk.ClaudeSDKClient = object
    sdk.HookMatcher = SimpleNamespace
    sdk_types = ModuleType("claude_agent_sdk.types")
    for name in ("AssistantMessage", "UserMessage", "ToolUseBlock", "ToolResultBlock", "ResultMessage", "StreamEvent", "SystemMessage"):
        setattr(sdk_types, name, type(name, (SimpleNamespace,), {}))
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", sdk_types)
    monkeypatch.setitem(sys.modules, "runtime_support", runtime_support)
    monkeypatch.setitem(sys.modules, "runtime_web", import_module("app.harnesses.runtime_web"))
    monkeypatch.setitem(sys.modules, "stream_trace", stream_trace)
    monkeypatch.setenv("CLAUDE_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GALARIS_MCP_URL", "http://example.invalid/mcp")
    monkeypatch.setenv("GALARIS_MCP_TOKEN", "synthetic-mcp-token")
    adapter = runpy.run_path(str(_RUNTIME_PATH))
    actor = runtime_support.RuntimeActor("run", tmp_path / "actor.json", "fingerprint")
    approvals = Mock(run_context="synthetic", **{"authorize_once.return_value": ("deny", "")})
    actor.approvals = approvals

    class SDKClient:
        def __init__(self, *, options):
            self.options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            pass

        async def query(self, *, prompt):
            async for _ in prompt:
                pass

        async def receive_response(self):
            assert self.options.permission_mode == "dontAsk"
            assert "Skill" in self.options.disallowed_tools
            assert self.options.skills == []
            assert self.options.setting_sources == []
            assert self.options.can_use_tool is None
            assert "skill_read" in self.options.system_prompt["append"]
            before = self.options.hooks["PreToolUse"][0].hooks[0]
            after = self.options.hooks["PostToolUse"][0].hooks[0]

            async def decide(tool, call_id, arguments):
                event = {"tool_name": tool, "tool_input": arguments, "tool_use_id": call_id}
                outcome = await before(event, call_id, None)
                return outcome["hookSpecificOutput"]["permissionDecision"]

            assert await decide("Skill", "native", {"skill": "synthetic"}) == "deny"
            assert await decide("Read", "read", {"file_path": "record.txt"}) == "allow"
            assert await decide("Read", "outside", {"file_path": "../other.txt"}) == "deny"
            assert await decide("mcp__unconfigured__read", "foreign", {}) == "deny"
            assert await decide("Bash", "shell", {"command": "true"}) == "deny"
            for index in range(300):
                call_id = f"read-skill-{index}"
                assert await decide("mcp__galaris__skill_read", call_id, {"skill_id": index + 1}) == "allow"
                await after({"tool_use_id": call_id, "tool_response": "Synthetic content"}, call_id, None)
            yield adapter["UserMessage"](content=[])

    run_events = adapter["_run_events"]
    monkeypatch.setitem(run_events.__globals__, "ClaudeSDKClient", SDKClient)
    body = adapter["ChatRequest"].model_validate({
        "model": "synthetic", "messages": [{"role": "user", "content": "Review records"}],
    })
    request = SimpleNamespace(headers={"X-Galaris-Tool-Call-Limit": "5000"})
    events = [payload async for kind, payload in run_events(body, request, actor) if kind == "tool"]

    assert [event["tool_call_external_id"] for event in events] == [f"read-skill-{index}" for index in range(300)]
    approvals.validate.assert_called_once_with()
    assert [call.args[:2] for call in approvals.authorize_once.call_args_list] == [("shell", "Bash")]
