"""Coordinate an explicitly admitted Task tree without expanding it after a restart."""

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from .models import Task, TaskStatus
from . import replacement, task_service


async def members(root_id: UUID, *, lock: bool = False) -> list[Task]:
    tree = select(Task.id).where(Task.id == root_id).cte(recursive=True)
    tree = tree.union(select(Task.id).join(tree, Task.parent_id == tree.c.id))
    query = select(Task).where(Task.id.in_(select(tree.c.id))).order_by(Task.id)
    if lock:
        query = query.with_for_update()
    return list(await get_db().scalars(query.execution_options(populate_existing=True, include_historized=True)))


def snapshot(task: Task) -> dict[str, Any]:
    return {
        "task_id": str(task.id), "agent_id": task.agent_id,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "lease_token": str(task.lease_token) if task.lease_token else None,
        "run": (task.data or {}).get("_agent_run_identity"),
        "completed": task.status.name == "SUCCESS",
    }


async def stage(root: Task) -> list[Task]:
    rows = await members(root.id, lock=True)
    for task in rows:
        wait = (task.data or {}).get("awaiting_reply")
        if task.deleted_at is not None or task.goal_id is not None or wait and (not isinstance(wait, dict) or cast(dict[str, Any], wait).get("kind") != "process"):
            raise task_service.TaskEditConflict("Replacement cannot silently stop a Goal or an unknown external wait.")
    ids = [task.id for task in rows]
    for key, blocked_ids in replacement.replacement_blockers().items():
        blocked = await get_db().scalar(select(Task.id).where(Task.id.in_(ids),
            Task.id.in_(blocked_ids())).limit(1).execution_options(include_historized=True))
        if blocked is not None and key not in replacement.replacement_coordinators():
            raise task_service.TaskEditConflict("The external owner cannot coordinate replacement.")
    return rows


def stable(rows: list[Task], records: list[dict[str, Any]]) -> bool:
    by_id = {str(task.id): task for task in rows}
    if set(by_id) != {str(record["task_id"]) for record in records}:
        return False
    for record in records:
        task = by_id[str(record["task_id"])]
        if (task.deleted_at is not None or task.status not in {TaskStatus.SUCCESS, TaskStatus.ERROR}
            or task.agent_id != record["agent_id"]
            or (str(task.parent_id) if task.parent_id else None) != record["parent_id"]
            or (task.data or {}).get("_agent_run_identity") != record.get("run")
            or task.lease_token is not None and str(task.lease_token) != record.get("lease_token")):
            return False
    return True


async def reconcile(successor: Task, state: dict[str, Any]) -> None:
    db = get_db()
    assert successor.source_task_id is not None
    root_id, successor_id = successor.source_task_id, successor.id
    records = [dict(value) for value in cast(list[dict[str, Any]], state["members"])]
    rows = await members(root_id)
    root = next((task for task in rows if task.id == root_id), None)
    unchanged = root is not None and replacement.predecessor_matches(root, successor, state) and stable(rows, records)
    await db.commit()  # No Task lock spans external stop requests.
    diagnostics: list[str] = []
    if unchanged:
        ids = [task.id for task in rows]
        for key, coordinate in replacement.replacement_coordinators().items():
            try:
                await coordinate(ids)
            except Exception as exc:
                diagnostics.append(f"{key}:{type(exc).__name__}")
                await db.rollback()
        for record in records:
            run = record.get("run")
            run = cast(dict[str, Any], run) if isinstance(run, dict) else {}
            task = await db.get(Task, UUID(str(record["task_id"])), populate_existing=True)
            matches = (task is not None and (task.data or {}).get("_agent_run_identity") == record.get("run")
                and task.agent_id == record.get("agent_id") and task.deleted_at is None)
            needs_stop = matches and task is not None and not await replacement.predecessor_stopped(task, record)
            await db.commit()
            if needs_stop and run.get("request_run_id") and run.get("driver_code"):
                try:
                    receipt = await replacement.cancel_agent_run(str(run["driver_code"]),
                        UUID(str(run["request_run_id"])), task_id=UUID(str(record["task_id"])))
                    record["cancellation"] = receipt.model_dump(mode="json")
                except (RuntimeError, ValueError):
                    pass
    root = await db.scalar(select(Task).where(Task.id == root_id).with_for_update().execution_options(populate_existing=True))
    refreshed = await db.scalar(select(Task).where(Task.id == successor_id).with_for_update().execution_options(populate_existing=True))
    if root is None or refreshed is None or refreshed.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
        await db.commit()
        return
    successor = refreshed
    current = replacement.replacement_state(successor)
    if current.get("state") != "pending":
        await db.commit()
        return
    # Preserve a concurrent worker's confirmed receipt for the same frozen run.
    saved_records = current.get("members", [])
    for saved in saved_records:
        if not isinstance(saved, dict):
            continue
        saved = cast(dict[str, Any], saved)
        receipt = saved.get("cancellation")
        if isinstance(receipt, dict) and cast(dict[str, Any], receipt).get("state") == "confirmed":
            for record in records:
                if record.get("task_id") == saved.get("task_id") and record.get("run") == saved.get("run"):
                    record["cancellation"] = receipt
    rows = await members(root_id, lock=True)
    unchanged = replacement.predecessor_matches(root, successor, current) and stable(rows, records)
    by_id = {str(task.id): task for task in rows}
    stopped = unchanged and all([await replacement.predecessor_stopped(by_id[str(record["task_id"])], record) for record in records])
    ids = [task.id for task in rows]
    for blocked_ids in replacement.replacement_blockers().values():
        if await db.scalar(select(Task.id).where(Task.id.in_(ids), Task.id.in_(blocked_ids()))
            .limit(1).execution_options(include_historized=True)) is not None:
            stopped = False
    current.update(members=records, checked_at=datetime.now(timezone.utc).isoformat(), diagnostics=diagnostics)
    if not unchanged:
        current["state"] = "conflict"
    elif stopped:
        current["state"] = "confirmed"
        task_service.release(successor, "replacement")
    successor.data = {**(successor.data or {}), replacement.REPLACEMENT_KEY: current}
    await db.commit()
    if stopped:
        await task_service.publish_updated(successor)
        from .scheduler import wake
        wake(successor.id)
