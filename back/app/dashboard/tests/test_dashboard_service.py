from datetime import datetime, timezone

import pytest

from app.agent.models import Agent, Title
from app.llm.models import LLMCall
from app.llm.provider_models import LLM, LLMProvider
from app.task.models import Task, TaskStatus

from ..dashboard_service import get_dashboard, month_bounds


def test_month_bounds_normalizes_calendar_interval() -> None:
    month, start, end = month_bounds("2026-12", timezone_name="Europe/Paris")

    assert month == "2026-12"
    assert start == datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)


def test_month_bounds_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        month_bounds("2026-13")


@pytest.mark.asyncio
async def test_dashboard_aggregates_month_by_model_and_agent(db, monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    title = Title(label="Analyste", gender="F")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code="dashboard-agent",
        first_name="Ada",
        last_name="Lovelace",
        job_title="Analyste IA",
        avatar=b"fake-avatar-data",
    )
    db.add(agent)
    await db.flush()
    provider = LLMProvider(
        name="OpenAI — ChatGPT",
        catalog_code=None,
        provider_type="openai_compatible",
        base_url="https://chatgpt.test",
        configuration={},
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    subscribed_llm = LLM(
        llm_provider_id=provider.id,
        code="gpt-test",
        llm_name="gpt-test",
        label="gpt-test",
        resource_type="model",
        primary_capability="chat",
        service_capabilities=["chat"],
        pricing={},
        is_subscription=True,
    )
    db.add(subscribed_llm)
    await db.flush()

    success_task = Task(
        label="Successful task",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        created_at=datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc),
    )
    failed_task = Task(
        label="Failed task",
        status=TaskStatus.ERROR,
        agent_id=agent.id,
        created_at=datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc),
    )
    db.add_all([success_task, failed_task])
    await db.flush()

    current_calls = [
        LLMCall(
            task_id=success_task.id,
            agent_id=None,
            llm_id=subscribed_llm.id,
            provider_name="OpenAI",
            requested_model="gpt-test",
            effective_model="gpt-test",
            status="completed",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost=0.15,
            inference_cost=0.15,
            is_subscription=False,
            duration=2.0,
            started_at=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 7, 3, 10, 0, 2, tzinfo=timezone.utc),
        ),
        LLMCall(
            task_id=failed_task.id,
            agent_id=agent.id,
            llm_id=subscribed_llm.id,
            provider_name="OpenAI",
            requested_model="gpt-test",
            effective_model="gpt-test",
            status="error",
            error="provider unavailable",
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
            cost=0.02,
            inference_cost=0.02,
            duration=1.0,
            started_at=datetime(2026, 7, 3, 11, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 7, 3, 11, 0, 1, tzinfo=timezone.utc),
        ),
        # 22:30 UTC still belongs to the next calendar day in Paris during summer.
        LLMCall(
            task_id=success_task.id,
            agent_id=agent.id,
            provider_name="OpenAI",
            requested_model="midnight-model",
            effective_model="midnight-model",
            status="completed",
            input_tokens=8,
            output_tokens=2,
            total_tokens=10,
            cost=0.01,
            inference_cost=0.01,
            duration=0.5,
            started_at=datetime(2026, 7, 13, 22, 30, tzinfo=timezone.utc),
        ),
        LLMCall(
            agent_id=agent.id,
            llm_id=subscribed_llm.id,
            provider_name="OpenAI",
            requested_model="gpt-test",
            effective_model="gpt-test",
            status="completed",
            total_tokens=40,
            cost=0.04,
            inference_cost=0.04,
            duration=1.5,
            started_at=datetime(2026, 6, 28, 10, 0, tzinfo=timezone.utc),
        ),
    ]
    db.add_all(current_calls)
    await db.flush()

    dashboard = await get_dashboard("2026-07")

    assert dashboard.totals.tasks == 2
    assert dashboard.totals.successful_tasks == 1
    assert dashboard.totals.task_errors == 1
    assert dashboard.totals.llm_calls == 3
    assert dashboard.totals.llm_errors == 1
    assert dashboard.totals.incidents == 2
    assert dashboard.totals.tokens == 185
    assert dashboard.totals.cost == pytest.approx(0.18)
    assert dashboard.totals.inference_cost == pytest.approx(0.18)
    assert dashboard.previous_totals.llm_calls == 1
    assert dashboard.previous_totals.tokens == 40
    assert dashboard.previous_totals.inference_cost == pytest.approx(0.04)

    assert len(dashboard.daily_usage) == 2
    gpt_usage = next(item for item in dashboard.daily_usage if item.llm_label == "gpt-test")
    assert gpt_usage.date.isoformat() == "2026-07-03"
    assert gpt_usage.calls == 2
    assert gpt_usage.errors == 1
    assert gpt_usage.cost == pytest.approx(0.17)
    assert gpt_usage.inference_cost == pytest.approx(0.17)
    midnight_usage = next(
        item for item in dashboard.daily_usage if item.llm_label == "midnight-model"
    )
    assert midnight_usage.date.isoformat() == "2026-07-14"

    agent_usage = next(item for item in dashboard.agents if item.agent_id == agent.id)
    assert agent_usage.has_avatar is True
    assert agent_usage.tasks == 2
    assert agent_usage.successful_tasks == 1
    assert agent_usage.llm_calls == 3
    assert agent_usage.llm_errors == 1
    assert agent_usage.tokens == 185
    assert agent_usage.cost == pytest.approx(0.18)
    assert agent_usage.task_success_rate == 50.0
    assert "2026-07" in dashboard.available_months
    assert "2026-06" in dashboard.available_months

    subscribed_llm.is_subscription = False
    await db.commit()
    dashboard_without_subscription = await get_dashboard("2026-07")
    assert dashboard_without_subscription.totals.cost == pytest.approx(0.18)
    assert dashboard_without_subscription.previous_totals.cost == dashboard.previous_totals.cost
    assert dashboard_without_subscription.agents == dashboard.agents
    assert dashboard_without_subscription.daily_usage == dashboard.daily_usage
    assert current_calls[0].cost == pytest.approx(0.15)
    assert current_calls[0].is_subscription is False


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["all", "first", "empty"])
async def test_dashboard_preserves_scoped_calendar_totals_with_bounded_queries(db, monkeypatch, scope):
    """Two-month aggregation keeps calendar, soft deletion and legacy ownership semantics."""
    from sqlalchemy import event

    monkeypatch.setenv("TZ", "Europe/Paris")
    title = Title(label="Dashboard scope", gender="F")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"dashboard-scope-{index}",
                    first_name=f"Agent {index}", last_name="Scope") for index in range(3)]
    db.add_all(agents)
    await db.flush()
    # January in Paris starts an hour before January in UTC.
    boundary = datetime(2025, 12, 31, 23, tzinfo=timezone.utc)
    before = datetime(2025, 12, 31, 22, 59, tzinfo=timezone.utc)
    excluded_end = datetime(2026, 1, 31, 23, tzinfo=timezone.utc)
    previous_task = Task(label="Previous", agent_id=agents[0].id, created_at=before, status=TaskStatus.ERROR)
    current_task = Task(label="Current", agent_id=agents[0].id, created_at=boundary, status=TaskStatus.SUCCESS)
    deleted_task = Task(label="Deleted", agent_id=agents[0].id,
                        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc), deleted_at=boundary)
    db.add_all([previous_task, current_task, deleted_task,
                Task(label="Other agent", agent_id=agents[1].id, created_at=boundary, status=TaskStatus.SUCCESS)])
    await db.flush()
    db.add_all([
        LLMCall(task_id=previous_task.id, started_at=before, status="error", cost=1,
                inference_cost=2, total_tokens=10, duration=4),
        LLMCall(task_id=current_task.id, started_at=boundary, status="completed", cost=2,
                inference_cost=3, total_tokens=20, duration=6),
        LLMCall(agent_id=agents[0].id, started_at=boundary, status="running", cost=3,
                inference_cost=4, total_tokens=30, duration=999),
        LLMCall(agent_id=agents[1].id, started_at=boundary, status="completed", cost=4,
                inference_cost=5, total_tokens=40, duration=8),
        LLMCall(started_at=boundary, status="completed", cost=5,
                inference_cost=6, total_tokens=50, duration=10),
        LLMCall(agent_id=agents[1].id, started_at=datetime(2021, 6, 1, tzinfo=timezone.utc)),
        LLMCall(agent_id=agents[0].id, started_at=excluded_end, status="completed", cost=1000),
    ])
    await db.flush()
    agent_ids = None if scope == "all" else ([agents[0].id] if scope == "first" else [])
    connection = await db.connection()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        dashboard = await get_dashboard("2026-01", agent_ids=agent_ids)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert len(statements) <= 5, "one dashboard read must not repeat monthly aggregations"
    expected = {"all": (2, 4, 140, 14), "first": (1, 2, 50, 5), "empty": (0, 0, 0, 0)}[scope]
    assert (dashboard.totals.tasks, dashboard.totals.llm_calls,
            dashboard.totals.tokens, dashboard.totals.cost) == expected
    assert dashboard.totals.average_llm_duration == (8 if scope == "all" else 6 if scope == "first" else 0)
    assert dashboard.previous_totals.tasks == (0 if scope == "empty" else 1)
    assert dashboard.previous_totals.cost == (0 if scope == "empty" else 1)
    assert "2020-01" not in dashboard.available_months
    assert ("2021-06" in dashboard.available_months) == (scope == "all")
    assert sum(point.cost for point in dashboard.daily_usage) == expected[3]
    assert len(dashboard.agents) == {"all": 3, "first": 1, "empty": 0}[scope]
    if scope != "empty":
        first = next(item for item in dashboard.agents if item.agent_id == agents[0].id)
        assert (first.tasks, first.llm_calls, first.cost, first.average_llm_duration) == (1, 2, 5, 6)


@pytest.mark.asyncio
async def test_dashboard_empty_months_have_zero_totals(db, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Paris")
    dashboard = await get_dashboard("2000-01")
    assert dashboard.totals == dashboard.previous_totals
    assert dashboard.totals.tasks == dashboard.totals.llm_calls == 0
    assert dashboard.daily_usage == []
    assert "2000-01" in dashboard.available_months
