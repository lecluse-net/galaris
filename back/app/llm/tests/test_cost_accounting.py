from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.llm import llm_call_service
from app.llm.models import LLMCall
from app.llm.cost_accounting import call_cost, summarize_costs
from app.llm.accounting_scope import llm_call_accounting


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,rates,quality,total", [
    ({"prompt_tokens": 100, "completion_tokens": 20}, {}, "unknown", None),
    ({"prompt_tokens": 100, "completion_tokens": 20}, {"input_rate": 0, "output_rate": 0}, "estimated", 0),
    ({"prompt_tokens": 100, "completion_tokens": 20}, {"input_rate": 2, "output_rate": 4}, "estimated", .00028),
    ({"cost": 0}, {}, "exact", 0),
    ({"cost": .2}, {"input_rate": 999, "output_rate": 999}, "exact", .2),
    ({"prompt_tokens": 100, "completion_tokens": 20}, {"input_rate": float("nan"), "output_rate": 4}, "unknown", None),
])
async def test_persisted_cost_provenance_distinguishes_missing_and_free(db, monkeypatch, usage, rates, quality, total):
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    row = LLMCall(status="running")
    db.add(row)
    await db.commit()
    with llm_call_accounting() as accounting:
        await llm_call_service.finalize_call(row.id, trace={"usage": usage}, **rates)
    await db.refresh(row)
    summary = accounting.snapshot()
    assert summary.quality == quality
    assert summary.total_cost == (pytest.approx(total) if total is not None else None)
    assert summary.entries[0].call_id == row.id
    if quality == "estimated":
        assert row.usage["_galaris_cost"]["input_rate"] == rates["input_rate"]


def test_subscription_and_running_costs_keep_independent_unknowns():
    def entry(**changes):
        return call_cost(**({"call_id": uuid4(), "status": "completed", "cost": 0,
            "inference_cost": 0, "cost_estimated": True, "usage": {}, "is_subscription": False} | changes))
    subscription = entry(is_subscription=True)
    assert subscription.cost == 0 and subscription.inference_cost is None
    assert summarize_costs([subscription]).total_cost == 0
    unknown = entry()
    partial = summarize_costs([subscription, unknown])
    assert partial.unknown_calls == 1 and partial.total_cost is None
    running = summarize_costs([entry(status="running", cost=.2, inference_cost=.2, cost_estimated=False)])
    assert running.recorded_cost == .2 and running.total_cost is None
    assert summarize_costs([]).total_cost is None
    historical = summarize_costs([entry(cost=.2, cost_estimated=False)])
    assert historical.total_cost == .2 and historical.inference_cost is None


@pytest.mark.asyncio
async def test_run_accounting_has_no_display_pagination_limit_and_guards_all_calls(db):
    from sqlalchemy import insert
    from app.llm.facade import aggregate_agent_run_usage

    run = uuid4()
    await db.execute(insert(LLMCall), [{"agent_run_id": run, "status": "completed", "cost": .001,
        "inference_cost": .001, "cost_estimated": False} for _ in range(10_001)])
    usage = await aggregate_agent_run_usage(run)
    assert usage["requests"] == 10_001
    assert usage["cost"] == pytest.approx(10.001)
    with pytest.raises(PermissionError):
        await aggregate_agent_run_usage(run, agent_id=2147483647)


@pytest.mark.asyncio
async def test_late_charge_enriches_unknown_cost_without_reopening_or_rebilling(db, monkeypatch):
    from app.llm.models import LLMCallCost
    monkeypatch.setattr(llm_call_service.websocket, "emit", AsyncMock())
    row = LLMCall(status="running", prompt="Synthetic private prompt")
    db.add(row)
    await db.commit()
    await llm_call_service.finalize_call(row.id, trace={}, status="cancelled")
    await llm_call_service.finalize_call(row.id, trace={"usage": {"cost": .4}}, status="cancelled")
    await llm_call_service.finalize_call(row.id, trace={"usage": {"cost": .9}}, status="cancelled")
    await db.refresh(row)
    assert row.cost == pytest.approx(.4)
    identity = row.id
    await db.delete(row)
    await db.flush()
    ledger = await db.get(LLMCallCost, identity, populate_existing=True)
    assert ledger.call_id is None and ledger.cost == pytest.approx(.4)
    assert ledger.status == "cancelled"
    assert "Synthetic private prompt" not in str(ledger.evidence)
