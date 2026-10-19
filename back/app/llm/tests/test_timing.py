from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.schema import DropIndex

from app.llm.models import LLMCall, LLMCallEvent
from app.llm.timing import LLMProcessingTiming, execution_timing, first_output_timestamp


@pytest.mark.parametrize("unfinished", [False, True])
def test_first_output_unions_overlaps_and_leaves_missing_end_evidence_unknown(unfinished):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def at(seconds):
        return start + timedelta(seconds=seconds)

    calls = [
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(0),
            completed_at=None if unfinished else at(5), seconds=5),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(2),
            completed_at=at(6), seconds=4),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(8),
            completed_at=None, seconds=0, first_output_at=at(10)),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(20),
            completed_at=at(25), seconds=5, first_output_at=at(23)),
    ]
    result = execution_timing(calls)
    assert result.first_output_seconds == 10
    assert result.call_seconds_before_output == (None if unfinished else 8)
    assert result.between_calls_seconds == (None if unfinished else 2)
    assert execution_timing(calls[:2]).first_output_seconds is None
    assert execution_timing([]).first_call_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("generic_plan", [False, True])
async def test_first_output_read_remains_bounded_as_the_stream_grows(db, generic_plan):
    """Monitoring an old call must not reread its entire output journal."""
    import json
    from sqlalchemy import event

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    call = LLMCall(purpose="agent.exec", started_at=start)
    db.add(call)
    await db.flush()
    # Mixed early evidence, including a pre-start event and sequence order that
    # differs from wall time: the result is the minimum valid timestamp.
    payloads = [
        (-1, {"kind": "message", "message": {"type": "text", "content": "Old"}}),
        (0, {"kind": "message", "message": {"type": "thinking", "content": "Reasoning"}}),
        (1, {"kind": "message", "message": {"type": "text", "content": " \n\t"}}),
        (2, {"kind": "message", "message": {"type": "tool", "tool_name": " "}}),
        (4, {"kind": "message", "message": {"type": "text", "content": "Answer"}}),
        (3, {"kind": "message", "message": {"type": "tool", "tool_name": "synthetic_read"}}),
    ]
    await db.execute(LLMCallEvent.__table__.insert(), [
        dict(id=uuid4(), call_id=call.id, sequence=sequence,
             created_at=start + timedelta(seconds=seconds), payload=payload)
        for sequence, (seconds, payload) in enumerate(payloads)
    ] + [dict(id=uuid4(), call_id=call.id, sequence=index + len(payloads),
              created_at=start + timedelta(seconds=10 + index),
              payload={"kind": "message", "message": {"type": "text", "content": "Synthetic output"}})
         for index in range(20000)])
    await db.execute(text("ANALYZE llm_call_events"))
    if generic_plan:
        await db.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
    connection = await db.connection()
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        captured.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        output = await db.scalar(select(first_output_timestamp()).select_from(LLMCall).where(LLMCall.id == call.id))
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert output == start + timedelta(seconds=3)
    statement, parameters = captured[0]

    async def plan():
        result = await connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
        return result.scalar_one()[0]

    # Compare the same query/data with and without the temporal index, confined
    # to a savepoint in the ephemeral test database.
    savepoint = await db.begin_nested()
    try:
        for index in LLMCallEvent.__table__.indexes:
            if tuple(column.name for column in index.columns) == ("call_id", "created_at"):
                await db.execute(DropIndex(index))
        before = await plan()
    finally:
        await savepoint.rollback()
    after = await plan()
    before_blocks = before["Plan"].get("Shared Hit Blocks", 0) + before["Plan"].get("Shared Read Blocks", 0)
    after_blocks = after["Plan"].get("Shared Hit Blocks", 0) + after["Plan"].get("Shared Read Blocks", 0)
    print("SQL_PLAN first-output-20000 " + json.dumps({
        "generic_plan": generic_plan,
        "before_blocks": before_blocks, "after_blocks": after_blocks,
        "before_ms": before["Execution Time"], "after_ms": after["Execution Time"],
    }))
    if after_blocks >= before_blocks / 4:
        print("SQL_PLAN_DETAILS " + json.dumps(after))
    assert after_blocks < before_blocks / 4


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["agent.exec", "agent.synthesis", "conversation.text", "conversation.audio",
                                  "agent.dispatch", "conversation.task_objective", None])
async def test_first_output_requires_execution_evidence_and_observes_later_events(db, purpose):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    call = LLMCall(purpose=purpose, started_at=start)
    db.add(call)
    await db.flush()
    query = select(first_output_timestamp()).select_from(LLMCall).where(LLMCall.id == call.id)
    assert await db.scalar(query) is None
    db.add(LLMCallEvent(call_id=call.id, sequence=0, created_at=start + timedelta(seconds=2),
        payload={"kind": "message", "message": {"type": "text", "content": "Synthetic answer"}}))
    await db.flush()
    expected = None if purpose in ("agent.dispatch", "conversation.task_objective", None) else start + timedelta(seconds=2)
    assert await db.scalar(query) == expected
