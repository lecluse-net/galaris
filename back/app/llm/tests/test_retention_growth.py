"""Twelve simulated weeks of ingestion, delayed consumption and bounded trace purge."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text, update

from app.conversation import facade
from app.conversation.models import ConversationProcessLink, ConversationRound
from app.conversation.tests.test_service import _scope
from app.llm import retention
from app.llm.models import LLMCall
from app.process import retention as process_retention
from app.process.models import ProcessDefinition, ProcessRun
from app.task import Task, TaskStatus
from core.params import runtime_settings


@pytest.mark.asyncio
async def test_twelve_weeks_reach_a_trace_plateau_without_losing_pending_evidence(db, monkeypatch):
    agent, connection, room = await _scope(db)
    definition = ProcessDefinition(agent_id=agent.id, tool_id=connection.tool_id,
                                   engine_process_id="retention-growth", label="Retention growth")
    db.add(definition)
    await db.flush()
    origin = datetime.now(timezone.utc) - timedelta(days=120)

    class Clock(datetime):
        current = origin

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(retention, "datetime", Clock)
    monkeypatch.setattr(runtime_settings, "LLM_TRACE_RETENTION_DAYS", 14)
    monkeypatch.setattr(retention, "_releases", {
        "conversation_round": facade._released_trace_ids,
        "process_run": process_retention.released_trace_ids,
    })
    monkeypatch.setattr(process_retention, "_guards", {"conversation": facade._process_results_still_needed})
    cohorts = []
    measurements = []
    copies = 4
    batch_size = 31

    async def drain():
        batches = []
        while count := await retention.prune_traces(batch_size=batch_size):
            assert count <= batch_size
            batches.append(count)
            await db.commit()
        return sum(batches)

    async def release(cohort):
        await db.execute(update(ConversationRound).where(ConversationRound.id == cohort["round"]).values(delivery_state="DELIVERED"))
        await db.execute(update(ConversationProcessLink).where(ConversationProcessLink.process_run_id == cohort["process"]).values(notification_state="DELIVERED"))
        await db.execute(update(Task).where(Task.id == cohort["task"]).values(status=TaskStatus.SUCCESS))

    for day in range(84):
        Clock.current = origin + timedelta(days=day)
        completed = Clock.current - timedelta(seconds=1)
        rounds = [ConversationRound(room_id=room.id, status="SUCCEEDED", delivery_state=state,
                                    finished_at=completed) for state in ("DELIVERED", "PENDING")]
        task = Task(label="Awaited work", agent_id=agent.id, status=TaskStatus.PLAN)
        runs = [ProcessRun(process_id=definition.id, launcher_agent_id=agent.id,
                           engine_code="retention-test", correlation_id=uuid4().hex,
                           callback_token="test", status="success", finished_at=completed,
                           output={"receipt": "keep"}) for _ in range(2)]
        db.add_all([*rounds, *runs, task])
        await db.flush()
        db.add(ConversationProcessLink(round_id=rounds[1].id, process_run_id=runs[1].id,
                                       action_key=f"wait-{day}", notification_state="PENDING"))
        owners = [{}, {"conversation_round_id": rounds[0].id}, {"process_run_id": runs[0].id},
                  {"conversation_round_id": rounds[1].id}, {"process_run_id": runs[1].id}, {"task_id": task.id}]
        await db.execute(insert(LLMCall), [dict(agent_id=agent.id, status="completed", completed_at=completed,
            updated_at=completed, prompt="p" * 2048, response_text="r" * 2048,
            total_tokens=42, cost=0.125, **owner) for owner in owners for _ in range(copies)])
        cohorts.append({"round": rounds[1].id, "process": runs[1].id, "task": task.id})
        if day >= 21:
            await release(cohorts[day - 21])
        await db.commit()
        await drain()
        expected = (min(day + 1, 14) + min(day + 1, 21)) * 3 * copies
        raw_count = await db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.prompt != ""))
        assert raw_count == expected, (day, raw_count, expected)
        if day % 7 == 6:
            reasons = await retention.preview_trace_retention()
            assert reasons.get("eligible", 0) == 0
            if day >= 21:
                assert all(reasons.get(key, 0) > 0 for key in ("conversation", "process", "task"))
            logical_bytes = await db.scalar(select(func.sum(func.octet_length(LLMCall.prompt) + func.octet_length(LLMCall.response_text))))
            measurements.append({"week": (day + 1) // 7, "calls": (day + 1) * 6 * copies,
                                 "raw_traces": raw_count, "logical_trace_bytes": logical_bytes,
                                 "physical_table_bytes": await db.scalar(text("SELECT pg_total_relation_size('llm_calls')")),
                                 "protected_reasons": reasons})

    assert len({entry["logical_trace_bytes"] for entry in measurements[3:]}) == 1
    for cohort in cohorts[-21:]:
        await release(cohort)
    Clock.current += timedelta(days=22)
    await db.commit()
    assert await drain() == 420
    assert await db.scalar(select(func.count()).select_from(LLMCall).where(LLMCall.prompt != "")) == 0
    total, tokens, cost = (await db.execute(select(func.count(LLMCall.id), func.sum(LLMCall.total_tokens), func.sum(LLMCall.cost)))).one()
    assert total == 2016 and tokens == total * 42 and cost == total * 0.125
    assert await db.scalar(select(func.count()).select_from(ProcessRun).where(ProcessRun.output.is_not(None))) == 168
    destination = Path(__file__).resolve().parents[4] / "artifacts/llm-retention-growth.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"simulated_days": 84, "retention_days": 14,
        "consumer_delay_days": 21, "daily_calls": 24, "batch_limit": batch_size,
        "measurements": measurements, "final_calls": total, "final_tokens": tokens,
        "final_cost": cost, "raw_traces_after_all_consumers_release": 0,
        "physical_storage_note": "MVCC pages include dead tuples; logical expiry does not promise filesystem shrinkage."}, indent=2) + "\n")
