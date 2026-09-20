from datetime import datetime, timezone
from uuid import uuid4

from app.llm.llm_call_service import _public  # pyright: ignore[reportPrivateUsage]
from app.llm.models import LLMCall


def test_public_llm_call_drops_empty_finished_tool_calls() -> None:
    now = datetime.now(timezone.utc)
    call = LLMCall(
        id=uuid4(),
        provider_name="internal",
        requested_model="model",
        effective_model="model",
        status="completed",
        stream=True,
        request_messages=[],
        prompt="prompt",
        system_prompt="system",
        response_text="   ",
        reasoning="\n",
        tool_calls=[
            {"id": "empty", "name": "empty_tool", "arguments": {}, "result": "  "},
            {"id": "with_args", "name": "lookup", "arguments": {"query": "x"}, "result": ""},
            {
                "id": "deferred",
                "name": "tool_call",
                "arguments": {
                    "name": "mcp__galaris__messenger_room_send_message",
                    "arguments": {"room_id": "room-42", "message": "Bonjour"},
                },
            },
        ],
        usage={},
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=0,
        cost=0.0,
        cost_estimated=True,
        started_at=now,
        duration=0.0,
        created_at=now,
        updated_at=now,
    )

    payload = _public(call)

    assert payload["response_text"] == ""
    assert payload["reasoning"] == ""
    assert [tool["id"] for tool in payload["tool_calls"]] == ["with_args", "deferred"]
    assert payload["tool_calls"][1]["name"] == "messenger_room_send_message"
    assert payload["tool_calls"][1]["arguments"] == {
        "room_id": "room-42",
        "message": "Bonjour",
    }
