"""Operational evidence shared by native run screens and agent introspection."""

from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import func, select

from app.task.facade import inspect_workflow_tasks
from core.database import get_db

from .models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun, ProcessRunEvent, ProcessStartJob
from .process_service import TERMINAL_STATUSES


async def observe_run(run: ProcessRun, *, can_control: bool, visible_children: set[str]) -> dict[str, Any]:
    db = get_db()
    observed_at = datetime.now(timezone.utc)
    state: dict[str, Any] = run.engine_metadata.get("native", {})
    counts = {status: count for status, count in (await db.execute(select(ProcessNodeRun.status, func.count())
        .where(ProcessNodeRun.run_id == run.id).group_by(ProcessNodeRun.status))).all()}
    active = list(await db.scalars(select(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id,
        ProcessNodeRun.status.in_(["ready", "waiting"]))
        .order_by(ProcessNodeRun.admission_order, ProcessNodeRun.id).limit(100)))
    if run.status in TERMINAL_STATUSES:
        active = []
    attempts = list(await db.scalars(select(ProcessNodeAttempt).distinct(ProcessNodeAttempt.node_run_id).where(
        ProcessNodeAttempt.node_run_id.in_([node.id for node in active]))
        .order_by(ProcessNodeAttempt.node_run_id, ProcessNodeAttempt.number.desc(), ProcessNodeAttempt.id.desc()))) if active else []
    latest = {attempt.node_run_id: attempt for attempt in attempts}
    task_states = await inspect_workflow_tasks([attempt.task_id for attempt in latest.values() if attempt.task_id])
    signals: list[dict[str, Any]] = []
    for node in active:
        attempt = latest.get(node.id)
        context = node.context
        graph: dict[str, Any] = run.launch_snapshot.get("definition", {}).get("graph") or {}
        for key in context.get("body_path", []):
            graph = next((cast(dict[str, Any], item.get("body") or {}) for item in
                cast(list[dict[str, Any]], graph.get("nodes", [])) if item.get("id") == key), dict[str, Any]())
        definition = next((item for item in cast(list[dict[str, Any]], graph.get("nodes", [])) if item.get("id") == node.node_key), dict[str, Any]())
        question = context.get("activity_question", {})
        task = task_states.get(attempt.task_id) if attempt and attempt.task_id else None
        kind = "ready" if node.status == "ready" else "engine"
        detail: dict[str, Any] = {}
        if question.get("status") == "pending" or attempt and attempt.status == "human_waiting":
            kind = "human_reply"
            detail = {"question": str(question.get("question") or (attempt.prompt if attempt else "") or "")[:2000],
                "user_id": question.get("user_id") or context.get("human_user_id")}
        elif attempt and attempt.status == "authorization":
            kind = "authorization"
        elif attempt and attempt.child_run_id:
            kind = "child_process"
            if str(attempt.child_run_id) in visible_children:
                detail["run_id"] = str(attempt.child_run_id)
        elif task:
            kind = {"RUNNING": "agent_task", "QUEUED": "task_queue", "PAUSED": "task_paused", "WAITING": "task_wait"}.get(task["operational_state"], "engine")
            if "approval" in task["pause_reasons"]:
                kind = "authorization"
            # A Task may await a process outside this run's readable child scope.
            task["waits"] = [{key: value for key, value in wait.items()
                if key not in {"process_run_id", "process_label"} or wait.get("process_run_id") in visible_children}
                for wait in task["waits"]]
            detail = {"task_uri": f"galaris://task/{attempt.task_id}" if attempt else None, "task": task}
        elif attempt and attempt.status in {"rest_ready", "tool_ready", "started", "claiming"}:
            kind = "external_operation"
        elif any(job.get("submitted") and not job.get("stopped") for job in context.get("code_jobs", {}).values()):
            kind = "code_execution"
        since = node.started_at or (attempt.created_at if attempt else None)
        signals.append({"kind": kind, "occurrence_id": str(node.id), "node_key": node.node_key,
            "title": definition.get("title") or node.node_key,
            "body_path": context.get("body_path", []), "since": since.isoformat() if since else None, **detail})
    last_node_time = await db.scalar(select(func.max(func.coalesce(ProcessNodeRun.finished_at, ProcessNodeRun.started_at)))
        .where(ProcessNodeRun.run_id == run.id))
    last_event = (await db.execute(select(ProcessRunEvent.created_at, ProcessRunEvent.event_type)
        .where(ProcessRunEvent.run_id == run.id).order_by(ProcessRunEvent.id.desc()).limit(1))).first()
    last_activity = max(value for value in (run.created_at, run.started_at, run.finished_at, last_node_time,
        last_event.created_at if last_event else None) if value is not None)
    for task in task_states.values():
        last_activity = max(last_activity, datetime.fromisoformat(task["updated_at"]))
    uncertain = run.status == "unknown" or state.get("error", {}).get("code") == "effect_outcome_unknown"
    stopping = run.status == "cancelling" or bool(state.get("cancel_requested"))
    in_flight = any(signal["kind"] in {"agent_task", "task_queue", "external_operation", "code_execution", "engine"} for signal in signals)
    phase = run.status
    if run.status not in TERMINAL_STATUSES:
        if stopping:
            phase = "cancelling"
        elif uncertain:
            phase = "blocked"
        elif state.get("paused"):
            phase = "pausing" if in_flight else "paused"
        elif signals and not in_flight and not any(signal["kind"] == "ready" for signal in signals):
            phase = "waiting"
    actions: list[str] = []
    if can_control and run.status not in TERMINAL_STATUSES:
        actions = ["cancel"] if stopping else ["cancel", "pause"]
        if not stopping and state.get("paused") and not uncertain:
            actions = ["resume", "step", "cancel"]
    startup = await db.scalar(select(ProcessStartJob).where(ProcessStartJob.run_id == run.id)) if run.status == "queued" else None
    return {"phase": phase, "observed_at": observed_at.isoformat(), "last_activity_at": last_activity.isoformat(),
        "last_event": {"at": last_event.created_at.isoformat(), "type": last_event.event_type} if last_event else None,
        "seconds_since_activity": max(0, (observed_at - last_activity).total_seconds()),
        "progress": {"occurrences": sum(counts.values()), "completed": counts.get("success", 0),
            "failed": counts.get("error", 0), "ready": counts.get("ready", 0) if run.status not in TERMINAL_STATUSES else 0,
            "active": counts.get("waiting", 0) if run.status not in TERMINAL_STATUSES else 0,
            "cancelled": counts.get("cancelled", 0), "by_status": counts},
        "activities": signals, "activities_truncated": run.status not in TERMINAL_STATUSES and sum(counts.get(key, 0) for key in ("ready", "waiting")) > len(active),
        "blocker": {"code": "effect_outcome_unknown", "requires_reconciliation": True} if uncertain else None,
        "startup": {"status": startup.status, "attempts": startup.attempts, "available_at": startup.available_at.isoformat()} if startup else None,
        "available_actions": actions,
        "pause_policy": "finish_admitted_activities_then_wait"}
