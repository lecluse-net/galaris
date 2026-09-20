from bridge.claude_agent.stream_trace import ClaudeStreamTrace


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
