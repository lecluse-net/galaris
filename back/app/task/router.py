from core.util import require_editorial_client
from fastapi import Depends
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from typing import Any, List, cast
from uuid import UUID

from core.authorize import authorize
from core.authorize import Privileges
from core.i18n import render_prompt, tr
from core.database import get_db
from app.agent import AgentManagementScope, current_management_scope

from .schemas import (
    Task as TaskSchema,
    TaskCreate,
    TaskCommand,
    TaskUpdate,
    TaskFull,
    TaskPage,
    TaskBudget,
)
from . import task_service
from .activity_snapshot import TaskActivityQuery, TaskActivitySnapshot, activity_snapshots, readable_activity_tasks

from loguru import logger

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _detail(key: str) -> str:
    return await tr(f"task_api.errors.{key}")


async def _task_scope_or_404(task_id: UUID) -> tuple[Any, AgentManagementScope]:
    scope = await current_management_scope()
    task = await task_service.get_by_id(task_id)
    if task is None or not scope.allows(task.agent_id):
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    return task, scope


async def _require_agent_scope(
    scope: AgentManagementScope,
    agent_id: int | None,
) -> int:
    if not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    assert agent_id is not None
    return agent_id


# Task CRUD

@router.get("", response_model=List[TaskSchema])
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_tasks(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    agent_id: int | None = None,
    goal_id: UUID | None = None,
):
    """List all tasks."""
    scope = await current_management_scope()
    tasks = await task_service.get_all(
        skip=skip,
        limit=limit,
        agent_id=agent_id,
        goal_id=goal_id,
        agent_ids=scope.agent_ids,
    )
    return tasks


@router.get("/recent", response_model=TaskPage)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_recent_tasks(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    agent_id: int | None = None,
    goal_id: UUID | None = None,
    topic_id: UUID | None = None,
    q: str | None = None,
    errors_only: bool = False,
    paused_only: bool = False,
    active: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """List tasks from newest to oldest by creation date across all statuses."""
    scope = await current_management_scope()
    tasks = await task_service.get_recent(
        skip=skip,
        limit=limit,
        agent_id=agent_id,
        goal_id=goal_id,
        topic_id=topic_id,
        search=q,
        errors_only=errors_only,
        paused_only=paused_only,
        active=active,
        date_from=date_from,
        date_to=date_to,
        agent_ids=scope.agent_ids,
    )
    _, summary = await task_service.summarize_recent(
        agent_id=agent_id,
        goal_id=goal_id,
        topic_id=topic_id,
        search=q,
        date_from=date_from,
        date_to=date_to,
        agent_ids=scope.agent_ids,
    )
    page_total = await task_service.count_recent(
        agent_id=agent_id,
        goal_id=goal_id,
        topic_id=topic_id,
        search=q,
        errors_only=errors_only,
        paused_only=paused_only,
        active=active,
        date_from=date_from,
        date_to=date_to,
        agent_ids=scope.agent_ids,
    )
    return TaskPage(
        items=[TaskSchema.model_validate(t) for t in tasks],
        total=page_total,
        summary=summary,
    )


@router.get("/active", response_model=List[TaskSchema])
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_active_tasks(
    limit: int = Query(default=10, ge=1, le=50),
) -> List[TaskSchema]:
    """List tasks that are currently being processed."""
    scope = await current_management_scope()
    tasks = await task_service.get_active(limit=limit, agent_ids=scope.agent_ids)
    return [TaskSchema.model_validate(task) for task in tasks]


@router.post("/activity")
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_task_activity(query: TaskActivityQuery) -> list[TaskActivitySnapshot]:
    scope = await current_management_scope()
    return await activity_snapshots(await readable_activity_tasks(query.task_ids, scope.agent_ids))


@router.get("/{task_id}", response_model=TaskSchema)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_task(
    task_id: UUID,
):
    """Get a task and its assignments by ID."""
    task, _ = await _task_scope_or_404(task_id)
    return task


@router.get("/{task_id}/budget", response_model=TaskBudget)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_task_budget(task_id: UUID) -> TaskBudget:
    """Inspect optional admission limits within the same task authorization scope."""
    from .budget import inspect_budget

    task, _ = await _task_scope_or_404(task_id)
    return await inspect_budget(get_db(), task)


@router.post("", dependencies=[Depends(require_editorial_client)], response_model=TaskSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.TASK_EDIT)
async def create_task(
    task: TaskCreate,
):
    """Create a task."""
    scope = await current_management_scope()
    await _require_agent_scope(scope, task.agent_id)
    if task.requester_agent_id is not None:
        await _require_agent_scope(scope, task.requester_agent_id)
    for linked_id in (task.parent_id, task.source_task_id):
        if linked_id is not None:
            await _task_scope_or_404(linked_id)
    if task.goal_id is not None:
        from app.goal import goal_service

        goal = await goal_service.get_detail(task.goal_id)
        if goal is None or not scope.allows(goal.agent_id):
            raise HTTPException(status_code=404, detail=await _detail("not_found"))
    new_task = await task_service.create(task)
    logger.debug(f"Task created: {new_task.label}")
    return new_task


@router.put("/{task_id}", dependencies=[Depends(require_editorial_client)], response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def update_task(
    task_id: UUID,
    task_update: TaskUpdate,
):
    """Update an existing task."""
    try:
        _, scope = await _task_scope_or_404(task_id)
        if "agent_id" in task_update.model_fields_set:
            await _require_agent_scope(scope, task_update.agent_id)
        task = await task_service.update(task_id, task_update)
    except task_service.TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.debug(f"Task updated: {task.label}")
    return task


@router.post("/{task_id}/retry", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def retry_task(task_id: UUID, command: TaskCommand):
    """Explicitly retry a failed task from its execution checkpoint."""
    from app.task.runner import go_next

    await _task_scope_or_404(task_id)

    try:
        task = await task_service.retry(task_id, command.expected_revision)
    except (task_service.TaskConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    raw_recovery = (
        task.data.get("delivery_recovery") if isinstance(task.data, dict) else None
    )
    recovery = (
        cast(dict[str, Any], raw_recovery)
        if isinstance(raw_recovery, dict)
        else None
    )
    if recovery is not None and recovery.get("status") == "running":
        try:
            recovery_child_id = UUID(str(recovery.get("child_task_id") or ""))
        except ValueError:
            recovery_child_id = None
        if recovery_child_id is not None:
            go_next(recovery_child_id, fast=True)
    go_next(task.id, fast=True)
    logger.info("Task retry requested: {}", task.id)
    return task


@router.post("/{task_id}/cancel", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def cancel_task(task_id: UUID, command: TaskCommand):
    """Explicitly cancel an active task and its in-flight action."""
    await _task_scope_or_404(task_id)
    try:
        task = await task_service.cancel(task_id, command.expected_revision)
    except (task_service.TaskConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.info("Task cancelled: {}", task.id)
    return task


@router.post("/{task_id}/force-terminate", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def force_terminate_task(task_id: UUID, command: TaskCommand):
    """Force a durable terminal state and close directly attached workflows."""
    await _task_scope_or_404(task_id)
    try:
        task = await task_service.force_terminate(
            task_id, command.expected_revision
        )
    except (task_service.TaskConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.warning("Task force-terminated: {}", task.id)
    return task


@router.delete("/cleanup", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.TASK_PURGE)
async def cleanup_tasks():
    """Permanently delete processed tasks only."""
    scope = await current_management_scope()
    await task_service.cleanup_all(agent_ids=scope.agent_ids)
    logger.warning("Processed tasks cleaned up")
    return None


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.TASK_EDIT)
async def delete_task(
    task_id: UUID,
):
    """Stop and soft-delete a task, including an active task."""
    await _task_scope_or_404(task_id)
    try:
        deleted = await task_service.delete(task_id)
    except task_service.TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.debug(f"Task deleted: {task_id}")
    return None


@router.post("/{task_id}/restore", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def restore_task(
    task_id: UUID,
):
    """Restore a soft-deleted task."""
    scope = await current_management_scope()
    task = await task_service.restore(task_id, agent_ids=scope.agent_ids)
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.debug(f"Task restored: {task.label}")
    return task


@router.post("/{task_id}/pause", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def pause_task(
    task_id: UUID,
):
    """Pause a task and its unfinished descendants."""
    await _task_scope_or_404(task_id)
    task = await task_service.pause_tree(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    logger.info(f"Task paused: {task.label}")
    return task


@router.post("/{task_id}/resume", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def resume_task(
    task_id: UUID,
):
    """Resume a task and its unfinished descendants."""
    from app.task.runner import go_next

    await _task_scope_or_404(task_id)
    task = await task_service.resume_tree(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=await _detail("not_found"))
    go_next(task_id, fast=True)
    logger.info(f"Task resumed: {task.label}")
    return task


# Complete task views

@router.get("/{task_id}/full", response_model=TaskFull)
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_task_full(
    task_id: UUID,
):
    """Get a complete task with flat relationships."""
    task, _ = await _task_scope_or_404(task_id)
    return task


@router.get("/{task_id}/children", response_model=List[TaskSchema])
@authorize(privileges=[Privileges.TASK_ACCESS, Privileges.TASK_EDIT])
async def read_task_children(
    task_id: UUID,
):
    """List a planned task's children in creation order."""
    _, scope = await _task_scope_or_404(task_id)
    return [
        task
        for task in await task_service.get_children(task_id)
        if scope.allows(task.agent_id)
    ]


# Task execution

@router.post("/{task_id}/run", response_model=TaskSchema)
@authorize(privileges=Privileges.TASK_EDIT)
async def run_task(
    task_id: UUID,
):
    """Start or continue processing a non-terminal task."""
    from app.task.models import TaskStatus
    from app.task.runner import go_next

    task, _ = await _task_scope_or_404(task_id)
    if task.status in (TaskStatus.SUCCESS, TaskStatus.ERROR):
        raise HTTPException(
            status_code=400,
            detail=render_prompt(
                await _detail("cannot_restart"),
                status=task.status.value,
            ),
        )
    if task_service.is_held_by_user(task):
        raise HTTPException(
            status_code=400,
            detail=await _detail("paused"),
        )
    await task_service.preempt_running_agent_tasks(task.agent_id, exclude_task_id=task.id)
    # A manual RUN clears internal suspension (waiting for a peer, plan step, or clarification).
    # ``status`` already identifies the resume point, so only automatic pause reasons are cleared.
    if task.paused:
        task_service.clear_pauses(task)
        task = await task_service.save(task)
    go_next(task_id, fast=True)
    logger.info(f"Task run triggered: {task.label} (status={task.status.value})")
    return TaskSchema.model_validate(task)
