"""Goal-owned agenda passages. Calendar reads never schedule or create Tasks."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select, update
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from app.task import Task

from .models import Goal, GoalCalendarPlan, GoalCycle, GoalOccurrence, GoalStatus
from .schemas import GoalAgendaEvent, GoalAgendaWindow, GoalRecurrence


def next_passage(config: GoalRecurrence, lower: datetime, *, inclusive: bool = True) -> datetime | None:
    """Seek without expanding history; skip invalid month days and nonexistent wall times.

    Repeated autumn wall times use the anchor's fold (normally the first occurrence).
    A daily 09:00 remains 09:00 across daylight saving transitions.
    """
    zone = ZoneInfo(config.timezone)
    anchor = config.start_at.astimezone(zone)
    local = lower.astimezone(zone)
    days = config.interval * (7 if config.frequency == "WEEKLY" else 1)
    months = config.interval * (12 if config.frequency == "YEARLY" else 1)
    if config.frequency in {"DAILY", "WEEKLY"}:
        index = max(0, (local.date() - anchor.date()).days // days)
    else:
        index = max(0, ((local.year - anchor.year) * 12 + local.month - anchor.month) // months)
    # At most a leap-year cycle is needed to find a valid yearly/monthly date.
    for step in range(index, index + 500):
        try:
            if config.frequency in {"DAILY", "WEEKLY"}:
                candidate = anchor + timedelta(days=step * days)
            else:
                ordinal = anchor.year * 12 + anchor.month - 1 + step * months
                year, month = divmod(ordinal, 12)
                month += 1
                if year > 9999:
                    return None
                if anchor.day > monthrange(year, month)[1]:
                    continue
                candidate = anchor.replace(year=year, month=month)
        except (OverflowError, ValueError):
            return None
        candidate = candidate.replace(fold=anchor.fold)
        instant = candidate.astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if instant > lower or inclusive and instant == lower:
            return instant
    return None


def passage_id(plan_id: UUID, at: datetime) -> UUID:
    return uuid5(plan_id, at.astimezone(timezone.utc).isoformat())


async def sync_plan(goal: Goal, *, now: datetime | None = None) -> None:
    """Caller owns the Goal row lock. Preserve every elapsed schedule segment."""
    reference = now or datetime.now(timezone.utc)
    db = get_db()
    plan = await db.scalar(select(GoalCalendarPlan).where(
        GoalCalendarPlan.goal_id == goal.id, GoalCalendarPlan.valid_until.is_(None)))
    active = goal.status == GoalStatus.ACTIVE and goal.deleted_at is None and goal.recurrence is not None
    if plan is not None and active and plan.config == goal.recurrence and plan.title == goal.title:
        return
    if plan is not None:
        plan.valid_until = reference
        if goal.deleted_at is not None or plan.next_at is not None and plan.next_at >= reference:
            plan.next_at = None
        await db.flush()  # Release the unique open-segment key before inserting its successor.
    if active:
        config = GoalRecurrence.model_validate(goal.recurrence)
        db.add(GoalCalendarPlan(id=uuid4(), goal_id=goal.id, title=goal.title,
            config=config.model_dump(mode="json"), valid_from=reference,
            next_at=next_passage(config, reference)))


async def materialize_due(*, now: datetime | None = None, limit: int = 100) -> None:
    """Bounded recovery, including old segments. Always lock Goal before its passages."""
    reference = now or datetime.now(timezone.utc)
    db = get_db()
    ids = list((await db.scalars(select(GoalCalendarPlan.id).where(
        GoalCalendarPlan.next_at <= reference,
        or_(GoalCalendarPlan.valid_until.is_(None), GoalCalendarPlan.next_at < GoalCalendarPlan.valid_until),
    ).order_by(GoalCalendarPlan.next_at).limit(limit))).all())
    remaining = limit
    for identity in ids:
        if remaining <= 0:
            break
        goal_id = await db.scalar(select(GoalCalendarPlan.goal_id).where(GoalCalendarPlan.id == identity))
        goal = await db.scalar(select(Goal).where(Goal.id == goal_id).with_for_update(skip_locked=True))
        if goal is None:
            continue
        plan = await db.get(GoalCalendarPlan, identity, populate_existing=True)
        if plan is None:
            continue
        config = GoalRecurrence.model_validate(plan.config)
        for _ in range(remaining):
            at = plan.next_at
            if at is None or at > reference or plan.valid_until is not None and at >= plan.valid_until:
                break
            expiry = at + timedelta(minutes=config.max_lateness_minutes)
            db.add(GoalOccurrence(id=passage_id(plan.id, at), goal_id=goal.id, plan_id=plan.id,
                scheduled_at=at, title=plan.title, timezone=config.timezone,
                expires_at=expiry, state="skipped" if reference > expiry else "waiting"))
            plan.next_at = next_passage(config, at, inclusive=False)
            next_at, valid_until = plan.next_at, plan.valid_until
            if valid_until is not None and next_at is not None and next_at >= valid_until:
                plan.next_at = None
            remaining -= 1
        await db.commit()
    # Admission takes the Goal lock too. No expiry can race a successful attachment.
    expired_goals = list((await db.scalars(select(GoalOccurrence.goal_id).where(
        GoalOccurrence.state == "waiting", GoalOccurrence.expires_at < reference,
    ).distinct().limit(limit))).all())
    for identity in expired_goals:
        goal = await db.scalar(select(Goal).where(Goal.id == identity).with_for_update(skip_locked=True))
        if goal is None:
            continue
        await db.execute(update(GoalOccurrence).where(GoalOccurrence.goal_id == identity,
            GoalOccurrence.state == "waiting", GoalOccurrence.expires_at < reference).values(state="skipped"))
        await db.commit()


def pending_passage(now: datetime) -> ColumnElement[bool]:
    """SQL eligibility shared by candidate selection and locked admission."""
    return exists().where(GoalOccurrence.goal_id == Goal.id, GoalOccurrence.state == "waiting",
        GoalOccurrence.plan_id.is_not(None), GoalOccurrence.scheduled_at <= now,
        GoalOccurrence.expires_at >= now)


async def attach_cycle(goal: Goal, cycle: GoalCycle, *, now: datetime, manual: bool) -> None:
    """Persist the exact Task/cycle association in the admission transaction."""
    db = get_db()
    occurrence = None
    if not manual:
        occurrence = await db.scalar(select(GoalOccurrence).where(GoalOccurrence.goal_id == goal.id,
            GoalOccurrence.state == "waiting", GoalOccurrence.plan_id.is_not(None),
            GoalOccurrence.scheduled_at <= now, GoalOccurrence.expires_at >= now,
        ).order_by(GoalOccurrence.scheduled_at).limit(1).with_for_update())
        if occurrence is None and goal.recurrence is not None:
            raise RuntimeError("The recurring Goal passage is no longer eligible")
    if occurrence is None:
        occurrence = GoalOccurrence(id=uuid4(), goal_id=goal.id,
            scheduled_at=now if manual else goal.next_cycle_at or now, title=goal.title,
            timezone=GoalRecurrence.model_validate(goal.recurrence).timezone if goal.recurrence else "UTC")
        db.add(occurrence)
    occurrence.cycle_id = cycle.id
    occurrence.state = "linked"


def execution_state(occurrence: GoalOccurrence, cycle: GoalCycle | None, task: Task | None) -> str:
    if occurrence.state != "linked":
        return occurrence.state
    if cycle is None:
        return "unavailable"
    if cycle.status.value == "ERROR":
        return "error"
    if cycle.status.value == "JUDGING":
        return "judging"
    if task is None:
        return "unavailable"
    if task.paused:
        return "paused"
    return {"SUCCESS": "done", "ERROR": "error", "CREATE": "queued", "DISPATCH": "queued"}.get(task.status.value, "running")


def agenda_event(occurrence: GoalOccurrence, cycle: GoalCycle | None = None, task: Task | None = None) -> GoalAgendaEvent:
    return GoalAgendaEvent(id=occurrence.id, goal_id=occurrence.goal_id, title=occurrence.title,
        scheduled_at=occurrence.scheduled_at, timezone=occurrence.timezone, projected=False,
        state=execution_state(occurrence, cycle, task), cycle_id=cycle.id if cycle else None,
        sequence=cycle.sequence if cycle else None,
        task_uri=f"galaris://task/{cycle.task_id}" if cycle and cycle.task_id else None,
        review_task_uri=f"galaris://task/{cycle.review_task_id}" if cycle and cycle.review_task_id else None,
        started_at=cycle.created_at if cycle else None,
        finished_at=cycle.task_finished_at if cycle else None,
        verdict=cycle.verdict if cycle else None, reason=(cycle.reason or cycle.error) if cycle else None)


async def agenda_window(agent_id: int, start: datetime, end: datetime, *,
                        managed_agents: frozenset[int] | None = None,
                        now: datetime | None = None) -> GoalAgendaWindow:
    """Read-only bounded projection; identities survive materialization and edits."""
    if start.tzinfo is None or end.tzinfo is None or not timedelta(0) < end - start <= timedelta(days=32):
        raise ValueError("Goal agenda windows require timezone-aware bounds of at most 32 days")
    reference = now or datetime.now(timezone.utc)
    db = get_db()
    conditions = [Goal.agent_id == agent_id]
    if managed_agents is not None:
        conditions.append(or_(Goal.referrer_agent_id.is_(None), Goal.referrer_agent_id.in_(managed_agents)))
    cap = 500
    query = (select(GoalOccurrence, GoalCycle, Task).join(Goal, Goal.id == GoalOccurrence.goal_id)
        .outerjoin(GoalCycle, GoalCycle.id == GoalOccurrence.cycle_id)
        .outerjoin(Task, Task.id == GoalCycle.task_id)
        .where(*conditions, GoalOccurrence.scheduled_at >= start, GoalOccurrence.scheduled_at < end)
        .order_by(GoalOccurrence.scheduled_at, GoalOccurrence.id).limit(cap + 1))
    rows = (await db.execute(query)).all()
    items = {row[0].id: agenda_event(*row) for row in rows}
    plans = (await db.execute(select(GoalCalendarPlan, Goal.status).join(Goal, Goal.id == GoalCalendarPlan.goal_id)
        .where(*conditions, GoalCalendarPlan.valid_from < end,
            or_(GoalCalendarPlan.valid_until.is_(None), GoalCalendarPlan.valid_until > start))
        .order_by(GoalCalendarPlan.valid_from, GoalCalendarPlan.id).limit(cap + 1))).all()
    complete = len(rows) <= cap and len(plans) <= cap
    for plan, status in plans[:cap]:
        config = GoalRecurrence.model_validate(plan.config)
        at = next_passage(config, max(start, plan.valid_from))
        while at is not None and at < end and (plan.valid_until is None or at < plan.valid_until):
            identity = passage_id(plan.id, at)
            if identity not in items and (at <= reference or status == GoalStatus.ACTIVE):
                future = at > reference
                state = "scheduled" if future else "skipped" if reference > at + timedelta(minutes=config.max_lateness_minutes) else "waiting"
                items[identity] = GoalAgendaEvent(id=identity, goal_id=plan.goal_id, title=plan.title,
                    scheduled_at=at, timezone=config.timezone, projected=future, state=state)
            if len(items) > cap:
                complete = False
                break
            at = next_passage(config, at, inclusive=False)
        if len(items) > cap:
            break
    # Existing Goals keep their actual cycle history without inventing historical planning.
    legacy = (await db.execute(select(GoalCycle, Task, Goal.title).join(Goal, Goal.id == GoalCycle.goal_id)
        .outerjoin(Task, Task.id == GoalCycle.task_id).where(*conditions,
            GoalCycle.created_at >= start, GoalCycle.created_at < end,
            ~exists().where(GoalOccurrence.cycle_id == GoalCycle.id))
        .order_by(GoalCycle.created_at, GoalCycle.id).limit(cap + 1))).all()
    for cycle, task, title in legacy:
        occurrence = GoalOccurrence(id=cycle.id, goal_id=cycle.goal_id, title=title,
            scheduled_at=cycle.created_at, timezone="UTC", state="linked")
        items[occurrence.id] = agenda_event(occurrence, cycle, task)
    # Delay-based Goals have only one predictable future instant; never fabricate a series.
    goals = list((await db.scalars(select(Goal).where(*conditions, Goal.status == GoalStatus.ACTIVE,
        Goal.recurrence.is_(None), Goal.next_cycle_at >= start, Goal.next_cycle_at < end,
        # A durable passage replaces its prediction, even if eligibility was retained.
        ~exists().where(GoalOccurrence.goal_id == Goal.id,
            GoalOccurrence.scheduled_at == Goal.next_cycle_at),
        ~exists().where(GoalCycle.goal_id == Goal.id, GoalCycle.verdict.is_(None)))
        .order_by(Goal.next_cycle_at, Goal.id).limit(cap + 1))).all())
    for goal in goals:
        if goal.next_cycle_at is not None:
            items[goal.id] = GoalAgendaEvent(id=goal.id, goal_id=goal.id, title=goal.title,
                scheduled_at=goal.next_cycle_at, timezone="UTC", projected=True, state="scheduled")
    ordered = sorted(items.values(), key=lambda item: (item.scheduled_at, str(item.id)))
    return GoalAgendaWindow(items=ordered[:cap], complete=complete and len(ordered) <= cap)
