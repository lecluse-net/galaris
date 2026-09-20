"""Durable Goal worker: judge terminal cycles, then materialize due Tasks."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.agent.models import Agent
from app.llm import LLM, LLMCallPurpose, model_usages
from app.llm.models import LLMCall
from app.llm.structured_service import run_structured
from app.task import task_service, try_lock_agent
from app.task.models import Task, TaskAttempt, TaskStatus
from app.task.schemas import TaskCreate
from core.database import get_db

from . import goal_service, settings_service
from .document_store import get_goal_document_store
from .models import (
    Goal,
    GoalCycle,
    GoalCycleTrigger,
    GoalCycleTriggerKind,
    GoalCycleStatus,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)
from .schemas import GoalJudgement


_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
_JUDGE_LEASE_SECONDS = 600
_MAX_TASK_RESULT_CHARS = 30_000
_GOAL_JUDGEMENT_RETENTION = "goal_judgement"
_TERMINAL_TASK_STATUSES = (TaskStatus.SUCCESS, TaskStatus.ERROR)
_RUNNABLE_TASK_STATUSES = (
    TaskStatus.CREATE,
    TaskStatus.DISPATCH,
    TaskStatus.BRIEFING,
    TaskStatus.EXEC,
    TaskStatus.PLAN,
)

_TRACKING_SYSTEM_PROMPT = """
You maintain the durable HTML tracking for a long-running Goal.

After every completed work cycle, return the full updated tracking document and exactly one
semantic action:
- CONTINUE: the Goal is not finished and another future work cycle can make meaningful progress.
- STOP: the Goal is achieved, explicitly no longer useful, or no additional cycle can reasonably
  advance it from the available evidence.

Judge the Goal, not whether the latest Task merely ended successfully. A failed or partial Task can
still justify CONTINUE. An open-ended Goal should continue while valuable concrete work remains.
Base the decision only on the Goal, its current durable tracking, and the latest Task result.
STOP must cite at least one observable evidence item. Do not invent evidence.

Return semantic HTML fragments (paragraphs, headings, lists, tables, code and links), never Markdown. Images, scripts, arbitrary styles and external image URLs are forbidden.
The tracking_content is the Goal's single shared source of truth. Return the entire document, not
a patch. Preserve useful verified facts, integrate the latest result, correct stale statements,
remove obsolete noise, and keep it concise and easy for a human to scan. It should normally cover
current state, completed milestones, evidence, decisions, blockers, and remaining work. It must not
choose a route, effort, planner mode, model, or assignee. Those decisions remain exclusively owned
by Galaris' normal dispatcher.
""".strip()


def goal_tracking_system_prompt() -> str:
    """Return the stable Goal judgement contract shared with isolated Lab runs."""
    return _TRACKING_SYSTEM_PROMPT


def _referrer_context(goal: Goal) -> str:
    """Build explicit, actionable contact instructions for one Goal Task."""

    if goal.referrer_type == GoalReferrerType.AGENT:
        agent = goal.referrer_agent
        name = goal.referrer_display_name or f"Agent #{goal.referrer_agent_id}"
        code = agent.code if agent is not None else ""
        return (
            "REFERRER (the person who assigned this Goal):\n"
            f"Agent {name} (id={goal.referrer_agent_id}, code={code or 'unknown'}).\n"
            "When you need information, a decision, or want to report meaningful progress, "
            "contact this agent with task_run using the exact agent_id above. State that your "
            "request or update concerns this Goal."
        )
    if goal.referrer_type == GoalReferrerType.MESSENGER:
        return (
            "REFERRER (the human who assigned this Goal):\n"
            f"{goal.referrer_display_name or goal.referrer_user_id} "
            f"(exact user_id={goal.referrer_user_id}, platform={goal.referrer_platform}).\n"
            "For a non-blocking progress update, use messenger_send_message_to_user with the "
            "exact user_id above. When you need information or a decision and must wait for "
            "the answer, use goal_ask_referrer instead. That tool correlates the human reply, "
            "suspends this Task, sends at most "
            f"{goal.referrer_max_reminders} automatic reminder(s) at 24-hour intervals, and "
            "pauses the Goal if no answer arrives. Never send those reminders yourself. The "
            "Task is pinned to the selected Messenger connection."
        )
    return "REFERRER:\nNo usable referrer is configured."


def next_cycle_at(finished_at: datetime, delay_seconds: int) -> datetime:
    """Return the earliest eligible time for a subsequent Goal cycle."""

    return finished_at + timedelta(seconds=max(0, delay_seconds))


def _task_result(task: Task) -> str:
    execution = task.get_execution_result()
    if execution is not None and execution.result.strip():
        return execution.result.strip()[:_MAX_TASK_RESULT_CHARS]
    return (task.feedback or task.last_error or "").strip()[:_MAX_TASK_RESULT_CHARS]


async def _judge_prompt(goal: Goal, cycle: GoalCycle, task: Task) -> str:
    markdown = await goal_service.read_markdown(goal)
    sections = [
        f"GOAL TITLE:\n{goal.title}",
        f"GOAL DESCRIPTION:\n{markdown.description}",
        (
            "CURRENT DURABLE TRACKING (HTML):\n"
            + (markdown.tracking or "(No tracking has been recorded yet.)")
        ),
        _referrer_context(goal),
        f"LATEST CYCLE:\n{cycle.sequence}",
        f"LATEST TASK STATUS:\n{task.status.value}",
        f"LATEST TASK OBJECTIVE:\n{task.objective or ''}",
        f"LATEST TASK RESULT:\n{_task_result(task) or '(no result recorded)'}",
    ]
    return "\n\n".join(sections)


async def _task_finished_at(task: Task) -> datetime:
    finished = await get_db().scalar(
        select(func.max(TaskAttempt.finished_at)).where(TaskAttempt.task_id == task.id)
    )
    if isinstance(finished, datetime):
        return finished
    if isinstance(task.updated_at, datetime):
        return task.updated_at
    return datetime.now(timezone.utc)


async def _release_cycle_task_retention(cycle: GoalCycle) -> None:
    if cycle.task_id is None:
        return
    task = await get_db().scalar(
        select(Task)
        .where(Task.id == cycle.task_id)
        .with_for_update()
        .execution_options(include_historized=True, populate_existing=True)
    )
    if task is not None:
        task_service.release_retention(task, _GOAL_JUDGEMENT_RETENTION)


async def _recorded_tracking_cost(
    task_id: UUID,
    started_at: datetime | None,
    fallback: float,
) -> float:
    """Prefer the canonical persisted llm_calls total over a client-side estimate."""

    if started_at is None:
        return max(0.0, float(fallback))
    count, cost = (
        await get_db().execute(
            select(
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.cost), 0.0),
            ).where(
                LLMCall.task_id == task_id,
                LLMCall.started_at >= started_at,
            )
        )
    ).one()
    return (
        max(0.0, float(cost or 0.0))
        if int(count or 0) > 0
        else max(0.0, float(fallback))
    )


async def _prepare_terminal_cycle() -> bool:
    """Persist the end of a Goal Task before any optional tracking judgement.

    Runtime schedules only govern new Goal activity. A cycle whose Task is already terminal
    must stop appearing as running even when tracking is temporarily unavailable or globally
    paused. ``Task.paused`` is deliberately ignored: terminal status remains authoritative.
    """

    db = get_db()
    cycle = await db.scalar(
        select(GoalCycle)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .join(Task, Task.id == GoalCycle.task_id)
        .options(
            selectinload(GoalCycle.goal),
            selectinload(GoalCycle.task),
        )
        .where(
            GoalCycle.verdict.is_(None),
            GoalCycle.status == GoalCycleStatus.RUNNING,
            Task.status.in_(_TERMINAL_TASK_STATUSES),
        )
        .order_by(Task.updated_at.asc(), GoalCycle.created_at.asc())
        .with_for_update(skip_locked=True, of=GoalCycle)
        .limit(1)
        .execution_options(include_historized=True)
    )
    if cycle is None or cycle.task is None:
        return False

    now = datetime.now(timezone.utc)
    cycle.task_finished_at = await _task_finished_at(cycle.task)
    cycle.task_cost = float(cycle.task.cost or 0.0)
    cycle.error = None
    if cycle.goal.status == GoalStatus.COMPLETED:
        cycle.status = GoalCycleStatus.DECIDED
        cycle.verdict = GoalVerdict.STOP
        cycle.reason = "The Goal was stopped manually before post-task evaluation."
        cycle.progress_changed = None
        cycle.judge_finished_at = now
        cycle.clear_lease()
        await _release_cycle_task_retention(cycle)
        await goal_service.enqueue_child_triggers(cycle)
    else:
        cycle.status = GoalCycleStatus.JUDGING
    await db.commit()
    await goal_service.emit_updated(cycle.goal_id)
    return True


async def _claim_terminal_cycle() -> tuple[UUID, UUID] | None:
    db = get_db()
    now = datetime.now(timezone.utc)
    cycle = await db.scalar(
        select(GoalCycle)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .join(Task, Task.id == GoalCycle.task_id)
        .options(
            selectinload(GoalCycle.goal).selectinload(Goal.agent),
            selectinload(GoalCycle.goal).selectinload(Goal.referrer_agent),
            selectinload(GoalCycle.task),
        )
        .where(
            GoalCycle.verdict.is_(None),
            GoalCycle.status.in_(
                (GoalCycleStatus.RUNNING, GoalCycleStatus.JUDGING)
            ),
            Task.status.in_(_TERMINAL_TASK_STATUSES),
            or_(
                GoalCycle.lease_token.is_(None),
                GoalCycle.lease_expires_at <= now,
            ),
        )
        .order_by(Task.updated_at.asc(), GoalCycle.created_at.asc())
        .with_for_update(skip_locked=True, of=GoalCycle)
        .limit(1)
        .execution_options(include_historized=True)
    )
    if cycle is None or cycle.task is None:
        return None

    cycle.task_finished_at = await _task_finished_at(cycle.task)
    cycle.task_cost = float(cycle.task.cost or 0.0)
    goal = cycle.goal
    if goal.status == GoalStatus.COMPLETED:
        cycle.status = GoalCycleStatus.DECIDED
        cycle.verdict = GoalVerdict.STOP
        cycle.reason = "The Goal was stopped manually before post-task evaluation."
        cycle.progress_changed = None
        cycle.judge_finished_at = now
        cycle.clear_lease()
        await _release_cycle_task_retention(cycle)
        await goal_service.enqueue_child_triggers(cycle)
        await db.commit()
        await goal_service.emit_updated(goal.id)
        return None

    token = uuid4()
    cycle.status = GoalCycleStatus.JUDGING
    cycle.judge_attempt_count += 1
    cycle.judge_started_at = now
    cycle.lease_token = token
    cycle.lease_owner = _WORKER_ID
    cycle.lease_expires_at = now + timedelta(seconds=_JUDGE_LEASE_SECONDS)
    cycle.error = None
    await db.commit()
    return cycle.id, token


async def _load_claim(cycle_id: UUID) -> tuple[GoalCycle, Goal, Task]:
    cycle = await get_db().scalar(
        select(GoalCycle)
        .options(
            selectinload(GoalCycle.goal)
            .selectinload(Goal.agent)
            .selectinload(Agent.title),
            selectinload(GoalCycle.goal)
            .selectinload(Goal.referrer_agent)
            .selectinload(Agent.title),
            selectinload(GoalCycle.task),
        )
        .where(GoalCycle.id == cycle_id)
        .execution_options(include_historized=True)
    )
    if cycle is None or cycle.task is None:
        raise LookupError(f"Goal cycle {cycle_id} or its Task no longer exists.")
    return cycle, cycle.goal, cycle.task


async def _restore_legacy_cycle_requester(goal: Goal, task: Task) -> None:
    """Persist a Goal's frozen requester on a cycle Task created before that snapshot."""

    if task.requester_user_id is not None:
        return
    if (
        goal.requester_user_id is None
        and goal.referrer_type == GoalReferrerType.MESSENGER
    ):
        await goal_service.assert_referrer_available(goal)
    requester_user_id = goal.requester_user_id or (
        goal.created_by if goal.referrer_type == GoalReferrerType.AGENT else None
    )
    if requester_user_id is None:
        return
    task.requester_user_id = requester_user_id
    await get_db().commit()


async def _lock_goal_and_cycle(cycle_id: UUID) -> tuple[Goal, GoalCycle] | None:
    """Lock command-shared Goal state before its cycle to avoid lock-order inversions."""

    db = get_db()
    goal_id = await db.scalar(
        select(GoalCycle.goal_id).where(GoalCycle.id == cycle_id)
    )
    if goal_id is None:
        return None
    goal = await db.scalar(select(Goal).where(Goal.id == goal_id).with_for_update())
    if goal is None:
        return None
    cycle = await db.scalar(
        select(GoalCycle)
        .where(GoalCycle.id == cycle_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if cycle is None:
        return None
    return goal, cycle


async def _finish_judgement(
    cycle_id: UUID,
    token: UUID,
    judgement: GoalJudgement,
    *,
    expected_goal_revision: int,
    expected_tracking_revision: int | None = None,
    cost: float,
    llm_id: int | None,
) -> None:
    db = get_db()
    locked = await _lock_goal_and_cycle(cycle_id)
    if locked is None:
        return
    goal, cycle = locked
    if cycle.lease_token != token:
        return
    now = datetime.now(timezone.utc)
    action = GoalVerdict(judgement.action)
    if goal.status == GoalStatus.COMPLETED:
        action = GoalVerdict.STOP
        reason = "The Goal was stopped manually while its post-task evaluation was running."
    elif goal.revision != expected_goal_revision or (expected_tracking_revision is not None and await get_goal_document_store().revision(goal.tracking_document_id) != expected_tracking_revision):
        cycle.status = GoalCycleStatus.RUNNING
        cycle.judge_cost += max(0.0, float(cost))
        cycle.judge_llm_id = llm_id
        cycle.judge_finished_at = now
        cycle.error = None
        cycle.clear_lease()
        await db.commit()
        await goal_service.emit_updated(goal.id)
        logger.info(
            "Goal {} changed from revision {} to {} during judgement; verdict discarded",
            goal.id,
            expected_goal_revision,
            goal.revision,
        )
        return
    else:
        reason = judgement.reason

    cycle.status = GoalCycleStatus.DECIDED
    cycle.verdict = action
    cycle.reason = reason
    cycle.progress_changed = judgement.progress.changed
    cycle.progress_summary = judgement.progress.summary
    cycle.evidence = judgement.progress.evidence
    cycle.continuation_context = None
    cycle.judge_cost += max(0.0, float(cost))
    cycle.judge_llm_id = llm_id
    cycle.judge_finished_at = now
    cycle.error = None
    cycle.clear_lease()
    await _release_cycle_task_retention(cycle)
    await goal_service.enqueue_child_triggers(cycle)

    goal.last_error = None
    if action == GoalVerdict.STOP:
        goal.status = GoalStatus.COMPLETED
        goal.completed_at = now
        goal.next_cycle_at = None
        goal.manual_run_requested_at = None
        goal.pause_reason = None
    else:
        goal.completed_at = None
        finished_at = cycle.task_finished_at or now
        if cycle.trigger_kind != GoalCycleTriggerKind.RELATIONAL:
            goal.next_cycle_at = (
                next_cycle_at(finished_at, goal.cycle_delay_seconds)
                if goal.cycle_delay_seconds is not None
                else None
            )
    await get_goal_document_store().update(
        goal.tracking_document_id,
        content=judgement.tracking_content,
        expected_revision=expected_tracking_revision,
    )
    await db.commit()
    await goal_service.emit_updated(goal.id)
    logger.info(
        "Goal {} cycle {} judged {} (task=${:.6f}, judge=${:.6f})",
        goal.id,
        cycle.sequence,
        action.value,
        cycle.task_cost,
        cycle.judge_cost,
    )


async def _fail_judgement(
    cycle_id: UUID,
    token: UUID,
    exc: BaseException,
    *,
    llm_id: int | None = None,
) -> None:
    db = get_db()
    locked = await _lock_goal_and_cycle(cycle_id)
    if locked is None:
        return
    goal, cycle = locked
    if cycle.lease_token != token:
        return
    if cycle.task_id is not None and cycle.judge_started_at is not None:
        attempt_cost = await db.scalar(
            select(func.coalesce(func.sum(LLMCall.cost), 0.0)).where(
                LLMCall.task_id == cycle.task_id,
                LLMCall.started_at >= cycle.judge_started_at,
            )
        )
        cycle.judge_cost += max(0.0, float(attempt_cost or 0.0))
    if llm_id is not None:
        cycle.judge_llm_id = llm_id
    now = datetime.now(timezone.utc)
    error = f"{type(exc).__name__}: {exc}"[:4000]
    cycle.judge_finished_at = now
    cycle.clear_lease()
    if goal.status == GoalStatus.COMPLETED:
        cycle.status = GoalCycleStatus.DECIDED
        cycle.verdict = GoalVerdict.STOP
        cycle.reason = "The Goal was stopped manually while its evaluation was running."
        cycle.error = error
        await _release_cycle_task_retention(cycle)
        await goal_service.enqueue_child_triggers(cycle)
    else:
        cycle.status = GoalCycleStatus.ERROR
        cycle.error = error
        goal.last_error = error
        goal.next_cycle_at = None
    if goal.status not in (GoalStatus.COMPLETED, GoalStatus.PAUSED):
        goal.status = GoalStatus.ERROR
    await db.commit()
    await goal_service.emit_updated(goal.id)
    logger.error("Goal {} cycle {} judgement failed: {}", goal.id, cycle.sequence, error)


async def process_terminal_cycle(tracking_llm: LLM | None = None) -> bool:
    prepared = await _prepare_terminal_cycle()
    claim = await _claim_terminal_cycle()
    if claim is None:
        return prepared
    cycle_id, token = claim
    llm_id: int | None = None
    try:
        cycle, goal, task = await _load_claim(cycle_id)
        await _restore_legacy_cycle_requester(goal, task)
        if tracking_llm is None:
            tracking_llm = await goal_service.get_tracking_llm(goal.agent_id)
        if tracking_llm is None:
            raise RuntimeError("No Goal model is configured for this agent profile.")
        expected_goal_revision = goal.revision
        expected_tracking_revision = await get_goal_document_store().revision(goal.tracking_document_id)
        llm_id = tracking_llm.id
        result = await run_structured(
            llm=tracking_llm,
            output_type=GoalJudgement,
            prompt=await _judge_prompt(goal, cycle, task),
            system_prompt=_TRACKING_SYSTEM_PROMPT,
            task_id=task.id,
            agent_id=goal.agent_id,
            temperature=0.0,
            request_limit=2,
            output_retries=1,
            purpose=LLMCallPurpose.GOAL_TRACKING,
            model_field=model_usages.GOAL,
        )
        recorded_cost = await _recorded_tracking_cost(
            task.id,
            cycle.judge_started_at,
            result.cost,
        )
        await _finish_judgement(
            cycle_id,
            token,
            result.output,
            expected_goal_revision=expected_goal_revision,
            expected_tracking_revision=expected_tracking_revision,
            cost=recorded_cost,
            llm_id=llm_id,
        )
    except Exception as exc:
        await get_db().rollback()
        await _fail_judgement(cycle_id, token, exc, llm_id=llm_id)
    return True


async def _agent_has_pending_work(agent_id: int, now: datetime) -> bool:
    pending = await get_db().scalar(
        select(
            exists().where(
                Task.agent_id == agent_id,
                Task.status.in_(_RUNNABLE_TASK_STATUSES),
                Task.deleted_at.is_(None),
                or_(
                    Task.paused.is_(False),
                    (
                        Task.lease_token.is_not(None)
                        & (Task.lease_expires_at > now)
                    ),
                ),
            )
        )
    )
    return bool(pending)


async def _cycle_task_objective(goal: Goal, sequence: int) -> str:
    markdown = await goal_service.read_markdown(goal)
    sections = [
        "You are advancing a long-running Goal through one concrete work cycle.",
        f"GOAL TITLE:\n{goal.title}",
        f"GOAL DESCRIPTION:\n{markdown.description}",
        (
            "DURABLE GOAL TRACKING (HTML, shared by every cycle):\n"
            + (markdown.tracking or "(No tracking has been recorded yet.)")
        ),
        _referrer_context(goal),
        f"CYCLE:\n{sequence}",
        (
            "Perform useful work now and advance the Goal materially. Use the available tools "
            "when appropriate. Do not stop at merely proposing what a later cycle could do. "
            "Treat the durable tracking above as the shared source of truth. Explicitly identify "
            "new facts, corrections, completed work, evidence, blockers, and remaining issues so "
            "the post-cycle tracking step can update the full HTML document accurately."
        ),
    ]
    return "\n\n".join(sections)


async def start_due_cycle(
    tracking_llm: LLM | None = None,
    *,
    manual_only: bool = False,
) -> bool:
    """Create one due Goal Task when its own schedule and agent availability allow it."""

    db = get_db()
    now = datetime.now(timezone.utc)
    open_cycle = exists().where(
        GoalCycle.goal_id == Goal.id,
        GoalCycle.verdict.is_(None),
    )
    pending_relational_trigger = exists().where(
        GoalCycleTrigger.goal_id == Goal.id,
        GoalCycleTrigger.consumed_cycle_id.is_(None),
    )
    temporal_due = and_(
        Goal.cycle_delay_seconds.is_not(None),
        Goal.next_cycle_at.is_not(None),
        Goal.next_cycle_at <= now,
    )
    candidate_query = select(Goal.id).where(
        Goal.status == GoalStatus.ACTIVE,
        ~open_cycle,
        or_(
            Goal.manual_run_requested_at.is_not(None),
            temporal_due,
            pending_relational_trigger,
        ),
    )
    if manual_only:
        candidate_query = candidate_query.where(
            Goal.manual_run_requested_at.is_not(None)
        )
    candidate_query = candidate_query.order_by(
        Goal.manual_run_requested_at.is_(None),
        Goal.manual_run_requested_at.asc(),
        Goal.next_cycle_at.asc().nullslast(),
        Goal.created_at.asc(),
    )
    candidate_ids = list((await db.scalars(candidate_query)).all())
    did_work = False
    for goal_id in candidate_ids:
        locked_query = (
            select(Goal)
            .options(
                selectinload(Goal.agent),
                selectinload(Goal.referrer_agent),
            )
            .where(
                Goal.id == goal_id,
                Goal.status == GoalStatus.ACTIVE,
                ~open_cycle,
                or_(
                    Goal.manual_run_requested_at.is_not(None),
                    temporal_due,
                    pending_relational_trigger,
                ),
            )
        )
        if manual_only:
            locked_query = locked_query.where(
                Goal.manual_run_requested_at.is_not(None)
            )
        goal = await db.scalar(
            locked_query.with_for_update(skip_locked=True)
        )
        if goal is None:
            await db.rollback()
            continue
        relational_trigger = await db.scalar(
            select(GoalCycleTrigger)
            .where(
                GoalCycleTrigger.goal_id == goal.id,
                GoalCycleTrigger.consumed_cycle_id.is_(None),
            )
            .order_by(
                GoalCycleTrigger.created_at.asc(), GoalCycleTrigger.id.asc()
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        is_manual = goal.manual_run_requested_at is not None
        selected_relational_trigger = None if is_manual else relational_trigger
        is_temporal = (
            goal.cycle_delay_seconds is not None
            and goal.next_cycle_at is not None
            and goal.next_cycle_at <= now
        )
        if manual_only and not is_manual:
            await db.rollback()
            continue
        if not is_manual and selected_relational_trigger is None and not is_temporal:
            await db.rollback()
            continue
        if (
            not is_manual
            and not settings_service.is_goal_processing_allowed(goal, now=now)
        ):
            await db.rollback()
            continue
        if goal.agent is None:
            goal.status = GoalStatus.ERROR
            goal.next_cycle_at = None
            goal.manual_run_requested_at = None
            goal.last_error = (
                f"Goal owner agent {goal.agent_id} is deleted or unavailable."
            )
            await db.commit()
            await goal_service.emit_updated(goal.id)
            logger.warning(
                "Goal {} stopped because agent {} is unavailable",
                goal.id,
                goal.agent_id,
            )
            did_work = True
            continue
        if (
            tracking_llm is None
            and await goal_service.get_tracking_llm(goal.agent_id) is None
        ):
            await db.rollback()
            continue
        try:
            await goal_service.assert_referrer_available(goal)
        except goal_service.GoalConflictError as exc:
            goal.status = GoalStatus.ERROR
            goal.next_cycle_at = None
            goal.manual_run_requested_at = None
            goal.last_error = str(exc)
            await db.commit()
            await goal_service.emit_updated(goal.id)
            logger.warning("Goal {} cannot contact its referrer: {}", goal.id, exc)
            did_work = True
            continue
        if not await try_lock_agent(db, goal.agent_id):
            await db.rollback()
            continue
        if await _agent_has_pending_work(goal.agent_id, now):
            await db.rollback()
            continue

        previous = await db.scalar(
            select(GoalCycle)
            .where(GoalCycle.goal_id == goal.id)
            .order_by(GoalCycle.sequence.desc())
            .limit(1)
        )
        sequence = (previous.sequence if previous is not None else 0) + 1
        cycle_id = uuid4()
        task_data: dict[str, object] = {
            "goal_cycle_id": str(cycle_id),
            "goal_sequence": sequence,
            "goal_referrer_type": (
                goal.referrer_type.value if goal.referrer_type is not None else None
            ),
            "goal_referrer_agent_id": goal.referrer_agent_id,
            "goal_referrer_user_id": goal.referrer_user_id,
            "goal_referrer_display_name": goal.referrer_display_name,
            "goal_referrer_platform": goal.referrer_platform,
            "goal_trigger_kind": (
                GoalCycleTriggerKind.MANUAL.value
                if is_manual
                else GoalCycleTriggerKind.RELATIONAL.value
                if selected_relational_trigger is not None
                else GoalCycleTriggerKind.TEMPORAL.value
            ),
            "goal_source_cycle_id": (
                str(selected_relational_trigger.source_cycle_id)
                if selected_relational_trigger is not None
                else None
            ),
        }
        if goal.referrer_connection_id is not None:
            task_data["messenger_connection_id"] = goal.referrer_connection_id
        task = task_service.build(
            TaskCreate(
                label=f"{goal.title} — cycle {sequence}"[:400],
                objective=await _cycle_task_objective(goal, sequence),
                agent_id=goal.agent_id,
                goal_id=goal.id,
                messenger_connection_id=goal.referrer_connection_id,
                data=task_data,
            )
        )
        task.requester_user_id = goal.requester_user_id or (
            goal.created_by
            if goal.referrer_type == GoalReferrerType.AGENT
            else None
        )
        task_service.retain(task, _GOAL_JUDGEMENT_RETENTION)
        cycle = GoalCycle(
            id=cycle_id,
            goal_id=goal.id,
            sequence=sequence,
            status=GoalCycleStatus.RUNNING,
            trigger_kind=(
                GoalCycleTriggerKind.MANUAL
                if is_manual
                else GoalCycleTriggerKind.RELATIONAL
                if selected_relational_trigger is not None
                else GoalCycleTriggerKind.TEMPORAL
            ),
            source_cycle_id=(
                selected_relational_trigger.source_cycle_id
                if selected_relational_trigger is not None
                else None
            ),
            task=task,
        )
        db.add_all([task, cycle])
        await db.flush()
        if selected_relational_trigger is not None:
            selected_relational_trigger.consumed_cycle_id = cycle_id
            selected_relational_trigger.consumed_at = now
        else:
            goal.next_cycle_at = None
        if is_manual:
            goal.manual_run_requested_at = None
        goal.last_error = None
        await db.commit()
        await db.refresh(task)
        await task_service.publish_created(task)
        await goal_service.emit_updated(goal.id)

        from app.task import scheduler

        scheduler.wake(task.id)
        logger.info("Goal {} created task {} for cycle {}", goal.id, task.id, sequence)
        return True

    return did_work


async def process_goals() -> None:
    """Finish one launched cycle, then start scheduled Goal activity when allowed."""

    from .referrer_wait import process_due_referrer_wait

    await process_terminal_cycle()
    settings = await settings_service.get_settings()
    if not settings.is_active:
        if settings.inactive_reason == "OUTSIDE_SCHEDULE":
            await start_due_cycle(manual_only=True)
        return
    await process_due_referrer_wait()
    await start_due_cycle()
