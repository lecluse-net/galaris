"""Durable, explicit replacement: admission waits for evidence that its predecessor stopped."""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, or_, select

from core.database import get_db
from app.agent import cancel as cancel_agent_run
from app.agent.contracts import HarnessCancellationReceipt

from .models import Task, TaskAttempt, TaskStatus
from . import task_service

REPLACEMENT_KEY = "_replacement"
_SUCCESSOR_KEY = "_replacement_successor"
_TERMINAL = {TaskStatus.SUCCESS, TaskStatus.ERROR}
_blockers: dict[str, Callable[[], Select[tuple[UUID]]]] = {}


def register_replacement_blocker(key: str, blocked_task_ids: Callable[[], Select[tuple[UUID]]]) -> None:
    """Compose owner-provided coordination evidence without reverse domain imports."""
    _blockers[key] = blocked_task_ids


def replacement_state(task: Task) -> dict[str, Any]:
    raw = (task.data or {}).get(REPLACEMENT_KEY)
    return dict(cast(dict[str, Any], raw)) if isinstance(raw, dict) else {}


def replacement_pending(task: Task) -> bool:
    state = replacement_state(task)
    return bool(state) and state.get("state") != "confirmed"


def _predecessor_matches(predecessor: Task, successor: Task, state: dict[str, Any]) -> bool:
    """A later restart or scope transfer is a new decision, not the requested stop."""
    return (
        predecessor.deleted_at is None
        and predecessor.status in _TERMINAL
        and predecessor.agent_id == successor.agent_id
        and predecessor.messenger_connection_id == successor.messenger_connection_id
        and predecessor.message_group_id == successor.message_group_id
        and (predecessor.data or {}).get("_agent_run_identity") == state.get("run")
        and (predecessor.lease_token is None or str(predecessor.lease_token) == state.get("lease_token"))
    )


async def _has_coordination(task: Task) -> bool:
    if task.goal_id is not None or bool((task.data or {}).get("awaiting_reply")):
        return True
    scope = select(Task.id).where(Task.id == task.id).cte(recursive=True)
    scope = scope.union(select(Task.id).join(scope, Task.parent_id == scope.c.id))
    identifiers = select(scope.c.id)
    child = await get_db().scalar(select(Task.id).where(
        Task.id.in_(identifiers), Task.id != task.id,
        or_(Task.status.not_in(_TERMINAL), Task.lease_token.is_not(None), Task.goal_id.is_not(None)),
    ).limit(1).execution_options(include_historized=True))
    if child is not None:
        return True
    for blocked_ids in _blockers.values():
        blocked = await get_db().scalar(select(Task.id).where(
            Task.id.in_(identifiers), Task.id.in_(blocked_ids()),
        ).limit(1).execution_options(include_historized=True))
        if blocked is not None:
            return True
    return False


async def prepare_replacement(
    successor: Task, *, predecessor_id: UUID, expected_revision: int, action_key: str,
) -> Task:
    """Stage both Tasks in the caller's transaction; never dispatch a pending successor."""
    db = get_db()
    predecessor = await db.scalar(select(Task).where(Task.id == predecessor_id)
        .with_for_update().execution_options(populate_existing=True))
    if predecessor is None or predecessor.deleted_at is not None or (
        predecessor.agent_id != successor.agent_id
        or predecessor.parent_id is not None
        or predecessor.messenger_connection_id != successor.messenger_connection_id
        or predecessor.message_group_id != successor.message_group_id
    ):
        raise task_service.TaskEditConflict("Replacement target is unavailable in this conversation.")
    existing_id = (predecessor.data or {}).get(_SUCCESSOR_KEY)
    if existing_id:
        existing = await db.get(Task, UUID(str(existing_id)))
        if existing is not None and replacement_state(existing).get("action_key") == action_key:
            return existing
        raise task_service.TaskEditConflict("This Task already has an explicit successor.")
    if predecessor.revision != expected_revision:
        raise task_service.TaskRevisionConflict("Replacement target revision changed.")
    # Coordination must be resolved by its owner, never silently orphaned by a root stop.
    if await _has_coordination(predecessor):
        raise task_service.TaskEditConflict("Replacement requires resolved child and external waits.")
    successor.id = successor.id or uuid4()
    successor.source_task_id = predecessor.id
    state: dict[str, Any] = {
        "state": "pending", "action_key": action_key,
        "lease_token": str(predecessor.lease_token) if predecessor.lease_token else None,
        "run": (predecessor.data or {}).get("_agent_run_identity"),
        "completed": predecessor.status == TaskStatus.SUCCESS,
    }
    successor.data = {**(successor.data or {}), REPLACEMENT_KEY: state}
    task_service.suspend(successor, "replacement")
    predecessor.data = {**(predecessor.data or {}), _SUCCESSOR_KEY: str(successor.id)}
    if predecessor.status not in _TERMINAL:
        await task_service.request_cancellation(predecessor)
    db.add(successor)
    return successor


async def _stopped(predecessor: Task, state: dict[str, Any]) -> bool:
    if predecessor.lease_token is not None or predecessor.status not in _TERMINAL:
        return False
    run = state.get("run")
    run = cast(dict[str, Any], run) if isinstance(run, dict) else {}
    if state.get("completed") or (not state.get("lease_token") and not run):
        return True
    receipt = state.get("cancellation")
    if isinstance(receipt, dict):
        receipt = HarnessCancellationReceipt.model_validate(receipt)
        if (str(receipt.run_id) == run.get("request_run_id") and receipt.state == "confirmed"
            and (receipt.scope == "remote" or run.get("local_interrupt") is True)):
            return True
    attempt_id = run.get("attempt_id")
    token = state.get("lease_token")
    query = select(TaskAttempt).where(TaskAttempt.task_id == predecessor.id)
    if token:
        query = query.where(TaskAttempt.lease_token == UUID(str(token)))
    elif attempt_id:
        query = query.where(TaskAttempt.id == UUID(str(attempt_id)))
    else:
        return False
    attempt = await get_db().scalar(query)
    if attempt is None or attempt.finished_at is None:
        return False
    data = attempt.data or {}
    if data.get("local_execution_stopped") is True and (not run or run.get("local_interrupt") is True):
        return True
    events = data.get("agent_events")
    if isinstance(events, list):
        for raw_event in cast(list[object], events):
            if not isinstance(raw_event, dict):
                continue
            event = cast(dict[str, Any], raw_event)
            identity = event.get("identity")
            payload = event.get("payload")
            if (event.get("kind") in {"run.completed", "run.failed"}
                and isinstance(identity, dict)
                and isinstance(payload, dict)
                and cast(dict[str, Any], payload).get("execution_stopped") is True
                and cast(dict[str, Any], identity).get("run_id") == run.get("request_run_id")):
                return True
    return False


async def reconcile_replacements() -> None:
    """Resume only explicit successors; pending/unknown cancellation survives worker restarts."""
    db = get_db()
    identifiers = list(await db.scalars(select(Task.id).where(
        Task.status.not_in(_TERMINAL), Task.deleted_at.is_(None),
        Task.data[REPLACEMENT_KEY]["state"].as_string() == "pending",
    ).order_by(Task.updated_at.asc().nullsfirst(), Task.created_at.asc()).limit(20)))
    for identifier in identifiers:
        successor = await db.get(Task, identifier, populate_existing=True)
        if successor is None or successor.source_task_id is None:
            continue
        source_id = successor.source_task_id
        state = replacement_state(successor)
        run = state.get("run")
        run = cast(dict[str, Any], run) if isinstance(run, dict) else {}
        predecessor = await db.get(Task, source_id, populate_existing=True)
        if predecessor is None:
            continue
        matches = _predecessor_matches(predecessor, successor, state)
        stopped = matches and await _stopped(predecessor, state)
        await db.commit()  # No database lock spans a driver control request.
        if matches and not stopped and run.get("request_run_id") and run.get("driver_code"):
            try:
                receipt = await cancel_agent_run(str(run["driver_code"]), UUID(str(run["request_run_id"])))
            except (RuntimeError, ValueError):
                receipt = None
            if receipt is not None:
                state["cancellation"] = receipt.model_dump(mode="json")
        predecessor = await db.scalar(select(Task).where(Task.id == source_id)
            .with_for_update().execution_options(populate_existing=True))
        successor = await db.scalar(select(Task).where(Task.id == identifier)
            .with_for_update().execution_options(populate_existing=True))
        if predecessor is None or successor is None or successor.status in _TERMINAL:
            await db.commit()
            continue
        current = replacement_state(successor)
        if current.get("state") != "pending":
            await db.commit()
            continue
        current["checked_at"] = datetime.now(timezone.utc).isoformat()
        if not _predecessor_matches(predecessor, successor, current) or await _has_coordination(predecessor):
            current["state"] = "conflict"
            successor.data = {**(successor.data or {}), REPLACEMENT_KEY: current}
            await db.commit()
            continue
        existing_receipt = current.get("cancellation")
        confirmed = isinstance(existing_receipt, dict) and cast(dict[str, Any], existing_receipt).get("state") == "confirmed"
        if "cancellation" in state and not confirmed:
            current["cancellation"] = state["cancellation"]
        if await _stopped(predecessor, current):
            current["state"] = "confirmed"
            task_service.release(successor, "replacement")
        successor.data = {**(successor.data or {}), REPLACEMENT_KEY: current}
        await db.commit()
        if current["state"] == "confirmed":
            await task_service.publish_updated(successor)
            from .scheduler import wake
            wake(successor.id)
