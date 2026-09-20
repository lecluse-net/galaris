import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import AIMessage, AIResult
from app.conversation import ConversationRuntimeStream, facade, public_ai_result
from app.conversation.runtime import room_runtime_snapshot


@pytest.mark.asyncio
async def test_message_fragments_survive_interleaving_and_terminal_snapshot(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(facade, "publish_runtime_event", publish)
    stream = ConversationRuntimeStream(room_id=uuid4(), round_id=uuid4(), attempt=2)
    await stream.start()
    await stream.append(AIMessage(type="tool", tool_name="thinking", stream_id="r", content="Je "))
    await stream.append(AIMessage(type="text", stream_id="t", content="Bon"))
    await stream.append(AIMessage(type="tool", tool_name="thinking", stream_id="r", content="vérifie."))
    await stream.append(AIMessage(type="text", stream_id="t", content="jour"))
    live = room_runtime_snapshot(stream.room_id)
    assert live.kind == "snapshot"
    assert live.sequence == 4
    assert live.attempt == 2
    assert [(m.stream_id, m.content) for m in live.result.messages] == [("r", "Je vérifie."), ("t", "Bonjour")]
    assert room_runtime_snapshot(uuid4()) is None
    terminal = AIResult(prompt="", result="Bonjour", messages=[
        AIMessage(type="text", stream_id="t", content="Bonjour"),
    ])
    snapshot = stream.snapshot(terminal)
    assert [(m.stream_id, m.content) for m in snapshot.messages] == [("r", "Je vérifie."), ("t", "Bonjour")]
    await stream.finish(success=True, result=terminal)
    await stream.finish(success=False)
    await stream.append(AIMessage(type="text", content="late"))
    events = [call.args[1] for call in publish.await_args_list]
    assert [event.sequence for event in events] == list(range(6))
    assert {event.attempt for event in events} == {2}
    assert events[-1].success
    assert events[-1].result.messages == public_ai_result(snapshot).messages
    assert room_runtime_snapshot(stream.room_id) is None


def test_same_message_id_cannot_change_kind():
    result = AIResult(prompt="")
    result.add_message(AIMessage(type="text", stream_id="m", content="hello"))
    with pytest.raises(ValueError, match="cannot change"):
        result.add_message(AIMessage(type="tool", stream_id="m", tool_name="thinking", content="oops"))


@pytest.mark.asyncio
async def test_slow_publication_coalesces_progress_without_blocking_generation(monkeypatch):
    blocked = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def publish(room_id, event):
        events.append(event)
        if event.kind == "message":
            blocked.set()
            await release.wait()

    monkeypatch.setattr(facade, "publish_runtime_event", publish)
    stream = ConversationRuntimeStream(room_id=uuid4(), round_id=uuid4())
    await stream.start()
    try:
        async with asyncio.timeout(1):
            await stream.append(AIMessage(type="text", stream_id="t", content="A"))
            await blocked.wait()
            for _ in range(100):
                await stream.append(AIMessage(type="text", stream_id="t", content="B"))
        assert len(events) == 2
        assert room_runtime_snapshot(stream.room_id).result.messages[0].content == "A" + "B" * 100
    finally:
        release.set()
        await stream.finish(success=True)
    assert [event.kind for event in events] == ["started", "message", "snapshot", "finished"]
    assert events[2].sequence == 101
    assert events[2].result.messages[0].content == "A" + "B" * 100
    assert events[-1].sequence == 102
