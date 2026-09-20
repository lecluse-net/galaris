"""CRUD, supervision, and cost accounting for long-running Goals."""

from __future__ import annotations

from app.llm import model_usages

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Sequence
from uuid import UUID, uuid4

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.orm.exc import StaleDataError
from pydantic import ValidationError

from app.agent.models import Agent
from app.task.models import Task, TaskStatus
from core import websocket
from core.database import get_db
from core.user import get_current_user_id

from .document_store import GoalMarkdown, get_goal_document_store
from .contact_port import contact_directory_port
from .lifecycle import notify_goal
from .models import (
    Goal,
    GoalCycle,
    GoalCycleTrigger,
    GoalCycleStatus,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)
from .schemas import (
    GoalAgentReferrerInput,
    GoalCommand,
    GoalCreate,
    GoalCyclePage,
    GoalCycleRead,
    GoalDetail,
    GoalMessengerReferrerInput,
    GoalPage,
    GoalRead,
    GoalReferrerInput,
    GoalReferrerRead,
    GoalScheduleConfig,
    GoalSummary,
    GoalUpdate,
    GoalTreeNode,
    GoalTreePage,
    MessengerReferrerOption,
)

if TYPE_CHECKING:
    from app.llm import LLM


class GoalConflictError(RuntimeError):
    """A Goal command conflicts with its current durable state."""


class GoalRevisionConflict(GoalConflictError):
    """The Goal changed since the client last loaded it."""


@dataclass(frozen=True)
class GoalMetrics:
    cycle_count: int = 0
    task_cost: float = 0.0
    evaluation_cost: float = 0.0
    last_task_finished_at: datetime | None = None
    current_task_id: UUID | None = None
    last_verdict: GoalVerdict | None = None

    @property
    def total_cost(self) -> float:
        return self.task_cost + self.evaluation_cost


def _assert_automatic_trigger_configuration(
    *,
    cycle_delay_seconds: int | None,
    parent_goal_id: UUID | None,
    schedule_enabled: bool,
) -> None:
    """Require exactly one automatic trigger and keep schedules temporal-only."""

    has_temporal_trigger = cycle_delay_seconds is not None
    has_relational_trigger = parent_goal_id is not None
    if has_temporal_trigger == has_relational_trigger:
        raise GoalConflictError(
            "A Goal must use exactly one automatic trigger: frequency or parent Goal."
        )
    if has_relational_trigger and schedule_enabled:
        raise GoalConflictError(
            "A parent-driven Goal cannot define its own time window."
        )


def _effective_task_cost():
    """Use the live Task cost until its immutable cycle snapshot is available."""

    return case(
        (
            GoalCycle.task_finished_at.is_(None),
            func.coalesce(Task.cost, GoalCycle.task_cost, 0.0),
        ),
        else_=GoalCycle.task_cost,
    )


def _apply_filters(
    query: Select[Any],
    *,
    agent_id: int | None,
    status: GoalStatus | None,
    search: str | None,
    agent_ids: Collection[int] | None = None,
    document_matches: dict[str, frozenset[UUID]] | None = None,
) -> Select[Any]:
    if agent_id is not None:
        query = query.where(Goal.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(
            Goal.agent_id.in_(agent_ids),
            or_(
                Goal.referrer_agent_id.is_(None),
                Goal.referrer_agent_id.in_(agent_ids),
            ),
        )
    if status is not None:
        query = query.where(Goal.status == status)
    terms = [term.strip() for term in (search or "").split() if term.strip()]
    if terms:
        referrer_agent = aliased(Agent)
        query = query.join(Agent, Goal.agent_id == Agent.id)
        for term in terms:
            pattern = f"%{term}%"
            query = query.where(
                or_(
                    Goal.title.ilike(pattern),
                    Goal.description_document_id.in_(
                        (document_matches or {}).get(term, frozenset())
                    ),
                    Goal.tracking_document_id.in_(
                        (document_matches or {}).get(term, frozenset())
                    ),
                    Agent.first_name.ilike(pattern),
                    Agent.last_name.ilike(pattern),
                    Agent.code.ilike(pattern),
                    Agent.job_title.ilike(pattern),
                    Goal.referrer_display_name.ilike(pattern),
                    Goal.referrer_user_id.ilike(pattern),
                    Goal.referrer_platform.ilike(pattern),
                    select(referrer_agent.id)
                    .where(
                        referrer_agent.id == Goal.referrer_agent_id,
                        or_(
                            referrer_agent.first_name.ilike(pattern),
                            referrer_agent.last_name.ilike(pattern),
                            referrer_agent.code.ilike(pattern),
                            referrer_agent.job_title.ilike(pattern),
                        ),
                    )
                    .exists(),
                )
            )
    return Goal.histo_filter(query)


async def _metrics_for(goal_ids: Sequence[UUID]) -> dict[UUID, GoalMetrics]:
    if not goal_ids:
        return {}
    db = get_db()
    rows = (
        await db.execute(
            select(
                GoalCycle.goal_id,
                func.count(GoalCycle.id),
                func.coalesce(func.sum(_effective_task_cost()), 0.0),
                func.coalesce(func.sum(GoalCycle.judge_cost), 0.0),
                func.max(GoalCycle.task_finished_at),
            )
            .outerjoin(Task, Task.id == GoalCycle.task_id)
            .where(GoalCycle.goal_id.in_(goal_ids))
            .group_by(GoalCycle.goal_id)
        )
    ).all()
    metrics = {
        goal_id: GoalMetrics(
            cycle_count=int(cycle_count),
            task_cost=float(task_cost),
            evaluation_cost=float(judge_cost),
            last_task_finished_at=last_finished,
        )
        for goal_id, cycle_count, task_cost, judge_cost, last_finished in rows
    }
    latest_rows = (
        await db.execute(
            select(GoalCycle.goal_id, GoalCycle.task_id, GoalCycle.verdict)
            .where(GoalCycle.goal_id.in_(goal_ids))
            .distinct(GoalCycle.goal_id)
            .order_by(GoalCycle.goal_id, GoalCycle.sequence.desc())
        )
    ).all()
    for goal_id, task_id, verdict in latest_rows:
        current = metrics.get(goal_id, GoalMetrics())
        metrics[goal_id] = GoalMetrics(
            cycle_count=current.cycle_count,
            task_cost=current.task_cost,
            evaluation_cost=current.evaluation_cost,
            last_task_finished_at=current.last_task_finished_at,
            current_task_id=task_id if verdict is None else None,
            last_verdict=verdict,
        )
    return metrics


def _agent_name(agent: Agent | None, agent_id: int) -> str:
    if agent is None:
        return f"Agent #{agent_id}"
    title = agent.title.label
    return " ".join(
        part for part in (title, agent.first_name, agent.last_name) if part
    ).strip()


def _serialize_referrer(goal: Goal) -> GoalReferrerRead | None:
    if goal.referrer_type == GoalReferrerType.AGENT:
        agent = goal.referrer_agent
        if goal.referrer_agent_id is None:
            return None
        return GoalReferrerRead(
            type=GoalReferrerType.AGENT,
            display_name=(
                _agent_name(agent, goal.referrer_agent_id)
                if agent is not None
                else goal.referrer_display_name or f"Agent #{goal.referrer_agent_id}"
            ),
            agent_id=goal.referrer_agent_id,
            agent_code=agent.code if agent is not None else None,
        )
    if goal.referrer_type == GoalReferrerType.MESSENGER:
        if not goal.referrer_user_id:
            return None
        return GoalReferrerRead(
            type=GoalReferrerType.MESSENGER,
            display_name=goal.referrer_display_name or goal.referrer_user_id,
            connection_id=goal.referrer_connection_id,
            user_id=goal.referrer_user_id,
            platform=goal.referrer_platform,
        )
    return None


def _serialize_goal(
    goal: Goal, metrics: GoalMetrics, markdown: GoalMarkdown
) -> GoalRead:
    return GoalRead.model_validate(
        {
            **goal.__dict__,
            "description": markdown.description,
            "tracking_content": markdown.tracking,
            "agent_name": _agent_name(goal.agent, goal.agent_id),
            "agent_code": goal.agent.code if goal.agent is not None else "",
            "referrer": _serialize_referrer(goal),
            "cycle_count": metrics.cycle_count,
            "task_cost": metrics.task_cost,
            "evaluation_cost": metrics.evaluation_cost,
            "total_cost": metrics.total_cost,
            "current_task_id": metrics.current_task_id,
            "last_task_finished_at": metrics.last_task_finished_at,
            "last_verdict": metrics.last_verdict,
            "parent_title": goal.parent.title if goal.parent is not None else None,
            "children_count": len(goal.children),
        }
    )


async def read_markdown(goal: Goal) -> GoalMarkdown:
    contents = await get_goal_document_store().read_many(
        (goal.description_document_id, goal.tracking_document_id)
    )
    return GoalMarkdown(
        description=contents[goal.description_document_id],
        tracking=contents[goal.tracking_document_id],
    )


async def _read_markdown_batch(goals: Sequence[Goal]) -> dict[UUID, GoalMarkdown]:
    document_ids = tuple(
        document_id
        for goal in goals
        for document_id in (
            goal.description_document_id,
            goal.tracking_document_id,
        )
    )
    contents = await get_goal_document_store().read_many(document_ids)
    return {
        goal.id: GoalMarkdown(
            description=contents[goal.description_document_id],
            tracking=contents[goal.tracking_document_id],
        )
        for goal in goals
    }


async def get_by_id(
    goal_id: UUID,
    *,
    for_update: bool = False,
    owner_agent_id: int | None = None,
) -> Goal | None:
    """Load one Goal, optionally restricting the query to its exact owner."""

    db = get_db()
    query = (
        select(Goal)
        .options(
            selectinload(Goal.agent).selectinload(Agent.title),
            selectinload(Goal.referrer_agent).selectinload(Agent.title),
            selectinload(Goal.parent),
            selectinload(Goal.children),
        )
        .where(Goal.id == goal_id)
    )
    if owner_agent_id is not None:
        query = query.where(Goal.agent_id == owner_agent_id)
    if for_update:
        query = query.with_for_update()
    return await db.scalar(Goal.histo_filter(query))


async def get_read(
    goal_id: UUID,
    *,
    owner_agent_id: int | None = None,
) -> GoalRead | None:
    goal = await get_by_id(goal_id, owner_agent_id=owner_agent_id)
    if goal is None:
        return None
    metrics = (await _metrics_for([goal.id])).get(goal.id, GoalMetrics())
    return _serialize_goal(goal, metrics, await read_markdown(goal))


async def get_detail(
    goal_id: UUID,
    *,
    owner_agent_id: int | None = None,
) -> GoalDetail | None:
    goal_read = await get_read(goal_id, owner_agent_id=owner_agent_id)
    if goal_read is None:
        return None
    return GoalDetail(**goal_read.model_dump())


def _serialize_cycle(
    cycle: GoalCycle,
    task_label: str | None,
    task_status: TaskStatus | str | None,
    current_task_cost: float | None,
) -> GoalCycleRead:
    return GoalCycleRead.model_validate(cycle).model_copy(
        update={
            "task_label": task_label,
            "task_status": (
                task_status.value
                if isinstance(task_status, TaskStatus)
                else str(task_status) if task_status is not None else None
            ),
            "task_cost": (
                float(current_task_cost or 0.0)
                if cycle.task_finished_at is None and current_task_cost is not None
                else float(cycle.task_cost or 0.0)
            ),
        }
    )


async def list_cycles(
    goal_id: UUID,
    *,
    page: int = 1,
    page_size: int = 20,
    owner_agent_id: int | None = None,
) -> GoalCyclePage | None:
    """Return one newest-first page without loading the Goal's full history."""

    if await get_by_id(goal_id, owner_agent_id=owner_agent_id) is None:
        return None
    db = get_db()
    total = int(
        await db.scalar(
            select(func.count(GoalCycle.id)).where(GoalCycle.goal_id == goal_id)
        )
        or 0
    )
    rows = (
        await db.execute(
            select(GoalCycle, Task.label, Task.status, Task.cost)
            .outerjoin(Task, Task.id == GoalCycle.task_id)
            .where(GoalCycle.goal_id == goal_id)
            .order_by(GoalCycle.sequence.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return GoalCyclePage(
        items=[_serialize_cycle(*row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_tracking_llm(agent_id: int | None = None) -> "LLM | None":
    """Resolve the profile's chat-capable Goal model without implicit fallback."""

    from app.llm import llm_service
    try:
        llm = await llm_service.get_profile_llm_for_agent_id(
            model_usages.GOAL, agent_id
        )
    except ValueError:
        return None
    if (
        llm is None
        or "chat" not in {llm.primary_capability, *llm.service_capabilities}
        or not llm.input_text
        or not llm.output_text
    ):
        return None
    return llm


async def tracking_llm_configured() -> bool:
    return await get_tracking_llm() is not None


async def list_page(
    *,
    skip: int = 0,
    limit: int = 50,
    agent_id: int | None = None,
    status: GoalStatus | None = None,
    search: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> GoalPage:
    db = get_db()
    terms = tuple(term.strip() for term in (search or "").split() if term.strip())
    document_matches = await get_goal_document_store().search(terms)
    filtered_ids = _apply_filters(
        select(Goal.id),
        agent_id=agent_id,
        status=status,
        search=search,
        agent_ids=agent_ids,
        document_matches=document_matches,
    )
    goals = list(
        (
            await db.scalars(
                _apply_filters(
                    select(Goal)
                    .options(
                        selectinload(Goal.agent).selectinload(Agent.title),
                        selectinload(Goal.referrer_agent).selectinload(Agent.title),
                        selectinload(Goal.parent),
                        selectinload(Goal.children),
                    )
                    .order_by(Goal.updated_at.desc().nullslast(), Goal.created_at.desc())
                    .offset(skip)
                    .limit(limit),
                    agent_id=agent_id,
                    status=status,
                    search=search,
                    agent_ids=agent_ids,
                    document_matches=document_matches,
                )
            )
        ).all()
    )
    metrics = await _metrics_for([goal.id for goal in goals])
    markdown_by_goal = await _read_markdown_batch(goals)

    status_rows = (
        await db.execute(
            select(Goal.status, func.count(Goal.id))
            .where(Goal.id.in_(filtered_ids))
            .group_by(Goal.status)
        )
    ).all()
    status_counts = {row_status: int(count) for row_status, count in status_rows}
    total = sum(status_counts.values())

    all_costs = await db.scalar(
        select(
            func.coalesce(
                func.sum(_effective_task_cost() + GoalCycle.judge_cost), 0.0
            )
        )
        .outerjoin(Task, Task.id == GoalCycle.task_id)
        .where(GoalCycle.goal_id.in_(filtered_ids))
    )
    summary = GoalSummary(
        active=status_counts.get(GoalStatus.ACTIVE, 0),
        paused=status_counts.get(GoalStatus.PAUSED, 0),
        completed=status_counts.get(GoalStatus.COMPLETED, 0),
        errors=status_counts.get(GoalStatus.ERROR, 0),
        total_cost=float(all_costs or 0.0),
    )
    return GoalPage(
        items=[
            _serialize_goal(
                goal,
                metrics.get(goal.id, GoalMetrics()),
                markdown_by_goal[goal.id],
            )
            for goal in goals
        ],
        total=total,
        summary=summary,
        tracking_llm_configured=await tracking_llm_configured(),
    )


async def _assert_agent(agent_id: int) -> Agent:
    agent = await get_db().scalar(
        select(Agent)
        .options(selectinload(Agent.title))
        .where(Agent.id == agent_id)
    )
    if agent is None or agent.deleted_at is not None:
        raise LookupError(f"Agent {agent_id} not found")
    return agent


async def _assert_parent(goal_id: UUID, parent_goal_id: UUID | None) -> Goal | None:
    """Validate one parent assignment and reject every ancestor cycle."""

    if parent_goal_id is None:
        return None
    if parent_goal_id == goal_id:
        raise GoalConflictError("A Goal cannot be its own parent.")
    db = get_db()
    parent = await db.scalar(
        Goal.histo_filter(
            select(Goal).where(Goal.id == parent_goal_id).with_for_update()
        )
    )
    if parent is None:
        raise LookupError(f"Parent Goal {parent_goal_id} not found")
    seen: set[UUID] = set()
    current: Goal | None = parent
    while current is not None:
        if current.id == goal_id:
            raise GoalConflictError("This parent would create a Goal hierarchy cycle.")
        if current.id in seen:
            raise GoalConflictError("The Goal hierarchy already contains a cycle.")
        seen.add(current.id)
        if current.parent_goal_id is None:
            break
        current = await db.scalar(
            Goal.histo_filter(
                select(Goal)
                .where(Goal.id == current.parent_goal_id)
                .with_for_update()
            )
        )
    return parent


async def list_tree(*, agent_ids: Collection[int] | None = None) -> GoalTreePage:
    """Return the lightweight Goal hierarchy visible to the current management scope."""

    query = (
        select(Goal)
        .options(
            selectinload(Goal.agent).selectinload(Agent.title),
            selectinload(Goal.children),
        )
        .order_by(Goal.title.asc(), Goal.id.asc())
    )
    if agent_ids is not None:
        query = query.where(Goal.agent_id.in_(agent_ids))
    goals = list((await get_db().scalars(Goal.histo_filter(query))).all())
    return GoalTreePage(
        items=[
            GoalTreeNode(
                id=goal.id,
                parent_goal_id=goal.parent_goal_id,
                title=goal.title,
                agent_id=goal.agent_id,
                agent_name=_agent_name(goal.agent, goal.agent_id),
                agent_code=goal.agent.code if goal.agent is not None else "",
                status=goal.status,
                cycle_delay_seconds=goal.cycle_delay_seconds,
                next_cycle_at=goal.next_cycle_at,
                children_count=len(goal.children),
            )
            for goal in goals
        ],
        total=len(goals),
    )


async def _resolve_referrer(
    owner_agent_id: int, referrer: GoalReferrerInput
) -> dict[str, Any]:
    """Validate and normalize a referrer into durable Goal columns."""

    if isinstance(referrer, GoalAgentReferrerInput):
        agent = await _assert_agent(referrer.agent_id)
        if agent.id == owner_agent_id:
            raise GoalConflictError(
                "The Goal owner and referring agent must be different agents."
            )
        return {
            "referrer_type": GoalReferrerType.AGENT,
            "referrer_agent_id": agent.id,
            "referrer_connection_id": None,
            "referrer_user_id": None,
            "referrer_display_name": _agent_name(agent, agent.id),
            "referrer_platform": None,
            "requester_user_id": get_current_user_id(),
        }

    assert isinstance(referrer, GoalMessengerReferrerInput)
    from app.messenger import service as messenger_service

    try:
        messenger = await messenger_service.messenger_for_agent_connection(
            owner_agent_id, referrer.connection_id
        )
    except (LookupError, ValueError) as exc:
        raise GoalConflictError(str(exc)) from exc
    if referrer.user_id == messenger.self_id:
        raise GoalConflictError(
            "The Goal owner cannot use its own Messenger identity as the human referrer."
        )
    from app.messenger import MessengerUser, directory

    resolved_user = await directory.resolve_user(messenger.tool_id, referrer.user_id)
    if resolved_user.agent_id is not None:
        raise GoalConflictError(
            "This Messenger identity belongs to an agent. Select it from the agent list."
        )
    requester_user_id = await get_db().scalar(
        select(MessengerUser.galaris_user_id).where(
            MessengerUser.tool_id == messenger.tool_id,
            MessengerUser.external_id == referrer.user_id,
        )
    )
    return {
        "referrer_type": GoalReferrerType.MESSENGER,
        "referrer_agent_id": None,
        "referrer_connection_id": referrer.connection_id,
        "referrer_user_id": referrer.user_id,
        "referrer_display_name": referrer.display_name,
        "referrer_platform": messenger.kind or "messenger",
        "requester_user_id": requester_user_id,
    }


def _assign_referrer(goal: Goal, values: dict[str, Any]) -> None:
    for field_name, value in values.items():
        setattr(goal, field_name, value)


async def assert_referrer_available(goal: Goal) -> None:
    """Reject execution when the durable referrer can no longer be reached."""

    if goal.referrer_type == GoalReferrerType.AGENT:
        if goal.referrer_agent_id is None:
            raise GoalConflictError("The Goal's referring agent is no longer available.")
        try:
            await _assert_agent(goal.referrer_agent_id)
        except LookupError as exc:
            raise GoalConflictError(str(exc)) from exc
        if goal.referrer_agent_id == goal.agent_id:
            raise GoalConflictError(
                "The Goal owner and referring agent must be different agents."
            )
        return
    if goal.referrer_type == GoalReferrerType.MESSENGER:
        if goal.referrer_connection_id is None or not goal.referrer_user_id:
            raise GoalConflictError(
                "The Goal's Messenger referrer no longer has a usable connection."
            )
        from app.messenger import service as messenger_service

        try:
            messenger = await messenger_service.messenger_for_agent_connection(
                goal.agent_id, goal.referrer_connection_id
            )
        except (LookupError, ValueError) as exc:
            raise GoalConflictError(str(exc)) from exc
        if goal.referrer_platform and messenger.kind != goal.referrer_platform:
            raise GoalConflictError(
                "The Goal's Messenger connection now targets a different platform. "
                "Select the human referrer again."
            )
        if goal.referrer_user_id == messenger.self_id:
            raise GoalConflictError(
                "The Goal owner cannot use its own Messenger identity as the human referrer."
            )
        from app.messenger import MessengerUser, directory

        resolved_user = await directory.resolve_user(
            messenger.tool_id, goal.referrer_user_id
        )
        if resolved_user.agent_id is not None:
            raise GoalConflictError(
                "The Messenger referrer now belongs to an agent. Select it from the agent list."
            )
        # Legacy Goals predate the frozen requester column. Resolve it once from the current
        # canonical link, then keep the snapshot stable on subsequent cycles.
        if goal.requester_user_id is None:
            goal.requester_user_id = await get_db().scalar(
                select(MessengerUser.galaris_user_id).where(
                    MessengerUser.tool_id == messenger.tool_id,
                    MessengerUser.external_id == goal.referrer_user_id,
                )
            )
        return
    raise GoalConflictError(
        "This legacy Goal has no referrer. Select an agent or Messenger contact first."
    )


async def search_messenger_referrers(
    agent_id: int, query: str
) -> list[MessengerReferrerOption]:
    """Return human contacts reachable by the selected Goal owner agent."""

    await _assert_agent(agent_id)
    matches = await contact_directory_port.list_humans(
        agent_id=agent_id,
        query=query,
    )
    current_user_id = get_current_user_id()
    return [
        MessengerReferrerOption(
            connection_id=contact.connection_id,
            tool_id=contact.tool_id,
            platform=contact.platform,
            user_id=contact.user_id,
            display_name=contact.display_name,
            is_current_user=(
                current_user_id is not None
                and contact.galaris_user_id == current_user_id
            ),
        )
        for contact in matches
    ]


async def _emit(goal_id: UUID, action: str = "update") -> None:
    goal = await get_read(goal_id)
    if goal is not None:
        await notify_goal(goal_id, action)
        await websocket.emit("goal", action, goal.model_dump(mode="json"), None)


async def create(data: GoalCreate) -> GoalRead:
    _assert_automatic_trigger_configuration(
        cycle_delay_seconds=data.cycle_delay_seconds,
        parent_goal_id=data.parent_goal_id,
        schedule_enabled=data.schedule_enabled,
    )
    await _assert_agent(data.agent_id)
    referrer = await _resolve_referrer(data.agent_id, data.referrer)
    now = datetime.now(timezone.utc)
    goal_id = uuid4()
    await _assert_parent(goal_id, data.parent_goal_id)
    document_store = get_goal_document_store()
    description_document_id = await document_store.create(
        goal_id=goal_id,
        owner_agent_id=data.agent_id,
        kind="description",
        goal_title=data.title,
        content=data.description,
    )
    try:
        tracking_document_id = await document_store.create(
            goal_id=goal_id,
            owner_agent_id=data.agent_id,
            kind="tracking",
            goal_title=data.title,
            content="",
        )
    except Exception:
        await document_store.discard(description_document_id)
        raise
    goal = Goal(
        id=goal_id,
        title=data.title,
        description_document_id=description_document_id,
        tracking_document_id=tracking_document_id,
        agent_id=data.agent_id,
        parent_goal_id=data.parent_goal_id,
        cycle_delay_seconds=data.cycle_delay_seconds,
        schedule_enabled=data.schedule_enabled,
        schedule=[window.model_dump(mode="json") for window in data.schedule],
        referrer_max_reminders=data.referrer_max_reminders,
        status=GoalStatus.ACTIVE if data.active else GoalStatus.PAUSED,
        pause_reason=None if data.active else "MANUAL",
        next_cycle_at=(
            now if data.active and data.cycle_delay_seconds is not None else None
        ),
        **referrer,
    )
    db = get_db()
    db.add(goal)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await document_store.discard(description_document_id)
        await document_store.discard(tracking_document_id)
        raise
    await db.refresh(goal)
    await _emit(goal.id, "create")

    if data.active and data.cycle_delay_seconds is not None:
        from app.task import scheduler

        scheduler.wake()
    result = await get_read(goal.id)
    assert result is not None
    return result


def _assert_revision(goal: Goal, command: GoalCommand | GoalUpdate) -> None:
    if goal.revision != command.expected_revision:
        raise GoalRevisionConflict(
            f"Goal revision conflict: expected {command.expected_revision}, "
            f"current {goal.revision}."
        )


async def _last_cycle(goal_id: UUID) -> GoalCycle | None:
    return await get_db().scalar(
        select(GoalCycle)
        .where(GoalCycle.goal_id == goal_id)
        .order_by(GoalCycle.sequence.desc())
        .limit(1)
    )


async def _has_any_cycle(goal_id: UUID) -> bool:
    return (
        await get_db().scalar(
            select(GoalCycle.id).where(GoalCycle.goal_id == goal_id).limit(1)
        )
        is not None
    )


async def _save(goal: Goal, *, action: str = "update") -> GoalRead:
    db = get_db()
    try:
        await db.commit()
    except StaleDataError as exc:
        await db.rollback()
        raise GoalRevisionConflict(f"Goal {goal.id} changed concurrently.") from exc
    await db.refresh(goal)
    await _emit(goal.id, action)
    result = await get_read(goal.id)
    assert result is not None
    return result


async def update(
    goal_id: UUID,
    data: GoalUpdate,
    *,
    owner_agent_id: int | None = None,
) -> GoalRead | None:
    goal = await get_by_id(
        goal_id,
        for_update=True,
        owner_agent_id=owner_agent_id,
    )
    if goal is None:
        return None
    _assert_revision(goal, data)
    changes = data.model_dump(
        exclude_unset=True,
        exclude={
            "expected_revision",
            "referrer",
            "description",
            "tracking_content",
        },
    )
    if {"schedule_enabled", "schedule"} & changes.keys():
        try:
            schedule_config = GoalScheduleConfig.model_validate(
                {
                    "schedule_enabled": changes.get(
                        "schedule_enabled", goal.schedule_enabled
                    ),
                    "schedule": changes.get("schedule", goal.schedule),
                }
            )
        except ValidationError as exc:
            raise GoalConflictError(
                "At least one schedule window is required when scheduling is enabled."
            ) from exc
        changes["schedule_enabled"] = schedule_config.schedule_enabled
        changes["schedule"] = [
            window.model_dump(mode="json") for window in schedule_config.schedule
        ]
    next_cycle_delay = (
        data.cycle_delay_seconds
        if "cycle_delay_seconds" in data.model_fields_set
        else goal.cycle_delay_seconds
    )
    next_parent_goal_id = (
        data.parent_goal_id
        if "parent_goal_id" in data.model_fields_set
        else goal.parent_goal_id
    )
    next_schedule_enabled = (
        data.schedule_enabled
        if "schedule_enabled" in data.model_fields_set
        else goal.schedule_enabled
    )
    assert next_schedule_enabled is not None
    _assert_automatic_trigger_configuration(
        cycle_delay_seconds=next_cycle_delay,
        parent_goal_id=next_parent_goal_id,
        schedule_enabled=next_schedule_enabled,
    )
    owner_agent_id = int(changes.get("agent_id", goal.agent_id))
    if "agent_id" in changes and changes["agent_id"] != goal.agent_id:
        if await _has_any_cycle(goal.id):
            raise GoalConflictError("An agent cannot be changed after the first Goal cycle.")
        await _assert_agent(owner_agent_id)

    referrer_values: dict[str, Any] | None = None
    if "referrer" in data.model_fields_set:
        assert data.referrer is not None
        referrer_values = await _resolve_referrer(owner_agent_id, data.referrer)
    elif owner_agent_id != goal.agent_id and goal.referrer_type == GoalReferrerType.MESSENGER:
        if goal.referrer_connection_id is None:
            raise GoalConflictError(
                "Select a Messenger referrer that belongs to the new Goal owner."
            )
        from app.messenger import service as messenger_service

        try:
            await messenger_service.messenger_for_agent_connection(
                owner_agent_id, goal.referrer_connection_id
            )
        except (LookupError, ValueError) as exc:
            raise GoalConflictError(
                "Select a Messenger referrer that belongs to the new Goal owner."
            ) from exc
    elif (
        owner_agent_id != goal.agent_id
        and goal.referrer_type == GoalReferrerType.AGENT
        and goal.referrer_agent_id == owner_agent_id
    ):
        raise GoalConflictError(
            "Select a referring agent different from the new Goal owner."
        )

    if "parent_goal_id" in changes:
        await _assert_parent(goal.id, changes["parent_goal_id"])

    delay_changed = (
        "cycle_delay_seconds" in changes
        and changes["cycle_delay_seconds"] != goal.cycle_delay_seconds
    )
    for key, value in changes.items():
        setattr(goal, key, value)
    if referrer_values is not None:
        _assign_referrer(goal, referrer_values)

    if delay_changed and goal.status != GoalStatus.COMPLETED:
        if goal.cycle_delay_seconds is None:
            goal.next_cycle_at = None
        else:
            last_cycle = await _last_cycle(goal.id)
            if (
                last_cycle is not None
                and last_cycle.verdict == GoalVerdict.CONTINUE
                and last_cycle.task_finished_at is not None
            ):
                goal.next_cycle_at = last_cycle.task_finished_at + timedelta(
                    seconds=goal.cycle_delay_seconds
                )
            elif last_cycle is None and goal.status == GoalStatus.ACTIVE:
                goal.next_cycle_at = datetime.now(timezone.utc)
    document_store = get_goal_document_store()
    document_changed = False
    if "description" in data.model_fields_set:
        assert data.description is not None
        await document_store.update(
            goal.description_document_id,
            content=data.description,
        )
        document_changed = True
    if "tracking_content" in data.model_fields_set:
        assert data.tracking_content is not None
        await document_store.update(
            goal.tracking_document_id,
            content=data.tracking_content,
        )
        document_changed = True
    title_changed = "title" in changes
    owner_changed = "agent_id" in changes
    if title_changed or owner_changed:
        for document_id in (
            goal.description_document_id,
            goal.tracking_document_id,
        ):
            await document_store.update(
                document_id,
                goal_title=goal.title,
                owner_agent_id=goal.agent_id if owner_changed else None,
            )
    goal_scalar_changed = bool(changes) or referrer_values is not None
    if document_changed and not goal_scalar_changed:
        goal.revision += 1
    result = await _save(goal)
    if goal.status == GoalStatus.ACTIVE:
        from app.task import scheduler

        scheduler.wake()
    return result


async def pause(goal_id: UUID, command: GoalCommand) -> GoalRead | None:
    goal = await get_by_id(goal_id, for_update=True)
    if goal is None:
        return None
    _assert_revision(goal, command)
    if goal.status == GoalStatus.COMPLETED:
        raise GoalConflictError("A completed Goal cannot be paused.")
    goal.status = GoalStatus.PAUSED
    goal.pause_reason = "MANUAL"
    goal.manual_run_requested_at = None
    return await _save(goal)


async def _reset_failed_judgement(goal: Goal) -> bool:
    last_cycle = await _last_cycle(goal.id)
    if last_cycle is None or last_cycle.status != GoalCycleStatus.ERROR:
        return False
    last_cycle.status = GoalCycleStatus.RUNNING
    last_cycle.error = None
    last_cycle.clear_lease()
    return True


async def resume(goal_id: UUID, command: GoalCommand) -> GoalRead | None:
    goal = await get_by_id(goal_id, for_update=True)
    if goal is None:
        return None
    _assert_revision(goal, command)
    was_completed = goal.status == GoalStatus.COMPLETED
    await assert_referrer_available(goal)
    retried_judgement = await _reset_failed_judgement(goal)
    goal.status = GoalStatus.ACTIVE
    goal.completed_at = None
    goal.pause_reason = None
    goal.last_error = None
    if was_completed and goal.cycle_delay_seconds is not None:
        goal.next_cycle_at = datetime.now(timezone.utc)
        goal.manual_run_requested_at = None
    elif was_completed:
        goal.next_cycle_at = None
        goal.manual_run_requested_at = None
    elif retried_judgement:
        goal.next_cycle_at = None
    else:
        last_cycle = await _last_cycle(goal.id)
        if last_cycle is None and goal.cycle_delay_seconds is not None:
            goal.next_cycle_at = datetime.now(timezone.utc)
        elif (
            last_cycle is not None
            and last_cycle.verdict == GoalVerdict.CONTINUE
            and last_cycle.task_finished_at is not None
            and goal.cycle_delay_seconds is not None
        ):
            goal.next_cycle_at = last_cycle.task_finished_at + timedelta(
                seconds=goal.cycle_delay_seconds
            )
    result = await _save(goal)
    from .referrer_wait import resume_wait_for_goal

    await resume_wait_for_goal(goal)
    from app.task import scheduler

    scheduler.wake()
    return result


async def complete(goal_id: UUID, command: GoalCommand) -> GoalRead | None:
    goal = await get_by_id(goal_id, for_update=True)
    if goal is None:
        return None
    _assert_revision(goal, command)
    last_cycle = await _last_cycle(goal.id)
    if (
        last_cycle is not None
        and last_cycle.status == GoalCycleStatus.ERROR
        and last_cycle.verdict is None
    ):
        last_cycle.status = GoalCycleStatus.DECIDED
        last_cycle.verdict = GoalVerdict.STOP
        last_cycle.reason = "The Goal was stopped manually after an evaluation error."
        last_cycle.judge_finished_at = datetime.now(timezone.utc)
        last_cycle.clear_lease()
        await enqueue_child_triggers(last_cycle)
        if last_cycle.task_id is not None:
            retained_task = await get_db().scalar(
                select(Task)
                .where(Task.id == last_cycle.task_id)
                .with_for_update()
                .execution_options(include_historized=True)
            )
            if retained_task is not None:
                from app.task import task_service

                task_service.release_retention(retained_task, "goal_judgement")
    goal.status = GoalStatus.COMPLETED
    goal.completed_at = datetime.now(timezone.utc)
    goal.next_cycle_at = None
    goal.manual_run_requested_at = None
    goal.pause_reason = None
    goal.last_error = None
    return await _save(goal)


async def run_now(
    goal_id: UUID,
    command: GoalCommand,
    *,
    owner_agent_id: int | None = None,
) -> GoalRead | None:
    goal = await get_by_id(
        goal_id,
        for_update=True,
        owner_agent_id=owner_agent_id,
    )
    if goal is None:
        return None
    _assert_revision(goal, command)
    if goal.status == GoalStatus.COMPLETED:
        raise GoalConflictError("A completed Goal cannot start another cycle.")
    await assert_referrer_available(goal)
    last_cycle = await _last_cycle(goal.id)
    if last_cycle is not None and last_cycle.verdict is None:
        if last_cycle.status == GoalCycleStatus.ERROR:
            await _reset_failed_judgement(goal)
        else:
            raise GoalConflictError("The current Goal cycle is still running.")
    # Retrying the previous evaluation must not consume a request for new work.
    # The runner waits for its verdict before starting the requested manual cycle.
    requested_at = datetime.now(timezone.utc)
    goal.next_cycle_at = requested_at
    goal.manual_run_requested_at = requested_at
    goal.status = GoalStatus.ACTIVE
    goal.pause_reason = None
    goal.last_error = None
    result = await _save(goal)
    from app.task import scheduler

    scheduler.wake()
    return result


async def delete(goal_id: UUID) -> bool:
    goal = await get_by_id(goal_id, for_update=True)
    if goal is None:
        return False
    open_cycle = await get_db().scalar(
        select(GoalCycle.id)
        .where(
            GoalCycle.goal_id == goal.id,
            GoalCycle.verdict.is_(None),
        )
        .limit(1)
    )
    if open_cycle is not None:
        raise GoalConflictError("A Goal with a running cycle cannot be deleted.")
    child_id = await get_db().scalar(
        Goal.histo_filter(
            select(Goal.id).where(Goal.parent_goal_id == goal.id).limit(1)
        )
    )
    if child_id is not None:
        raise GoalConflictError(
            "A Goal with sub-goals cannot be deleted. Detach or move them first."
        )
    goal.soft_delete()
    await get_db().commit()
    await notify_goal(goal_id, "delete")
    await websocket.emit("goal", "delete", {
        "id": str(goal_id), "agent_id": goal.agent_id,
        "referrer_agent_id": goal.referrer_agent_id,
    }, None)
    return True


async def emit_updated(goal_id: UUID) -> None:
    """Publish a worker-side state change through the regular Goal channel."""

    await _emit(goal_id)


async def enqueue_child_triggers(cycle: GoalCycle) -> None:
    """Accept one relational trigger per direct child, idempotently."""

    child_ids = list(
        (
            await get_db().scalars(
                Goal.histo_filter(
                    select(Goal.id).where(Goal.parent_goal_id == cycle.goal_id)
                )
            )
        ).all()
    )
    if not child_ids:
        return
    statement = (
        pg_insert(GoalCycleTrigger)
        .values(
            [
                {
                    "id": uuid4(),
                    "goal_id": child_id,
                    "source_cycle_id": cycle.id,
                }
                for child_id in child_ids
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["goal_id", "source_cycle_id"]
        )
    )
    await get_db().execute(statement)


async def handle_goal_document_change(item_id: UUID, action: str) -> None:
    """Reflect a document-library edit in Goal concurrency and projections."""

    if action != "update":
        return
    goal = await get_db().scalar(
        select(Goal).where(
            or_(
                Goal.description_document_id == item_id,
                Goal.tracking_document_id == item_id,
            )
        )
    )
    if goal is None:
        return
    goal.revision += 1
    await get_db().commit()
    await _emit(goal.id)
