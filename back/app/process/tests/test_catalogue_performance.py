"""Interactive process lists must not spend seconds compiling resource ACLs."""

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import InvalidRequestError

from app.agent import AgentManagementScope
from app.process import catalogue, native_definitions, native_runs, process_service
from app.process.models import ProcessNodeRun, ProcessRun
from tests.sql_reads import measured_reads
from .test_native_bpmn import committed_native as committed_native, graph
from .test_lifecycle_workflows import workflow as workflow


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [10, 50, 500])
@pytest.mark.parametrize("view", ["scoped", "general"])
async def test_scoped_run_pages_bound_reads_and_preserve_public_json_without_private_payloads(db, workflow, count, view, monkeypatch):
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    private = "Synthetic internal state. " * 300
    rows = [ProcessRun(process_id=workflow.definition.id, launcher_agent_id=workflow.owner.id,
        engine_code="fake", correlation_id=f"synthetic-{uuid4().hex}", callback_token="synthetic",
        status="success", created_at=origin + timedelta(seconds=index),
        input={"index": index, "enabled": False, "token": "synthetic business input"},
        output={"password": "synthetic business output", "values": [0, False, None, "été"]},
        engine_metadata={"source": "synthetic", "index": index},
        raw_snapshot={"trace": private}, analysis={"details": private}, data={"internal": private},
        execution_state={"private": private}, launch_snapshot={"process_label": "Synthetic snapshot",
            "workflow_id": "synthetic-saved", "definition": {"source": private}}) for index in range(count)]
    db.add_all(rows)
    db.add(ProcessRun(process_id=workflow.definition.id, launcher_agent_id=workflow.other.id,
        engine_code="fake", correlation_id=f"synthetic-hidden-{uuid4().hex}", callback_token="synthetic",
        status="success", input={}, output={"hidden": True}))
    await db.commit()
    identifiers = [row.id for row in rows]
    agent_code = workflow.owner.code
    owner_id, process_id = workflow.owner.id, workflow.definition.id
    if view == "general":
        from unittest.mock import AsyncMock
        from app.process import router
        monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=AgentManagementScope(
            workflow.owner.user_id, frozenset({owner_id}))))
    db.expunge_all()
    async with measured_reads(db, f"process-summary-page-{count}") as reads:
        if view == "general":
            page = await router.read_runs(agent_id=None, process_id=process_id, workflow_id=None,
                run_status=None, active=None, search=None, created_after=None, created_before=None,
                sort_by="created_at", descending=True, page=1, page_size=count)
            items, total = page.items, page.total
        else:
            items, total = await process_service.list_run_summaries_page_for_scope(identifiers, [], page_size=count)
    assert total == count and [item.id for item in items] == list(reversed(identifiers))
    assert len(reads) <= 3, "A run page must not refresh and resolve references for each row"
    assert not {"raw_snapshot", "analysis", "data", "execution_state", "launch_snapshot"} & reads.result_columns
    for index, item in enumerate(reversed(items)):
        assert item.input == {"index": index, "enabled": False, "token": "synthetic business input"}
        assert item.output == {"password": "synthetic business output", "values": [0, False, None, "été"]}
        assert item.engine_metadata == {"source": "synthetic", "index": index}
        assert item.process_label == workflow.definition.label and item.workflow_id == workflow.definition.engine_process_id
        assert item.launcher_agent_code == agent_code and item.fresh and item.summary
    stored = await db.get(ProcessRun, identifiers[0])
    assert stored.raw_snapshot == {"trace": private} and stored.analysis == {"details": private}
    assert stored.data == {"internal": private} and stored.execution_state == {"private": private}
    assert stored.launch_snapshot["definition"] == {"source": private}
    # Full consumers retain their default, including after a summary in this session.
    db.expunge_all()
    selected, _ = await process_service.paginate_runs(agent_id=owner_id, process_id=process_id,
        page_size=count, summary_only=True)
    detail = await process_service.get_run_detail(selected[0].id, refresh_if_stale=True)
    assert detail is not None and detail.output == {"password": "synthetic business output", "values": [0, False, None, "été"]}
    full, total = await process_service.paginate_runs(agent_id=owner_id, process_id=process_id, page_size=count)
    assert total == count and full[0].execution_state == {"private": private}
    assert selected[0] is full[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["terminal", "definition-archive", "retirement", "deletion"])
async def test_preselected_run_summaries_match_fresh_detail_after_late_changes(db, workflow, change):
    from app.process.models import ProcessDefinition

    run = ProcessRun(process_id=workflow.definition.id, launcher_agent_id=workflow.owner.id,
        engine_code="fake", correlation_id=f"synthetic-{uuid4().hex}", callback_token="synthetic", status="running",
        input={"preserve": False}, launch_snapshot={"workflow_id": "synthetic-saved", "process_label": "Synthetic saved label"})
    db.add(run)
    await db.commit()
    identity = run.id
    selected = list(await db.scalars(select(ProcessRun.id).where(ProcessRun.id == identity)))
    if change == "deletion":
        await db.execute(delete(ProcessRun).where(ProcessRun.id == identity).execution_options(synchronize_session=False))
        with pytest.raises(InvalidRequestError):
            await process_service._run_read(run)
        with pytest.raises(InvalidRequestError):
            await process_service._run_reads(selected)
        return
    if change == "terminal":
        await db.execute(update(ProcessRun).where(ProcessRun.id == identity).values(status="success",
            output={"result": [0, False, None]}).execution_options(synchronize_session=False))
    elif change == "definition-archive":
        definition = await db.get(ProcessDefinition, run.process_id)
        definition.soft_delete()
        await db.flush()
    else:
        await db.execute(update(ProcessRun).where(ProcessRun.id == identity).values(
            deleted_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
    expected = (await process_service._run_read(run)).model_dump(mode="json")
    actual = await process_service._run_reads(selected)
    assert len(actual) == 1 and actual[0].model_dump(mode="json") == expected


@pytest.mark.asyncio
async def test_run_summary_reopens_with_an_independently_committed_result(inference_db, committed_database, committed_native):
    db = inference_db
    owner, _ = committed_native
    definition = await native_definitions.create(actor_agent_id=owner.id, title="Synthetic fresh run", graph=graph())
    run = ProcessRun(process_id=definition.id, launcher_agent_id=owner.id, engine_code="galaris",
        correlation_id=uuid4().hex, callback_token="synthetic", status="running", input={},
        data={"preserved": "synthetic process data"})
    db.add(run)
    await db.commit()
    identity = run.id
    assert (await process_service.list_run_summaries_page_for_scope([identity], []))[0][0].status == "running"
    async with committed_database() as writer:
        await writer.execute(update(ProcessRun).where(ProcessRun.id == identity).values(status="success",
            output={"result": [0, False, None, "synthetic final result"]}))
        await writer.commit()
    reopened, total = await process_service.list_run_summaries_page_for_scope([identity], [])
    assert total == 1 and reopened[0].status == "success"
    assert reopened[0].output == {"result": [0, False, None, "synthetic final result"]}
    await db.refresh(run)
    assert run.status == "success" and run.data == {"preserved": "synthetic process data"}


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
    for query in (native_runs.list_runs, native_definitions.page_for, catalogue.page_for):
        await db.execute(text("SET LOCAL jit = on"))
        await db.execute(text("SET LOCAL jit_above_cost = 0"))
        await db.execute(text("SET LOCAL jit_inline_above_cost = 0"))
        await db.execute(text("SET LOCAL jit_optimize_above_cost = 0"))
        started = time.perf_counter()
        page = await query(scope)
        elapsed = time.perf_counter() - started
        assert (page.total if query is catalogue.page_for else page["total"]) == (5 if query is native_runs.list_runs else 1)
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
