from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.agent.contracts import AIResult
from app.llm import llm_call_service
from app.llm.inference_store import read_event_batch
from app.llm.models import LLMCall, LLMCallEvent, LLMInference, LLMInferenceAttempt
from app.llm.retention import prune_call_events, prune_traces
from app.llm.timing import first_output_timestamp
from app.task import Task, TaskStatus
from core.params import runtime_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_days", [0, 30])
async def test_weekly_retention_preserves_cost_timings_and_final_results(db, monkeypatch, configured_days):
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", configured_days)
    monkeypatch.setattr("app.llm.retention._EVENT_BATCH_SIZE", 1)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=8)
    recent = now - timedelta(days=6)
    inference = LLMInference(request={}, status="running", generation=2)
    task = Task(label="Archived task", objective="<p>Synthetic task objective</p>", status=TaskStatus.SUCCESS)
    db.add_all([inference, task])
    await db.flush()
    result = AIResult(prompt="Synthetic prompt", system_prompt="", success=True, result="Synthetic answer")
    finished = LLMInferenceAttempt(
        inference_id=inference.id, number=1, status="completed", completed_at=old,
        final_sequence=2, result=result.model_dump(mode="json"),
    )
    running = LLMInferenceAttempt(inference_id=inference.id, number=2, status="running")
    db.add_all([finished, running])
    await db.flush()
    prompt_excerpt = "é" * 499 + "🧪"
    calls = [
        LLMCall(status="completed", completed_at=old, inference_attempt_id=finished.id, cost=0.75, task_id=task.id,
                purpose="agent.exec", started_at=old - timedelta(seconds=9), duration=9,
                first_token_at=old - timedelta(seconds=7), total_tokens=123, prompt=prompt_excerpt + " trailing text",
                request_messages=[{"content": "Request"}], reasoning="Reasoning", response_text="Answer",
                system_prompt="System", raw_response="Raw response", tool_calls=[
                    {"id": "tool-1", "type": "function", "name": "tool_call", "status": "completed",
                     "arguments": {"name": "file_read", "arguments": {"uri": "fixture://private"}},
                     "result": "Synthetic payload", "started_at": (old - timedelta(seconds=2)).isoformat(),
                     "completed_at": old.isoformat()},
                    {"id": "tool-2", "name": "file_search", "status": "requested", "arguments": {"query": "fixture"}},
                ]),
        LLMCall(status="completed", completed_at=old),
        LLMCall(status="completed", completed_at=old, inference_attempt_id=running.id),
        LLMCall(status="completed", completed_at=recent, response_text="Recent detail"),
        LLMCall(status="running"),
    ]
    for call in calls:
        call.updated_at = call.completed_at or old
    db.add_all(calls)
    await db.flush()
    events = [
        LLMCallEvent(
            call_id=call.id, sequence=1, created_at=old, payload={"kind": "wire"},
            inference_id=inference.id if call.inference_attempt_id is not None else None,
        )
        for call in calls
    ]
    events[0].payload = {"kind": "message", "message": {"type": "text", "content": "Answer"}}
    events[0].created_at = old - timedelta(seconds=3)
    events[0].inference_sequence = 1
    events[3].payload = {"kind": "message", "message": {"type": "text", "content": "Recent detail"}}
    events[3].created_at = recent + timedelta(seconds=1)
    calls[3].purpose = "agent.exec"
    calls[3].started_at = recent - timedelta(seconds=1)
    future_event = LLMCallEvent(call_id=calls[1].id, sequence=2, created_at=now - timedelta(minutes=5),
                                payload={"kind": "wire"})
    db.add_all([*events, future_event])
    await db.flush()

    assert await prune_traces(preview=True) == 1
    assert await prune_traces() == 1
    assert await prune_traces() == 0
    assert len((await db.scalars(select(LLMCallEvent.id))).all()) == 6
    assert await prune_call_events() == 1
    assert await prune_call_events() == 1
    assert await prune_call_events() == 1
    assert await prune_call_events() == 0
    assert set(await db.scalars(select(LLMCallEvent.id))) == {events[2].id, events[4].id, future_event.id}
    assert calls[3].response_text == "Recent detail"
    assert await db.scalar(select(first_output_timestamp()).where(LLMCall.id == calls[3].id)) == events[3].created_at
    assert calls[0].prompt == prompt_excerpt
    assert calls[0].system_prompt == calls[0].response_text == calls[0].reasoning == ""
    assert calls[0].request_messages == []
    assert calls[0].raw_response == ""
    summaries = [
        {"id": "tool-1", "type": "function", "name": "file_read", "status": "completed",
         "started_at": (old - timedelta(seconds=2)).isoformat(), "completed_at": old.isoformat()},
        {"id": "tool-2", "name": "file_search", "status": "requested"},
    ]
    assert calls[0].tool_calls == summaries
    await llm_call_service.attach_tool_results(
        messages=[{"role": "tool", "tool_call_id": "tool-2", "content": "Late synthetic payload"}],
        agent_id=None, task_id=task.id,
    )
    call_id = calls[0].id
    db.expunge(calls[0])
    archived = await llm_call_service.get_call(call_id)
    assert archived is not None
    serialized = await llm_call_service.serialize_call(archived)
    assert serialized.prompt == prompt_excerpt
    assert serialized.tool_calls == [{**summary, "arguments": {}} for summary in summaries]
    assert (archived.cost, archived.total_tokens, archived.duration) == (0.75, 123, 9)
    observed = await db.scalar(select(first_output_timestamp()).where(LLMCall.id == call_id))
    assert observed == old - timedelta(seconds=3)
    assert archived.first_token_at == old - timedelta(seconds=7)
    status, stream = await read_event_batch(inference.id, finished.id)
    assert status == "completed"
    assert len(stream) == 1 and stream[0].kind == "result"
    assert stream[0].result == result


@pytest.mark.asyncio
async def test_retention_preserves_accounting_and_active_work(db, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(days=60)
    task = Task(label="Active parent", status=TaskStatus.PLAN)
    db.add(task)
    await db.flush()
    calls = [LLMCall(
        status=status, completed_at=old, updated_at=old,
        prompt="trace", response_text="response", total_tokens=1234, cost=0.75,
        task_id=task.id if linked else None,
    ) for status, linked in [("completed", False), ("running", False), ("completed", True)]]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 0)
    assert await prune_traces(preview=True) == 1
    assert calls[0].prompt == "trace"
    assert await prune_traces() == 1
    assert calls[0].prompt == "trace" and calls[0].response_text == ""
    assert calls[0].total_tokens == 1234 and calls[0].cost == 0.75
    assert calls[0].usage["trace_retention"] == "expired"
    assert all(call.prompt == "trace" and call.response_text == "response" for call in calls[1:])
    assert await prune_traces() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("preview", [True, False])
async def test_retention_does_not_materialize_payloads_to_discard_them(db, monkeypatch, preview):
    import json
    from pathlib import Path
    import tracemalloc
    from sqlalchemy import insert, select

    old = datetime.now(timezone.utc) - timedelta(days=60)
    payload = "synthetic trace " * 20000
    count = 8
    await db.execute(insert(LLMCall), [dict(
        status="completed", completed_at=old, updated_at=old, prompt=payload,
        response_text=payload, raw_response=payload,
        request_messages=[{"role": "user", "content": payload}],
        tool_calls=[{"name": "file_read", "arguments": {"value": payload}, "result": payload}],
        total_tokens=42, cost=0.125, usage={"input_tokens": 21},
    ) for _ in range(count)])
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    db.expunge_all()
    tracemalloc.start()
    try:
        assert await prune_traces(preview=preview) == count
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    rows = (await db.execute(select(LLMCall.prompt, LLMCall.response_text, LLMCall.request_messages,
                                   LLMCall.total_tokens, LLMCall.cost, LLMCall.usage, LLMCall.tool_calls))).all()
    assert len(rows) == count
    for prompt, response, messages, tokens, cost, usage, tools in rows:
        assert prompt == (payload if preview else payload[:500])
        assert response == (payload if preview else "")
        assert messages == ([{"role": "user", "content": payload}] if preview else [])
        assert tokens == 42 and cost == 0.125 and usage["input_tokens"] == 21
        assert (usage.get("trace_retention") == "expired") is (not preview)
        assert tools == ([{"name": "file_read", "arguments": {"value": payload}, "result": payload}]
                         if preview else [{"name": "file_read"}])
    destination = Path(__file__).resolve().parents[4] / f"artifacts/llm-retention-performance-{preview}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"preview": preview, "calls": count,
        "logical_payload_bytes": count * 6 * len(payload.encode()), "python_peak_bytes": peak}, indent=2) + "\n")
    assert peak < 4 * 1024 * 1024, f"Retention allocated {peak} bytes while discarding trace payloads"


@pytest.mark.asyncio
async def test_retention_protects_causal_relatives_but_not_unrelated_completed_work(db, monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(days=60)
    active = Task(label="Active", status=TaskStatus.PLAN)
    unrelated = Task(label="Unrelated", status=TaskStatus.SUCCESS)
    db.add_all([active, unrelated])
    await db.flush()
    child = Task(label="Consumed later", status=TaskStatus.SUCCESS, parent_id=active.id)
    source = Task(label="Causal source", status=TaskStatus.SUCCESS)
    db.add_all([child, source])
    await db.flush()
    active.source_task_id = source.id
    calls = [LLMCall(task_id=task.id, status="completed", completed_at=old, updated_at=old, prompt="n" * 501)
             for task in (active, child, source, unrelated)]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces() == 1
    assert all(call.prompt == "n" * 501 for call in calls[:3])
    assert calls[3].prompt == "n" * 500


@pytest.mark.asyncio
async def test_conversation_release_requires_delivery_and_consumed_work(db, monkeypatch):
    from app.conversation.tests.test_service import _scope
    from app.conversation.models import ConversationRound
    from app.conversation import facade
    from app.llm import retention

    _agent, _connection, room = await _scope(db)
    old = datetime.now(timezone.utc) - timedelta(days=60)
    rounds = [ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state=state, finished_at=old)
              for state in ("DELIVERED", "PENDING")]
    db.add_all(rounds)
    await db.flush()
    calls = [LLMCall(conversation_round_id=round_.id, status="completed", completed_at=old, updated_at=old,
                     prompt="trace", response_text="answer", cost=0.75, total_tokens=42) for round_ in rounds]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(retention, "_releases", {"conversation_round": facade._released_trace_ids})
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    preview = await retention.preview_trace_retention()
    assert preview["eligible"] == preview["conversation"] == 1
    assert await prune_traces() == 1
    assert calls[0].prompt == calls[1].prompt == "trace"
    assert calls[0].response_text == "" and calls[1].response_text == "answer"
    assert await retention.preview_trace_retention() == {"conversation": 1}
    assert calls[0].cost == 0.75 and calls[0].total_tokens == 42


@pytest.mark.asyncio
async def test_preview_obeys_management_scope_including_task_lineage(db, monkeypatch):
    from unittest.mock import AsyncMock
    from app.agent import AgentManagementScope
    from app.conversation.tests.test_service import _scope
    from app.llm import call_router

    agent, _connection, _room = await _scope(db)
    task = Task(label="Finished", agent_id=agent.id, status=TaskStatus.SUCCESS)
    db.add(task)
    await db.flush()
    old = datetime.now(timezone.utc) - timedelta(days=60)
    calls = [LLMCall(task_id=task.id if linked else None, status="completed",
                     completed_at=old, updated_at=old, prompt="private") for linked in (True, False)]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    monkeypatch.setattr(call_router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, frozenset({agent.id}))))
    assert await call_router.preview_call_retention() == {"eligible": 1}
    monkeypatch.setattr(call_router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(1, frozenset())))
    assert await call_router.preview_call_retention() == {}
    assert all(call.prompt == "private" for call in calls)
