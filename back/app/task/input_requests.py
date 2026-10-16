"""Suspend an existing execution for domain-owned input, without a child Task."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm.attributes import get_history

from core.database import get_db

from . import task_service
from .models import Task, TaskStatus
from .workflow import TaskEvent, transition

INPUT_KEY = "input_request"
INPUT_CONTEXT = "input_context"


async def _owned_task(task_id: UUID, agent_id: int) -> Task:
    task = await task_service.get_by_id(task_id, for_update=True)
    if task is None or task.agent_id != agent_id:
        raise PermissionError("An owned Task is required")
    if task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR} or task.cancel_requested:
        raise ValueError("This Task is no longer awaiting input")
    return task


async def request_task_input(*, task_id: UUID, agent_id: int, request_key: str) -> None:
    """Stage the wait in the caller's transaction with its domain request."""
    task = await _owned_task(task_id, agent_id)
    previous = (task.data or {}).get(INPUT_KEY, {})
    if previous.get("status") == "pending" and previous.get("key") != request_key:
        raise ValueError("This Task already awaits another input")
    run_id = (task.data or {}).get("_agent_run_identity", {}).get("request_run_id")
    task.data = {**(task.data or {}), INPUT_KEY: {"key": request_key, "status": "pending",
        **({"request_run_id": run_id} if run_id else {})}}
    # The current turn still owns its lease until it returns. Pausing EXEC here
    # would make the heartbeat revoke that lease while the tool reply is in flight.
    if task.status != TaskStatus.EXEC:
        task_service.suspend(task, task_service.PAUSE_INPUT)


async def answer_task_input(*, task_id: UUID, agent_id: int, request_key: str, response: str) -> None:
    """Stage a reply and wake only the input suspension, preserving human holds."""
    task = await _owned_task(task_id, agent_id)
    marker: dict[str, Any] = (task.data or {}).get(INPUT_KEY, {})
    if marker.get("key") != request_key:
        raise PermissionError("This is not the expected Task input")
    if marker.get("status") != "pending":
        if marker.get("response") != response:
            raise ValueError("This input already has a different response")
        return
    run_id = marker.get("request_run_id") or (task.data or {}).get("_agent_run_identity", {}).get("request_run_id")
    if run_id:
        marker = {**marker, "request_run_id": run_id}
    previous = str((task.data or {}).get(INPUT_CONTEXT) or "")
    context = "\n\n".join(part for part in (previous, response) if part)
    if len(context.encode("utf-8")) > 2_000_000:
        raise ValueError("Task input context exceeds its 2 MB limit")
    task.data = {**(task.data or {}),
        INPUT_KEY: {**marker, "status": "answered" if task.status == TaskStatus.EXEC else "delivered", "response": response},
        INPUT_CONTEXT: context}
    if task.status != TaskStatus.EXEC:
        task_service.release(task, task_service.PAUSE_INPUT)


async def consume_task_input(*, task_id: UUID, agent_id: int, request_key: str) -> None:
    """The running execution already used a reply that arrived before it finished."""
    task = await _owned_task(task_id, agent_id)
    marker: dict[str, Any] = (task.data or {}).get(INPUT_KEY, {})
    if marker.get("key") == request_key and marker.get("status") in {"answered", "delivered"}:
        task.data = {**(task.data or {}), INPUT_KEY: {**marker, "status": "delivered", "consumed": True}}
        task_service.release(task, task_service.PAUSE_INPUT)


async def replace_legacy_input_wait(*, task_id: UUID, agent_id: int,
                                  request_key: str, wait_task_id: UUID) -> None:
    """Adopt a historical inert wait without resuming or recreating any work."""
    task = await _owned_task(task_id, agent_id)
    wait = await task_service.get_by_id(wait_task_id, for_update=True)
    if (wait is None or wait.parent_id != task_id or wait.source_task_id != task_id
            or wait.agent_id != agent_id or wait.ai or wait.plan is not None
            or wait.lease_token is not None or wait.status != TaskStatus.DISPATCH
            or (wait.data or {}).get("awaiting_reply", {}).get("kind") != "human_input"
            or await task_service.get_children(wait.id)):
        raise ValueError("The historical human input wait cannot be replaced")
    await request_task_input(task_id=task_id, agent_id=agent_id, request_key=request_key)
    await task_service.request_cancellation(wait)
    wait.soft_delete()
    from .collab import is_coordination_child
    others = [child for child in await task_service.get_children(task_id)
        if child.id != wait_task_id and is_coordination_child(child)
        and not (child.data or {}).get("fanned_in")]
    if not others:
        task_service.release(task, task_service.PAUSE_AWAIT)


async def suspend_on_pending_input(task: Task) -> bool:
    """Fold a separately committed tool request/reply before accepting a final result."""
    result = task.get_execution_result()
    result_run_id = result.metadata.get("run_id") if result is not None else None
    # The facade has already applied the driver's result to this ORM instance.
    # Preserve that local delta (including checkpoint/identity removal) while
    # loading replies or user holds committed by another session in the meantime.
    history = get_history(task, "data")
    before = cast(dict[str, Any], history.deleted[0] or {}) if history.deleted else {}
    local = dict(task.data or {})
    removed = set(before) - set(local) if history.has_changes() else set[str]()
    patch = {key: value for key, value in local.items() if key not in before or before[key] != value} if history.has_changes() else {}
    # Non-key updates must coexist with the FK locks held by pending LLM traces.
    await get_db().refresh(task, with_for_update={"key_share": True})
    if removed or patch:
        merged = {key: value for key, value in (task.data or {}).items() if key not in removed}
        task.data = {**merged, **patch}
    marker: dict[str, Any] = (task.data or {}).get(INPUT_KEY, {})
    reconciled_question_turn = (marker.get("status") == "delivered" and not marker.get("consumed")
        and bool(marker.get("request_run_id")) and marker["request_run_id"] == result_run_id)
    if marker.get("status") not in {"pending", "answered"} and not reconciled_question_turn:
        return False
    if task.status == TaskStatus.EXEC:
        transition(task, TaskEvent.INTERRUPT_EXECUTION)
    if marker["status"] == "pending":
        task_service.suspend(task, task_service.PAUSE_INPUT)
    else:
        task.data = {**(task.data or {}), INPUT_KEY: {**marker, "status": "delivered"}}
        task_service.release(task, task_service.PAUSE_INPUT)
    return True
