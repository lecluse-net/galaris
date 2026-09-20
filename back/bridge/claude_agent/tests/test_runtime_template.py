import ast
from pathlib import Path


_RUNTIME_SOURCE = (
    Path(__file__).parents[1] / "default-agent" / "server.py.txt"
).read_text(encoding="utf-8")


def test_runtime_uses_streaming_sdk_input_with_permission_callback() -> None:
    tree = ast.parse(_RUNTIME_SOURCE)
    prompt_helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_prompt_messages"
    )
    assert any(isinstance(node, ast.Yield) for node in ast.walk(prompt_helper))

    query_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "query"
    )
    prompt_keyword = next(
        keyword for keyword in query_call.keywords if keyword.arg == "prompt"
    )
    assert isinstance(prompt_keyword.value, ast.Call)
    assert isinstance(prompt_keyword.value.func, ast.Name)
    assert prompt_keyword.value.func.id == "_prompt_messages"


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
