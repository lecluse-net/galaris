from types import SimpleNamespace
from typing import Any, AsyncIterator, cast
from uuid import uuid4

import pytest
from pydantic_ai import PartStartEvent, PartDeltaEvent, PartEndEvent
from pydantic_ai.messages import ThinkingPart, ThinkingPartDelta, TextPart, TextPartDelta

from app.agent import AIResult
from app.harness.runtime import Agent, _StreamState


@pytest.mark.asyncio
async def test_thinking_is_live_and_each_model_part_keeps_its_identity():
    async def events() -> AsyncIterator[Any]:
        yield PartStartEvent(index=0, part=ThinkingPart(content="Je "))
        yield PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta="vérifie."))
        yield PartEndEvent(index=0, part=ThinkingPart(content="Je vérifie."))
        yield PartStartEvent(index=1, part=TextPart(content="Bon"))
        yield PartDeltaEvent(index=1, delta=TextPartDelta(content_delta="jour"))
        # The next model request may reuse the same part index.
        yield PartStartEvent(index=0, part=ThinkingPart(content="Autre réflexion."))

    agent = Agent(cast(Any, SimpleNamespace()), language="fr")
    fragments = [message async for message in agent._emit_stream_messages(events(), _StreamState(), None)]
    assert [m.content for m in fragments] == ["Je ", "vérifie.", "Bon", "jour", "Autre réflexion."]
    assert fragments[0].stream_id == fragments[1].stream_id
    assert fragments[2].stream_id == fragments[3].stream_id
    assert fragments[4].stream_id != fragments[0].stream_id
    result = AIResult(prompt="")
    for message in fragments:
        result.add_message(message.model_copy(deep=True))
    assert [m.content for m in result.messages] == ["Je vérifie.", "Bonjour", "Autre réflexion."]


@pytest.mark.asyncio
async def test_reasoning_end_can_complete_but_never_repeat_or_truncate_a_message():
    async def events() -> AsyncIterator[Any]:
        yield PartStartEvent(index=0, part=ThinkingPart(content="Début"))
        yield PartEndEvent(index=0, part=ThinkingPart(content="Début complet"))
        yield PartEndEvent(index=0, part=ThinkingPart(content="Début complet"))
        yield PartEndEvent(index=0, part=ThinkingPart(content="Début"))

    agent = Agent(cast(Any, SimpleNamespace()), language="fr")
    fragments = [message async for message in agent._emit_stream_messages(events(), _StreamState(), None)]
    assert [m.content for m in fragments] == ["Début", " complet"]
    assert fragments[0].stream_id == fragments[1].stream_id


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("thinking", [False, True])
async def test_completion_is_explicit_for_tasks_and_chat_keeps_live_fragments(task, thinking):
    result = AIResult(prompt="")

    async def events() -> AsyncIterator[Any]:
        part_type = ThinkingPart if thinking else TextPart
        delta_type = ThinkingPartDelta if thinking else TextPartDelta
        yield PartStartEvent(index=0, part=part_type(content="Samp"))
        assert result.messages[0].content == "Samp"
        assert result.messages[0].stream_complete is (False if task else None)
        yield PartDeltaEvent(index=0, delta=delta_type(content_delta="le image."))
        assert result.messages[0].content == "Sample image."
        assert result.messages[0].stream_complete is (False if task else None)
        yield PartEndEvent(index=0, part=part_type(content="Sample image."))

    agent = Agent(cast(Any, SimpleNamespace()), task_id=uuid4() if task else None)
    emitted = []
    async for message in agent._emit_stream_messages(events(), _StreamState(), None):
        emitted.append(message.model_copy(deep=True))
        result.add_message(message.model_copy(deep=True))
    assert [message.content for message in emitted] == ["Samp", "le image."] + ([""] if task else [])
    assert len(result.messages) == 1
    assert result.messages[0].stream_complete is (True if task else None)
    assert result.messages[0].content == "Sample image."
    assert result.result == ("" if thinking else "Sample image.")
