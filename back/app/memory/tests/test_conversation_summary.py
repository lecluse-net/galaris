"""Explicit summaries retain synthesized HTML and never save raw text on failure."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.memory import conversation_summary, mcp
from app.memory.models import MemoryItem
from app.tools import McpToolContext


@pytest.mark.asyncio
async def test_summary_escapes_model_output_and_preserves_attribution(monkeypatch):
    monkeypatch.setattr(conversation_summary, "get_agent_record", AsyncMock(return_value=object()))
    monkeypatch.setattr(conversation_summary, "get_llm_for_agent", AsyncMock(return_value=object()))
    inference = AsyncMock(
        return_value=SimpleNamespace(
            output=conversation_summary.ConversationSummary(
                facts=[
                    "Alice agreed to review <draft> & reply tomorrow.",
                    "Bob's proposal remains undecided.",
                ]
            )
        )
    )
    monkeypatch.setattr(conversation_summary, "run_prompted", inference)
    result = await conversation_summary.summarize_transcript(
        "Alice: I will review it tomorrow.",
        agent_id=7,
        task_id=None,
        language="en",
    )
    assert (
        result
        == "<ul><li>Alice agreed to review &lt;draft&gt; &amp; reply tomorrow.</li><li>Bob&#x27;s proposal remains undecided.</li></ul>"
    )
    assert inference.await_args.kwargs["prompt"] == "Alice: I will review it tomorrow."
    assert inference.await_args.kwargs["agent_id"] == 7


@pytest.mark.asyncio
async def test_bounded_summary_failure_does_not_persist_transcript(
    db, agents, memory_storage, monkeypatch
):
    agent = agents[0]
    transcript = "older message " * 4000 + "latest decision"
    driver = SimpleNamespace(
        history=AsyncMock(
            return_value=[
                SimpleNamespace(
                    sender=SimpleNamespace(display_name="Alice", id="alice"), text=transcript
                )
            ]
        )
    )
    monkeypatch.setattr("app.messenger.messenger_for_agent", AsyncMock(return_value=driver))
    inference = AsyncMock(side_effect=RuntimeError("Model unavailable"))
    monkeypatch.setattr(conversation_summary, "summarize_transcript", inference)
    before = await db.scalar(select(func.count()).select_from(MemoryItem))
    result = json.loads(
        await mcp.memory_summarize(
            McpToolContext(agent_id=agent.id, runtime="internal"),
            room_id="room",
            limit=500,
        )
    )
    assert "error" in result and "memory_id" not in result
    assert await db.scalar(select(func.count()).select_from(MemoryItem)) == before
    driver.history.assert_awaited_once_with("room", 200)
    assert len(inference.await_args.args[0]) == 32_000
    assert inference.await_args.args[0].endswith("latest decision")


@pytest.mark.asyncio
async def test_empty_conversation_never_calls_model(db, agents, monkeypatch):
    driver = SimpleNamespace(history=AsyncMock(return_value=[]))
    monkeypatch.setattr("app.messenger.messenger_for_agent", AsyncMock(return_value=driver))
    inference = AsyncMock()
    monkeypatch.setattr(conversation_summary, "summarize_transcript", inference)
    result = json.loads(
        await mcp.memory_summarize(
            McpToolContext(agent_id=agents[0].id, runtime="internal"),
            room_id="room",
        )
    )
    assert "error" in result
    inference.assert_not_awaited()
