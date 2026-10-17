"""Interactive process lists must not spend seconds compiling resource ACLs."""

import time
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.agent import AgentManagementScope
from app.process import native_definitions, native_runs, process_service
from app.process.models import ProcessNodeRun, ProcessRun
from .test_native_bpmn import committed_native as committed_native, graph


@pytest.mark.asyncio
async def test_process_catalogues_bound_planner_work_and_restore_transaction_defaults(inference_db, committed_native):
    # Real transactions are required: releasing the usual test savepoint does
    # not restore SET LOCAL settings until its outer transaction ends.
    db = inference_db
    owner, _ = committed_native
    definition = await native_definitions.create(actor_agent_id=owner.id,
        title="Synthetic interactive catalogue", graph=graph())
    assert owner.user_id is not None
    for _ in range(5):
        db.add(ProcessRun(process_id=definition.id, launcher_agent_id=owner.id,
            requester_user_id=owner.user_id, engine_code="galaris", correlation_id=str(uuid4()),
            callback_token="synthetic", status="success", input={}, output={"result": "Synthetic result"},
            launch_snapshot={"process_label": "Synthetic interactive catalogue", "participant_agents": [owner.id]}))
    await db.commit()
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=None)
    original = await db.scalar(text("SHOW jit"))
    # Force the PostgreSQL cost threshold, independently of a test database's statistics.
    # This reproduces the expensive compilation of the real, fully composed ACL query.
    for query in (native_runs.list_runs, native_definitions.page_for):
        await db.execute(text("SET LOCAL jit = on"))
        await db.execute(text("SET LOCAL jit_above_cost = 0"))
        await db.execute(text("SET LOCAL jit_inline_above_cost = 0"))
        await db.execute(text("SET LOCAL jit_optimize_above_cost = 0"))
        started = time.perf_counter()
        page = await query(scope)
        elapsed = time.perf_counter() - started
        assert page["total"] == (5 if query is native_runs.list_runs else 1)
        assert elapsed < 2, "A small interactive catalogue must not compile its resource ACLs"
        await db.commit()
        assert await db.scalar(text("SHOW jit")) == original
    await db.execute(text("SET LOCAL jit = on"))
    await db.execute(text("SET LOCAL jit_above_cost = 0"))
    started = time.perf_counter()
    rows, total = await process_service.paginate_runs(native_actor=scope)
    assert total == 5 and len(rows) == 5
    assert time.perf_counter() - started < 2
    await db.rollback()
    assert await db.scalar(text("SHOW jit")) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["run", "metrics", "activity", "occurrence"])
async def test_single_run_reads_bound_acl_compilation(inference_db, committed_native, view):
    db = inference_db
    owner, _ = committed_native
    definition = await native_definitions.create(actor_agent_id=owner.id,
        title="Synthetic single-run inspection", graph=graph())
    run = ProcessRun(process_id=definition.id, launcher_agent_id=owner.id,
        requester_user_id=owner.user_id, engine_code="galaris", correlation_id=str(uuid4()),
        callback_token="synthetic", status="success", input={}, output={"result": "Synthetic result"},
        launch_snapshot={"definition": {"graph": graph().model_dump(), "revision": 1}})
    db.add(run)
    await db.flush()
    occurrence = ProcessNodeRun(run_id=run.id, node_key="work", occurrence="work", status="success",
        admission_order=1, context={})
    db.add(occurrence)
    await db.commit()
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    original = await db.scalar(text("SHOW jit"))
    await db.execute(text("SET LOCAL jit = on"))
    await db.execute(text("SET LOCAL jit_above_cost = 0"))
    await db.execute(text("SET LOCAL jit_inline_above_cost = 0"))
    await db.execute(text("SET LOCAL jit_optimize_above_cost = 0"))
    started = time.perf_counter()
    if view == "run":
        result = await native_runs.inspect_run(run.id, scope)
        assert result["total"] == 1 and result["nodes"][0]["id"] == str(occurrence.id)
    elif view == "metrics":
        result = await native_runs.run_metrics(run.id, scope)
        assert result["direct"]["calls"] == 0 and str(occurrence.id) in result["occurrences"]
    elif view == "activity":
        result = await native_runs.activity_occurrences(run.id, "work", scope)
        assert result["total"] == 1 and result["items"][0]["id"] == str(occurrence.id)
    else:
        result = await native_runs.inspect_occurrence(run.id, occurrence.id, scope)
        assert result["id"] == str(occurrence.id) and result["attempts"] == []
    elapsed = time.perf_counter() - started
    print(f"SINGLE_RUN_READ {view}: seconds={elapsed:.6f}")
    assert elapsed < 2, "Inspecting one occurrence must not spend seconds compiling ACLs"
    await db.rollback()
    assert await db.scalar(text("SHOW jit")) == original
