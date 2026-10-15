"""Bounded trace reads and bulk supervision context over synthetic call histories."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter
import tracemalloc
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select

from app.llm import llm_call_service
from app.llm.models import LLMCall
from app.task import Task, TaskStatus


def measurement(name, value):
    destination = Path(__file__).resolve().parents[4] / f"artifacts/{name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True])
async def test_tool_results_read_full_payloads_only_for_matching_calls(db, monkeypatch, reused):
    task = Task(label="Synthetic tool result owner")
    db.add(task)
    await db.flush()
    task_id = task.id
    payload = "synthetic trace " * 20000
    ids = [uuid4() for _ in range(24)]
    await db.execute(insert(LLMCall), [dict(
        id=call_id, task_id=task_id, status="completed", prompt=payload, raw_response=payload,
        response_text="preserved response", request_messages=[{"role": "user", "content": f"root-{index}"}],
        tool_calls=[{"id": "target" if index == 0 or (reused and index == 1) else f"other-{index}",
                     "name": "synthetic_read", "arguments": {"index": index}}],
        total_tokens=42, cost=0.125,
    ) for index, call_id in enumerate(ids)])
    await db.commit()
    db.expunge_all()
    emitted = AsyncMock()
    monkeypatch.setattr(llm_call_service.websocket, "emit", emitted)
    tracemalloc.start()
    try:
        await llm_call_service.attach_tool_results(
            messages=[{"role": "user", "content": "root-0"},
                      {"role": "tool", "tool_call_id": "target", "content": "synthetic result"}],
            agent_id=None, task_id=task_id,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    event_payload = emitted.await_args.args[2]
    assert emitted.await_count == 1 and event_payload["id"] == str(ids[0])
    assert event_payload["prompt"] == event_payload["raw_response"] == payload
    assert event_payload["response_text"] == "preserved response"
    assert event_payload["cost"] == 0.125 and event_payload["total_tokens"] == 42
    assert event_payload["tool_calls"][0]["result"] == "synthetic result"
    tools = (await db.execute(select(LLMCall.id, LLMCall.tool_calls))).all()
    assert len(tools) == 24
    assert [call_id for call_id, calls in tools if "result" in calls[0]] == [ids[0]]
    measurement(f"llm-tool-result-performance-{reused}", {"calls": len(ids), "reused_tool_id": reused,
        "logical_large_payload_bytes": len(ids) * 2 * len(payload.encode()), "python_peak_bytes": peak})
    assert peak < 4 * 1024 * 1024, f"Attaching one tool result allocated {peak} bytes of trace history"


@pytest.mark.asyncio
async def test_supervision_preserves_order_context_and_costs_with_bulk_reads(db):
    from app.conversation.tests.test_service import _scope
    from app.process.models import ProcessDefinition, ProcessRun

    agent, connection, _room = await _scope(db)
    definition = ProcessDefinition(agent_id=agent.id, tool_id=connection.tool_id,
        engine_process_id="synthetic-supervision", label="Synthetic process")
    db.add(definition)
    await db.flush()
    tasks = [Task(label=f"Synthetic task {n}", objective=f"<p>Objective {n}</p>",
                  agent_id=agent.id, status=TaskStatus.SUCCESS) for n in range(500)]
    runs = [ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code="synthetic",
                       correlation_id=uuid4().hex, callback_token="unused", status="success") for _ in tasks]
    db.add_all([*tasks, *runs])
    await db.flush()
    calls = [LLMCall(task_id=task.id, agent_id=agent.id, process_run_id=run.id, status="completed",
                     purpose="agent.exec", prompt="Original trace", total_tokens=42, cost=0.125)
             for task, run in zip(tasks, runs, strict=True)]
    db.add_all(calls)
    tasks[0].soft_delete()
    runs[1].soft_delete()
    await db.commit()
    ordered = list(reversed(calls))
    samples = []
    statements = []
    connection = await db.connection()

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        for _ in range(3):
            started = perf_counter()
            serialized = await llm_call_service.serialize_calls(ordered)
            samples.append(perf_counter() - started)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert [call.id for call in serialized] == [call.id for call in ordered]
    for index, call in enumerate(reversed(serialized)):
        assert call.task_label == (f"Synthetic task {index}" if index else None)
        assert call.prompt == (f"<p>Objective {index}</p>" if index else "Original trace")
        assert call.task_status == (TaskStatus.SUCCESS.value if index else None)
        assert call.process_label == ("Synthetic process" if index != 1 else None)
        assert call.agent_name == f"{agent.first_name} {agent.last_name}".strip()
        assert call.agent_code == agent.code
        assert call.cost == 0.125 and call.total_tokens == 42
    assert len(statements) <= 9, "Context reads must remain batched as the call list grows"
    measurement("llm-call-serialization-performance", {"calls": len(calls), "samples_seconds": samples,
        "median_seconds": median(samples), "queries_per_pass": len(statements) / 3})
