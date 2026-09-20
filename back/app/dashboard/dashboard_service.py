"""Database aggregations backing the monthly operational dashboard."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import Date, cast, func, select

from app.agent.models import Agent
from app.llm.models import LLMCall
from app.llm.provider_models import LLM, LLMProvider
from app.task.models import Task, TaskStatus
from core.database import get_db
from core.util import local_timezone_name, month_bounds

from .schemas import AgentUsage, DailyLlmUsage, DashboardResponse, DashboardTotals


def _previous_month(
    month: str,
    *,
    timezone_name: str,
) -> tuple[str, datetime, datetime]:
    year, month_number = (int(part) for part in month.split("-"))
    if month_number == 1:
        previous_month = f"{year - 1:04d}-12"
    else:
        previous_month = f"{year:04d}-{month_number - 1:02d}"
    return month_bounds(
        previous_month,
        timezone_name=timezone_name,
    )


async def _totals(
    previous_start: datetime,
    start: datetime,
    end: datetime,
    *,
    agent_ids: Collection[int] | None = None,
) -> tuple[DashboardTotals, DashboardTotals]:
    """Aggregate both adjacent months in one pass per source table."""
    db = get_db()
    task_period = (Task.created_at >= start).label("current_month")
    task_query = (
        select(
            task_period,
            func.count(Task.id).label("tasks"),
            func.count(Task.id).filter(Task.status == TaskStatus.SUCCESS).label("successes"),
            func.count(Task.id).filter(Task.status == TaskStatus.ERROR).label("errors"),
        )
        .where(Task.created_at >= previous_start, Task.created_at < end)
        .group_by(task_period)
    )
    if agent_ids is not None:
        task_query = task_query.where(Task.agent_id.in_(agent_ids))
    task_result = await db.execute(task_query)
    task_rows = {row.current_month: row for row in task_result}

    call_agent_id = func.coalesce(LLMCall.agent_id, Task.agent_id)
    call_period = (LLMCall.started_at >= start).label("current_month")
    llm_query = (
        select(
            call_period,
            func.count(LLMCall.id).label("calls"),
            func.count(LLMCall.id).filter(
                (LLMCall.status == "error") | LLMCall.error.is_not(None)
            ).label("errors"),
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
            func.coalesce(
                func.sum(LLMCall.cost),
                0.0,
            ).label("cost"),
            func.coalesce(func.sum(LLMCall.inference_cost), 0.0).label("inference_cost"),
            func.coalesce(
                func.avg(LLMCall.duration).filter(LLMCall.status != "running"),
                0.0,
            ).label("duration"),
        )
        .select_from(LLMCall)
        .where(LLMCall.started_at >= previous_start, LLMCall.started_at < end)
        .group_by(call_period)
    )
    if agent_ids is not None:
        llm_query = llm_query.outerjoin(Task, Task.id == LLMCall.task_id).where(
            call_agent_id.in_(agent_ids)
        )
    llm_result = await db.execute(llm_query)
    call_rows = {row.current_month: row for row in llm_result}
    totals: list[DashboardTotals] = []
    for current in (True, False):
        tasks = task_rows.get(current)
        calls = call_rows.get(current)
        task_count = int(tasks.tasks) if tasks else 0
        successful_count = int(tasks.successes) if tasks else 0
        task_error_count = int(tasks.errors) if tasks else 0
        call_count = int(calls.calls) if calls else 0
        llm_error_count = int(calls.errors) if calls else 0
        totals.append(
            DashboardTotals(
                tasks=task_count,
                successful_tasks=successful_count,
                task_errors=task_error_count,
                llm_calls=call_count,
                llm_errors=llm_error_count,
                incidents=task_error_count + llm_error_count,
                tokens=int(calls.tokens) if calls else 0,
                cost=float(calls.cost) if calls else 0.0,
                inference_cost=float(calls.inference_cost) if calls else 0.0,
                average_llm_duration=float(calls.duration) if calls else 0.0,
                task_success_rate=(successful_count / task_count * 100.0) if task_count else 0.0,
                llm_success_rate=((call_count - llm_error_count) / call_count * 100.0)
                if call_count else 0.0,
            )
        )
    return totals[0], totals[1]


async def _daily_usage(
    start: datetime,
    end: datetime,
    *,
    timezone_name: str,
    agent_ids: Collection[int] | None = None,
) -> list[DailyLlmUsage]:
    db = get_db()
    day = cast(func.timezone(timezone_name, LLMCall.started_at), Date).label("usage_day")
    label = func.coalesce(
        func.nullif(LLM.label, ""),
        func.nullif(LLMCall.effective_model, ""),
        func.nullif(LLMCall.requested_model, ""),
        "Unknown model",
    ).label("llm_label")
    provider = func.coalesce(
        func.nullif(LLMProvider.name, ""),
        func.nullif(LLMCall.provider_name, ""),
        "",
    ).label("provider_name")
    query = (
        select(
            day,
            LLMCall.llm_id,
            label,
            provider,
            func.count(LLMCall.id).label("calls"),
            func.count(LLMCall.id)
            .filter((LLMCall.status == "error") | LLMCall.error.is_not(None))
            .label("errors"),
            func.coalesce(func.sum(LLMCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMCall.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
            func.coalesce(
                func.sum(LLMCall.cost),
                0.0,
            ).label("cost"),
            func.coalesce(func.sum(LLMCall.inference_cost), 0.0).label(
                "inference_cost"
            ),
        )
        .select_from(LLMCall)
        .outerjoin(LLM, LLM.id == LLMCall.llm_id)
        .outerjoin(LLMProvider, LLMProvider.id == LLM.llm_provider_id)
        .where(LLMCall.started_at >= start, LLMCall.started_at < end)
        .group_by(day, LLMCall.llm_id, label, provider)
        .order_by(day, label)
    )
    if agent_ids is not None:
        query = query.outerjoin(Task, Task.id == LLMCall.task_id).where(
            func.coalesce(LLMCall.agent_id, Task.agent_id).in_(agent_ids)
        )
    result = await db.execute(query)

    points: list[DailyLlmUsage] = []
    for row in result:
        llm_label = str(row.llm_label)
        provider_name = str(row.provider_name or "")
        llm_key = (
            f"llm:{row.llm_id}"
            if row.llm_id is not None
            else f"model:{provider_name}:{llm_label}"
        )
        points.append(
            DailyLlmUsage(
                date=row.usage_day,
                llm_key=llm_key,
                llm_label=llm_label,
                provider_name=provider_name,
                calls=int(row.calls or 0),
                errors=int(row.errors or 0),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                tokens=int(row.tokens or 0),
                cost=float(row.cost or 0.0),
                inference_cost=float(row.inference_cost or 0.0),
            )
        )
    return points


async def _agent_usage(
    start: datetime,
    end: datetime,
    *,
    agent_ids: Collection[int] | None = None,
) -> list[AgentUsage]:
    db = get_db()
    task_stats = (
        select(
            Task.agent_id.label("agent_id"),
            func.count(Task.id).label("tasks"),
            func.count(Task.id)
            .filter(Task.status == TaskStatus.SUCCESS)
            .label("successful_tasks"),
            func.count(Task.id).filter(Task.status == TaskStatus.ERROR).label("task_errors"),
        )
        .where(
            Task.agent_id.is_not(None),
            Task.created_at >= start,
            Task.created_at < end,
        )
        .group_by(Task.agent_id)
    )
    if agent_ids is not None:
        task_stats = task_stats.where(Task.agent_id.in_(agent_ids))
    task_stats = task_stats.subquery()

    call_agent_id = func.coalesce(LLMCall.agent_id, Task.agent_id).label("agent_id")
    call_stats = (
        select(
            call_agent_id,
            func.count(LLMCall.id).label("llm_calls"),
            func.count(LLMCall.id)
            .filter((LLMCall.status == "error") | LLMCall.error.is_not(None))
            .label("llm_errors"),
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label("tokens"),
            func.coalesce(
                func.sum(LLMCall.cost),
                0.0,
            ).label("cost"),
            func.coalesce(
                func.avg(LLMCall.duration).filter(LLMCall.status != "running"),
                0.0,
            ).label("average_llm_duration"),
        )
        .select_from(LLMCall)
        .outerjoin(Task, Task.id == LLMCall.task_id)
        .where(
            call_agent_id.is_not(None),
            LLMCall.started_at >= start,
            LLMCall.started_at < end,
        )
        .group_by(call_agent_id)
    )
    if agent_ids is not None:
        call_stats = call_stats.where(call_agent_id.in_(agent_ids))
    call_stats = call_stats.subquery()

    query = (
        select(
            Agent.id,
            Agent.first_name,
            Agent.last_name,
            Agent.job_title,
            Agent.avatar.is_not(None).label("has_avatar"),
            func.coalesce(task_stats.c.tasks, 0).label("tasks"),
            func.coalesce(task_stats.c.successful_tasks, 0).label("successful_tasks"),
            func.coalesce(task_stats.c.task_errors, 0).label("task_errors"),
            func.coalesce(call_stats.c.llm_calls, 0).label("llm_calls"),
            func.coalesce(call_stats.c.llm_errors, 0).label("llm_errors"),
            func.coalesce(call_stats.c.tokens, 0).label("tokens"),
            func.coalesce(call_stats.c.cost, 0.0).label("cost"),
            func.coalesce(call_stats.c.average_llm_duration, 0.0).label(
                "average_llm_duration"
            ),
        )
        .outerjoin(task_stats, task_stats.c.agent_id == Agent.id)
        .outerjoin(call_stats, call_stats.c.agent_id == Agent.id)
        .order_by(
            func.coalesce(task_stats.c.tasks, 0).desc(),
            func.coalesce(call_stats.c.llm_calls, 0).desc(),
            Agent.first_name,
            Agent.last_name,
        )
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    result = await db.execute(query)

    agents: list[AgentUsage] = []
    for row in result:
        tasks = int(row.tasks or 0)
        successful_tasks = int(row.successful_tasks or 0)
        task_errors = int(row.task_errors or 0)
        llm_errors = int(row.llm_errors or 0)
        agents.append(
            AgentUsage(
                agent_id=row.id,
                agent_name=f"{row.first_name} {row.last_name}".strip(),
                job_title=row.job_title,
                has_avatar=bool(row.has_avatar),
                tasks=tasks,
                successful_tasks=successful_tasks,
                task_errors=task_errors,
                llm_calls=int(row.llm_calls or 0),
                llm_errors=llm_errors,
                incidents=task_errors + llm_errors,
                tokens=int(row.tokens or 0),
                cost=float(row.cost or 0.0),
                average_llm_duration=float(row.average_llm_duration or 0.0),
                task_success_rate=(successful_tasks / tasks * 100.0) if tasks else 0.0,
            )
        )
    return agents


async def _available_months(
    selected_month: str,
    *,
    timezone_name: str,
    agent_ids: Collection[int] | None = None,
) -> list[str]:
    db = get_db()
    task_month = cast(
        func.date_trunc("month", func.timezone(timezone_name, Task.created_at)),
        Date,
    ).label("month")
    task_month_query = select(task_month)
    if agent_ids is not None:
        task_month_query = task_month_query.where(Task.agent_id.in_(agent_ids))
    call_month = cast(
        func.date_trunc("month", func.timezone(timezone_name, LLMCall.started_at)),
        Date,
    ).label("month")
    call_month_query = (
        select(call_month)
        .select_from(LLMCall)
    )
    if agent_ids is not None:
        call_month_query = call_month_query.outerjoin(Task, Task.id == LLMCall.task_id).where(
            func.coalesce(LLMCall.agent_id, Task.agent_id).in_(agent_ids)
        )
    month_rows = await db.execute(task_month_query.union(call_month_query))
    months = {
        f"{value.year:04d}-{value.month:02d}"
        for value in month_rows.scalars()
    }
    months.add(selected_month)
    current_month, _, _ = month_bounds(None, timezone_name=timezone_name)
    months.add(current_month)
    return sorted(months, reverse=True)


async def get_dashboard(
    month: str | None = None,
    *,
    agent_ids: Collection[int] | None = None,
) -> DashboardResponse:
    """Build the complete monthly dashboard response."""

    timezone_name = local_timezone_name()
    normalized, start, end = month_bounds(month, timezone_name=timezone_name)
    _, previous_start, _ = _previous_month(
        normalized,
        timezone_name=timezone_name,
    )
    totals, previous_totals = await _totals(
        previous_start,
        start,
        end,
        agent_ids=agent_ids,
    )
    daily_usage = await _daily_usage(
        start,
        end,
        timezone_name=timezone_name,
        agent_ids=agent_ids,
    )
    agents = await _agent_usage(start, end, agent_ids=agent_ids)
    available_months = await _available_months(
        normalized,
        timezone_name=timezone_name,
        agent_ids=agent_ids,
    )
    return DashboardResponse(
        month=normalized,
        available_months=available_months,
        totals=totals,
        previous_totals=previous_totals,
        daily_usage=daily_usage,
        agents=agents,
    )
