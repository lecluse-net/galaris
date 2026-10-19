"""Synthetic stream cost measurements and durable progress contracts."""

import json
import asyncio
import tracemalloc
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from app.llm import llm_call_service
from app.llm.models import LLMCall
from app.llm.stream_updates import StreamUpdates


@pytest.mark.asyncio
async def test_running_trace_cost_does_not_transfer_request_history(db, monkeypatch):
    history = "synthetic request context " * 40000
    call = LLMCall(status="running", prompt=history, system_prompt=history,
                   request_messages=[{"role": "user", "content": history}])
    db.add(call)
    await db.commit()
    emitted = AsyncMock()
    monkeypatch.setattr(llm_call_service.websocket, "emit", emitted)
    statements = []
    update_bytes = 0
    connection = await db.connection()

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal update_bytes
        statements.append(statement)
        if statement.lstrip().upper().startswith("UPDATE LLM_CALLS"):
            update_bytes += len(json.dumps(_parameters, default=str, ensure_ascii=False).encode())

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    started = perf_counter()
    try:
        for index in range(12):
            await llm_call_service.update_running_call(call.id, trace={
                "response_text": "synthetic output " * (index + 1) * 1000,
                "reasoning": "synthetic reasoning " * (index + 1) * 1000,
                "tool_calls": [], "usage": {},
            })
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    payloads = [args.args[2] for args in emitted.await_args_list]
    measurements = {
        "updates": len(payloads), "sql_statements": len(statements),
        "websocket_bytes": sum(len(json.dumps(payload).encode()) for payload in payloads),
        "elapsed_seconds": perf_counter() - started,
        "update_parameter_bytes": update_bytes,
        "select_statements": sum(statement.lstrip().upper().startswith("SELECT") for statement in statements),
    }
    destination = Path(__file__).resolve().parents[4] / "artifacts/stream-running-trace.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(measurements, indent=2) + "\n")
    # Published progress must be proportional to generated output, independently
    # of the much larger, unchanged prompt and input history.
    assert measurements["websocket_bytes"] < 600000, measurements
    assert not any("request_messages" in payload or "prompt" in payload for payload in payloads)
    assert not any("request_messages" in statement for statement in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("during_update", [False, True])
async def test_supervision_flushes_last_fragment_without_another_provider_event(monkeypatch, during_update):
    from uuid import uuid4

    published = []
    first = asyncio.Event()
    release = asyncio.Event()
    text = "Thinking"

    async def receive(_call_id, *, trace):
        published.append(trace["response_text"])
        first.set()
        if during_update:
            await release.wait()

    monkeypatch.setattr(llm_call_service, "update_running_call", receive)
    updates = StreamUpdates(uuid4(), lambda: {"trace": {"response_text": text}})
    try:
        updates.changed()
        await asyncio.wait_for(first.wait(), 1)
        text = "Thinking. First visible answer"
        updates.changed()
        release.set()
        async with asyncio.timeout(0.75):
            while published[-1] != text:
                await asyncio.sleep(0.01)
    finally:
        await updates.close()


@pytest.mark.asyncio
async def test_slow_supervision_is_bounded_and_joined_before_terminal(monkeypatch):
    from uuid import uuid4

    entered, released = asyncio.Event(), asyncio.Event()
    snapshots = []

    async def slow(*_args, **_kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.set()

    monkeypatch.setattr(llm_call_service, "update_running_call", slow)
    updates = StreamUpdates(uuid4(), lambda: snapshots.append(True) or {"trace": {}})
    updates.changed()
    await asyncio.wait_for(entered.wait(), 1)
    for _ in range(10000):
        updates.changed()
    assert len(snapshots) == 1
    await asyncio.wait_for(updates.close(), 1)
    assert released.is_set()


@pytest.mark.asyncio
async def test_late_progress_cannot_overwrite_terminal_trace(db, monkeypatch):
    call = LLMCall(status="completed", response_text="Authoritative terminal output")
    db.add(call)
    await db.commit()
    emitted = AsyncMock()
    monkeypatch.setattr(llm_call_service.websocket, "emit", emitted)
    await llm_call_service.update_running_call(call.id, trace={"response_text": "Late partial"})
    await db.refresh(call)
    assert call.response_text == "Authoritative terminal output"
    emitted.assert_not_awaited()


@pytest.mark.asyncio
async def test_progress_preserves_tool_presentation_without_repeating_unchanged_tools(db, monkeypatch):
    call = LLMCall(status="running")
    db.add(call)
    await db.commit()
    emitted = AsyncMock()
    monkeypatch.setattr(llm_call_service.websocket, "emit", emitted)
    trace = {"tool_calls": [{"id": "synthetic-tool", "type": "function", "name": "tool_call",
        "arguments": {"name": "mcp__galaris__file_read", "arguments": {"uri": "synthetic://file"}},
        "status": "requested"}]}
    await llm_call_service.update_running_call(call.id, trace=trace)
    await llm_call_service.update_running_call(call.id, trace=trace)
    first, second = [args.args[2] for args in emitted.await_args_list]
    assert first["tool_calls"][0]["name"] == "file_read"
    assert first["tool_calls"][0]["arguments"] == {"uri": "synthetic://file"}
    assert "tool_calls" not in second


def test_journal_representations_wake_only_their_readers_and_lifecycle_wakes_all():
    from uuid import uuid4
    from app.llm import inference_notifications as notifications

    key = uuid4()
    with notifications.subscribe("messages", key) as messages, notifications.subscribe("wire", key) as wire:
        notifications.notify("wire", key)
        assert wire.is_set() and not messages.is_set()
        wire.clear()
        notifications.notify("messages", key)
        assert messages.is_set() and not wire.is_set()
        messages.clear()
        notifications.notify("changes", key)
        assert messages.is_set() and wire.is_set()
    assert not any(identity == key for _, identity in notifications._subscribers)


def test_trace_memory_retains_output_and_envelope_without_every_decoded_frame():
    from app.llm.trace import StreamTrace
    from app.llm.proxy_service import _chat_completion_from_stream_trace

    trace = StreamTrace()
    tracemalloc.start()
    try:
        for index in range(10000):
            trace.add_payload({"id": "synthetic", "created": 1, "model": "synthetic-model",
                "service_tier": "synthetic-tier", "system_fingerprint": "synthetic-fingerprint",
                "choices": [{"delta": {"content": f"fragment {index} "}}],
                "unused_provider_metadata": "synthetic padding " * 100 + str(index)})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    completion = _chat_completion_from_stream_trace(trace, model="fallback")
    assert completion["model"] == "synthetic-model"
    assert completion["created"] == 1
    assert completion["service_tier"] == "synthetic-tier"
    assert completion["system_fingerprint"] == "synthetic-fingerprint"
    assert completion["choices"][0]["message"]["content"] == "".join(f"fragment {index} " for index in range(10000))
    assert peak < 3 * 1024 * 1024, peak
