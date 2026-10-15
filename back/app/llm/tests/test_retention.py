from datetime import datetime, timedelta, timezone

import pytest

from app.llm.models import LLMCall
from app.llm.retention import prune_traces
from app.task import Task, TaskStatus
from core.params import runtime_settings


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
    assert await prune_traces() == 0
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces(preview=True) == 1
    assert calls[0].prompt == "trace"
    assert await prune_traces() == 1
    assert calls[0].prompt == ""
    assert calls[0].total_tokens == 1234 and calls[0].cost == 0.75
    assert calls[0].usage["trace_retention"] == "expired"
    assert calls[1].prompt == calls[2].prompt == "trace"
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
                                   LLMCall.total_tokens, LLMCall.cost, LLMCall.usage))).all()
    assert len(rows) == count
    for prompt, response, messages, tokens, cost, usage in rows:
        assert prompt == response == (payload if preview else "")
        assert messages == ([{"role": "user", "content": payload}] if preview else [])
        assert tokens == 42 and cost == 0.125 and usage["input_tokens"] == 21
        assert (usage.get("trace_retention") == "expired") is (not preview)
    destination = Path(__file__).resolve().parents[4] / f"artifacts/llm-retention-performance-{preview}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"preview": preview, "calls": count,
        "logical_payload_bytes": count * 4 * len(payload.encode()), "python_peak_bytes": peak}, indent=2) + "\n")
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
    calls = [LLMCall(task_id=task.id, status="completed", completed_at=old, updated_at=old, prompt="needed")
             for task in (active, child, source, unrelated)]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    assert await prune_traces() == 1
    assert all(call.prompt == "needed" for call in calls[:3])
    assert calls[3].prompt == ""


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
                     prompt="trace", cost=0.75, total_tokens=42) for round_ in rounds]
    db.add_all(calls)
    await db.flush()
    monkeypatch.setattr(retention, "_releases", {"conversation_round": facade._released_trace_ids})
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 30)
    preview = await retention.preview_trace_retention()
    assert preview["eligible"] == preview["conversation"] == 1
    assert await prune_traces() == 1
    assert calls[0].prompt == "" and calls[1].prompt == "trace"
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
