from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.llm.cost_report import correlated_cost_evidence
from app.llm.dbadmin import register_dbadmin
from app.llm.models import LLMCall
from core.database import engine, get_db_session
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, SchemaTransitionSet, orchestrator


@pytest.mark.asyncio
async def test_retiring_the_cost_register_preserves_paired_and_orphaned_costs(db):
    await db.execute(text("""
        CREATE TABLE public.llm_call_costs (
            id uuid PRIMARY KEY, call_id uuid REFERENCES public.llm_calls(id) ON DELETE SET NULL,
            task_id uuid, agent_id integer, conversation_round_id uuid, correlation_ref varchar(300),
            purpose varchar(120), status varchar(30), started_at timestamptz, completed_at timestamptz,
            cost double precision, inference_cost double precision, cost_estimated boolean,
            is_subscription boolean, evidence jsonb
        )
    """))
    paired, orphan = uuid4(), uuid4()
    db.add(LLMCall(id=paired, cost=.1, usage={"token_detail": 41}, raw_response="Captured response",
                   correlation_ref="test://cost-migration/paired", status="completed"))
    await db.flush()
    await db.execute(text("""
        INSERT INTO public.llm_call_costs (
            id, call_id, correlation_ref, purpose, status, started_at, completed_at,
            cost, inference_cost, cost_estimated, is_subscription, evidence
        ) VALUES
            (:paired, :paired, 'test://cost-migration/paired', NULL, 'completed', now(), now(),
                 .25, .25, false, false, '{"_galaris_cost":{"version":"llm-cost/v1","source":"provider"}}'),
            (:orphan, NULL, 'test://cost-migration/orphan', 'agent.exec', 'error', now(), now(),
                 .5, .5, false, false, '{"_galaris_cost":{"version":"llm-cost/v1","source":"provider"}}')
    """), {"paired": paired, "orphan": orphan})

    registry = DbAdminRegistry()
    register_dbadmin(registry)
    action = next(action for action in registry.actions if action.key == "app.llm.consolidate_call_costs")
    delta = SchemaTransitionSet(removed_tables=frozenset({"llm_call_costs"}))
    assert action.predicate(delta) and not action.predicate(SchemaTransitionSet())
    assert not await action.postcondition(db, delta)
    await action.handler(db, delta)
    assert await action.postcondition(db, delta)
    await action.handler(db, delta)
    assert await action.postcondition(db, delta)
    await db.execute(text("DROP TABLE public.llm_call_costs"))
    assert await action.postcondition(db, delta)

    rows = (await db.scalars(select(LLMCall).where(LLMCall.id.in_((paired, orphan)))
                             .execution_options(include_historized=True, populate_existing=True))).all()
    found = {row.id: row for row in rows}
    assert found[paired].raw_response == "Captured response" and found[paired].usage["token_detail"] == 41
    assert found[orphan].deleted_at is not None and found[orphan].status == "error"
    costs = {row.call_id: row.cost for row in await correlated_cost_evidence("test://cost-migration/")}
    assert costs == {paired: .25, orphan: .5}


@pytest.mark.asyncio
async def test_upgrade_converges_from_the_cost_register_and_no_history_marker():
    """Exercise Atlas expansion, transfer, and contraction on the isolated database."""
    registry = DbAdminRegistry()
    identity = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE public.llm_calls DROP COLUMN deleted_at"))
            await connection.execute(text("""
                CREATE TABLE public.llm_call_costs (
                    id uuid PRIMARY KEY, call_id uuid REFERENCES public.llm_calls(id) ON DELETE SET NULL,
                    task_id uuid, agent_id integer, conversation_round_id uuid, correlation_ref varchar(300),
                    purpose varchar(120), status varchar(30), started_at timestamptz, completed_at timestamptz,
                    cost double precision, inference_cost double precision, cost_estimated boolean,
                    is_subscription boolean, evidence jsonb
                )
            """))
            await connection.execute(text("""
                INSERT INTO public.llm_call_costs (
                    id, status, started_at, completed_at, cost, inference_cost, cost_estimated,
                    is_subscription, evidence, correlation_ref
                ) VALUES (:id, 'error', now(), now(), .5, .5, false, false,
                    '{"_galaris_cost":{"version":"llm-cost/v1","source":"provider"}}', 'test://legacy-cost/orphan')
            """), {"id": identity})
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with get_db_session() as session:
            assert await session.scalar(text("SELECT to_regclass('public.llm_call_costs')")) is None
            assert await session.scalar(select(LLMCall.id).where(LLMCall.id == identity)) is None
            costs = await correlated_cost_evidence("test://legacy-cost/")
            assert len(costs) == 1 and costs[0].call_id == identity and costs[0].cost == .5
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS public.llm_call_costs"))
            await connection.execute(text("ALTER TABLE public.llm_calls ADD COLUMN IF NOT EXISTS deleted_at timestamptz"))
            await connection.execute(text("DELETE FROM public.llm_calls WHERE id = :id"), {"id": identity})
            await connection.execute(text("DELETE FROM public.dbadmin_actions WHERE key = 'app.llm.consolidate_call_costs'"))
