from pathlib import Path


_RUNTIME_SOURCE = (
    Path(__file__).parents[1] / "default-agent" / "server.py"
).read_text(encoding="utf-8")


def test_runtime_keeps_task_effort_separate_from_reasoning_effort() -> None:
    compile(_RUNTIME_SOURCE, "server.py", "exec")
    assert '"X-Galaris-Reasoning-Effort", ""' in _RUNTIME_SOURCE
    assert "X-Galaris-Conversation-Round-Id" not in _RUNTIME_SOURCE
    assert 'mapped_reasoning_effort = {' in _RUNTIME_SOURCE
    assert '"minimal": "low"' in _RUNTIME_SOURCE
    assert '"max": "max"' in _RUNTIME_SOURCE
    assert '"model_reasoning_effort": "high" if effort' not in _RUNTIME_SOURCE


def test_runtime_forwards_public_codex_deltas_before_item_completion() -> None:
    assert "final_delta, thinking_message = trace.record_agent_delta(" in _RUNTIME_SOURCE
    assert "thinking_message = trace.record_reasoning_delta(" in _RUNTIME_SOURCE
    assert _RUNTIME_SOURCE.count("yield semantic_event(thinking_message)") == 2
