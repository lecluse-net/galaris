"""Fresh-context Goal reviews are ordinary durable Tasks, with the same owner and rights."""

from html import escape
import hashlib
import json

from sqlalchemy import func, select

from app.task import Task, TaskCreate, TaskStatus, initialize_scope, task_service
from core.database import get_db

from .document_store import get_goal_document_store
from .models import Goal, GoalCycle, GoalCycleStatus
from .schemas import GoalJudgement


REVIEW_KEY = "goal_review"
RETENTION_REASON = "goal_judgement"
STAGNATION_CYCLES = 3


def work_fingerprint(task: Task) -> str:
    """Accounting and trace updates must not invalidate unchanged work."""
    result = task.get_execution_result()
    return hashlib.sha256(json.dumps({
        "objective": task.objective, "status": task.status.value,
        "result": result.result if result is not None else task.feedback or task.last_error or "",
    }, sort_keys=True).encode()).hexdigest()


async def stagnant(cycle: GoalCycle, judgement: GoalJudgement) -> bool:
    if judgement.progress.changed:
        return False
    previous = list((await get_db().scalars(select(GoalCycle).where(
        GoalCycle.goal_id == cycle.goal_id,
        GoalCycle.sequence < cycle.sequence,
        GoalCycle.status == GoalCycleStatus.DECIDED,
    ).order_by(GoalCycle.sequence.desc()).limit(STAGNATION_CYCLES - 1))).all())
    return len(previous) == STAGNATION_CYCLES - 1 and all(
        item.progress_changed is False and item.review_task_id is None for item in previous
    )


async def current_review(goal: Goal, cycle: GoalCycle) -> Task | None:
    if cycle.review_task_id is None:
        return None
    task = await get_db().scalar(select(Task).where(Task.id == cycle.review_task_id)
        .execution_options(include_historized=True, populate_existing=True))
    if task is None or task.deleted_at is not None:
        raise RuntimeError("The Goal review Task is missing or deleted; retry after recovery.")
    snapshot = (task.data or {}).get(REVIEW_KEY, {})
    revision = await get_goal_document_store().revision(goal.tracking_document_id)
    work = await get_db().get(Task, cycle.task_id) if cycle.task_id is not None else None
    if (snapshot.get("goal_revision") != goal.revision
            or snapshot.get("tracking_revision") != revision
            or work is None or snapshot.get("work_fingerprint") != work_fingerprint(work)):
        # Never replace an in-flight review: let its normal Task settle first.
        if not task_service.has_terminal_outcome(task):
            return task
        task_service.release_retention(task, RETENTION_REASON)
        cycle.review_task_id = None
        await get_db().flush()
        return None
    return task


async def release_review(cycle: GoalCycle) -> None:
    if cycle.review_task_id is not None:
        task = await get_db().scalar(select(Task).where(Task.id == cycle.review_task_id)
            .with_for_update().execution_options(include_historized=True, populate_existing=True))
        if task is not None:
            task_service.release_retention(task, RETENTION_REASON)


async def cancel_review(cycle: GoalCycle) -> None:
    """A human closing the Goal also stops its now unnecessary review."""
    if cycle.review_task_id is not None:
        task = await get_db().scalar(select(Task).where(Task.id == cycle.review_task_id)
            .with_for_update().execution_options(populate_existing=True))
        if task is not None and not task_service.has_terminal_outcome(task):
            await task_service.request_cancellation(task)


async def review_cost(cycle: GoalCycle) -> float:
    """Include superseded reviews without charging their calls as judge calls."""
    return float(await get_db().scalar(select(func.coalesce(func.sum(Task.cost), 0.0)).where(
        Task.goal_id == cycle.goal_id,
        Task.parent_id == cycle.task_id,
        Task.data[REVIEW_KEY]["cycle"].as_string() == str(cycle.id),
    ).execution_options(include_historized=True)) or 0.0)


async def create_review(
    goal: Goal, cycle: GoalCycle, source: Task, judgement: GoalJudgement,
) -> Task:
    """Called under Goal → cycle locks; caller commits task and pointer atomically."""
    revision = await get_goal_document_store().revision(goal.tracking_document_id)
    tracking = await get_goal_document_store().read(goal.tracking_document_id)
    execution = source.get_execution_result()
    result = execution.result if execution is not None else source.feedback or source.last_error or ""
    objective = (
        "<p>Independently review this Goal's work and strategy in a fresh context. "
        "Inspect the actual authorized resources and use appropriate read or test tools. "
        "Do not edit deliverables, send messages or execute business actions merely to "
        "review them. A read denial is a limit, never permission to bypass it. "
        "Assess the original outcome, useful improvements, overlooked approaches, "
        "uncertainty and completion criteria. Do not accept the previous author's claims "
        "as verified facts. Report concrete observations, resource revisions, tool evidence, "
        "remaining gaps and a useful next action or resumption condition. "
        "Do not contact the referrer to ask how to solve the Goal.</p>"
        f"<p>Goal: galaris://goal/{goal.id}; work: galaris://task/{source.id}</p>"
        f"<h2>Original outcome</h2>{goal.description}"
        f"<h2>Current tracking</h2>{tracking}"
        f"<h2>Work result (unverified claims)</h2><pre>{escape(result[:30000])}</pre>"
        f"<h2>Reason for review</h2><p>{escape(judgement.reason)}</p>"
        f"<h2>Proposed synthesis (unverified)</h2>{judgement.tracking_content}"
    )
    task = task_service.build(TaskCreate(
        label=f"{goal.title} — review {cycle.sequence}"[:400],
        objective=objective, agent_id=goal.agent_id, goal_id=goal.id,
        parent_id=source.id, source_task_id=source.id,
        data={REVIEW_KEY: {"cycle": str(cycle.id), "goal_revision": goal.revision,
                          "tracking_revision": revision, "work_fingerprint": work_fingerprint(source)},
              "_original_demand": goal.description or goal.title},
    ))
    task.requester_user_id = source.requester_user_id
    await initialize_scope(task, source_reference=f"galaris://goal/{goal.id}")
    task_service.retain(task, RETENTION_REASON)
    get_db().add(task)
    await get_db().flush()
    cycle.review_task_id = task.id
    return task


def successful_review(task: Task | None) -> bool:
    return task is not None and task.deleted_at is None and task.status == TaskStatus.SUCCESS
