from bridge.claude_agent.stream_trace import ClaudeStreamTrace
import pytest


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("via_hook", [False, True])
def test_sdk_result_keeps_denied_and_successful_tools_without_duplicating_hooks(failed, via_hook):
    trace = ClaudeStreamTrace()
    trace.record_tool_call("call-1", "Write", {"file_path": "/workspace/report", "content": "Synthetic"})
    outcome = {"output": "Denied" if failed else "Written"}
    message = trace.complete_tool_result("call-1", [{"type": "text", "text": outcome["output"]}],
        failed=failed and not via_hook, result={**outcome, "isError": failed} if via_hook else None)
    assert message["tool_name"] == "Write"
    assert message["tool_call_external_id"] == "call-1"
    assert message["tool_arguments"]["content"] == "Synthetic"
    assert message["tool_result"]["output"] == ("Denied" if failed else "Written")
    assert message["success"] is not failed
    assert trace.complete_tool_result("call-1", "Same SDK result", failed=failed) is None


def test_thinking_deltas_become_one_semantic_message_at_block_stop() -> None:
    trace = ClaudeStreamTrace()

    assert trace.consume({
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "thinking_delta", "thinking": "Inspecting "},
    }) == []
    assert trace.consume({
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "thinking_delta", "thinking": "the contract."},
    }) == []

    assert trace.consume({"type": "content_block_stop", "index": 2}) == [{
        "type": "tool",
        "tool_name": "thinking",
        "content": "Inspecting the contract.",
        "success": True,
    }]
    assert trace.finish() == []


def test_finish_flushes_a_thinking_block_when_stop_is_missing() -> None:
    trace = ClaudeStreamTrace()
    trace.consume({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Public summary"},
    })

    assert [message["content"] for message in trace.finish()] == ["Public summary"]
