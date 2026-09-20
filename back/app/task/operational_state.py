"""Semantic operational state derived from durable Task data and children."""

from __future__ import annotations
from core.util import visible_text


from typing import Any, Literal, NotRequired, Sequence, TypedDict, cast

from .models import Task, TaskStatus


OperationalState = Literal["QUEUED", "RUNNING", "WAITING", "PAUSED", "TERMINAL"]
WaitKind = Literal[
    "AGENT_REPLY",
    "HUMAN_REPLY",
    "PROCESS",
    "DELEGATED_TASK",
    "PLAN_STEP",
    "CLARIFICATION",
]


class TaskWait(TypedDict):
    kind: WaitKind
    status: Literal["PENDING"]
    coordination_task_id: NotRequired[str]
    response_task_id: NotRequired[str | None]
    question: NotRequired[str]
    peer_user_id: NotRequired[str]
    peer_display: NotRequired[str]
    target_agent_id: NotRequired[int]
    room_id: NotRequired[str]
    asked_at: NotRequired[str]
    deadline: NotRequired[str]
    process_run_id: NotRequired[str]
    process_label: NotRequired[str]


class TaskOperationalSnapshot(TypedDict):
    operational_state: OperationalState
    resume_phase: str
    pause_reasons: list[str]
    waits: list[TaskWait]
    amendable: bool
    amend_blocker: str | None
    replacement: NotRequired[dict[str, Any]]


_TERMINAL = (TaskStatus.SUCCESS, TaskStatus.ERROR)


def _data(task: Task) -> dict[str, Any]:
    return task.data if isinstance(task.data, dict) else {}


def _pause_reasons(task: Task) -> list[str]:
    raw = _data(task).get("pause_reasons")
    if not isinstance(raw, list):
        return []
    return [str(reason) for reason in cast(list[Any], raw)]


def _await_wait(child: Task, marker: dict[str, Any]) -> TaskWait:
    marker_kind = str(marker.get("kind") or "").strip()
    if marker_kind == "process":
        kind: WaitKind = "PROCESS"
    elif marker_kind == "goal_referrer":
        kind = "HUMAN_REPLY"
    else:
        kind = "AGENT_REPLY"
    wait: TaskWait = {
        "kind": kind,
        "status": "PENDING",
        "coordination_task_id": str(child.id),
        "response_task_id": None,
        "question": visible_text(child.objective or ""),
    }
    peer_user_id = marker.get("peer_user_id")
    peer_display = marker.get("peer_display")
    room_id = marker.get("room_id")
    asked_at = marker.get("asked_at")
    deadline = marker.get("deadline")
    process_run_id = marker.get("run_id")
    process_label = marker.get("process_label")
    if peer_user_id not in (None, ""):
        wait["peer_user_id"] = str(peer_user_id)
    if peer_display not in (None, ""):
        wait["peer_display"] = str(peer_display)
    if room_id not in (None, ""):
        wait["room_id"] = str(room_id)
    if asked_at not in (None, ""):
        wait["asked_at"] = str(asked_at)
    if deadline not in (None, ""):
        wait["deadline"] = str(deadline)
    if process_run_id not in (None, ""):
        wait["process_run_id"] = str(process_run_id)
    if process_label not in (None, ""):
        wait["process_label"] = str(process_label)
    resolved_by = _data(child).get("resolved_by_task_id")
    if resolved_by:
        wait["response_task_id"] = str(resolved_by)
    return wait


def _active_waits(task: Task, children: Sequence[Task]) -> list[TaskWait]:
    waits: list[TaskWait] = []
    own_marker = _data(task).get("awaiting_reply")
    if isinstance(own_marker, dict) and task.status not in _TERMINAL:
        waits.append(_await_wait(task, cast(dict[str, Any], own_marker)))
    for child in children:
        if child.status in _TERMINAL:
            continue
        child_data = _data(child)
        marker = child_data.get("awaiting_reply")
        if isinstance(marker, dict):
            waits.append(_await_wait(child, cast(dict[str, Any], marker)))
        elif bool(child_data.get("delegated")):
            wait: TaskWait = {
                "kind": "DELEGATED_TASK",
                "status": "PENDING",
                "coordination_task_id": str(child.id),
                "response_task_id": None,
                "question": visible_text(child.objective or ""),
            }
            if child.agent_id is not None:
                wait["target_agent_id"] = child.agent_id
            waits.append(wait)

    reasons = _pause_reasons(task)
    data = _data(task)
    if "clarify" in reasons and not any(wait["kind"] == "CLARIFICATION" for wait in waits):
        questions = data.get("clarification_questions")
        question = (
            "\n".join(str(value) for value in cast(list[Any], questions))
            if isinstance(questions, list)
            else ""
        )
        waits.append({"kind": "CLARIFICATION", "status": "PENDING", "question": question})
    if "plan" in reasons and not any(wait["kind"] == "PLAN_STEP" for wait in waits):
        waits.append({"kind": "PLAN_STEP", "status": "PENDING"})
    return waits


def operational_snapshot(task: Task, children: Sequence[Task] = ()) -> TaskOperationalSnapshot:
    """Return a stable, agent-readable semantic view with resume diagnostics."""

    reasons = _pause_reasons(task)
    waits = _active_waits(task, children)
    if task.status in _TERMINAL:
        state: OperationalState = "TERMINAL"
    elif task.paused and "user" in reasons:
        state = "PAUSED"
    elif task.paused or waits:
        state = "WAITING"
    elif task.lease_token is not None:
        state = "RUNNING"
    else:
        state = "QUEUED"

    blocker: str | None = None
    if task.parent_id is not None:
        blocker = "Only root Tasks can be amended."
    elif task.status in _TERMINAL:
        blocker = "Terminal Tasks cannot be amended."
    elif task.plan is not None:
        blocker = "A Task with a materialized plan cannot be amended safely."
    elif any(
        bool(_data(child).get("delegated")) or child.plan is not None
        for child in children
        if child.status not in _TERMINAL
    ):
        blocker = "A Task with active delegated or planned children cannot be amended safely."

    from .replacement import replacement_state, replacement_pending
    replacement = replacement_state(task)
    if replacement_pending(task):
        blocker = "A replacement is waiting for its predecessor to stop."
    if blocker is None:
        from app.agent import objective_amendment_blocker

        blocker = objective_amendment_blocker(
            _data(task), execution_active=task.lease_token is not None,
        )
    snapshot: TaskOperationalSnapshot = {
        "operational_state": state,
        "resume_phase": task.status.value,
        "pause_reasons": reasons,
        "waits": waits,
        "amendable": blocker is None,
        "amend_blocker": blocker,
    }
    if replacement:
        snapshot["replacement"] = {"state": replacement.get("state"),
            "predecessor_uri": f"galaris://task/{task.source_task_id}"}
    return snapshot


async def inspect_operational_state(task: Task) -> TaskOperationalSnapshot:
    """Load direct children and derive the operational snapshot."""

    from . import task_service

    return operational_snapshot(task, await task_service.get_children(task.id))


__all__ = [
    "OperationalState",
    "TaskOperationalSnapshot",
    "TaskWait",
    "inspect_operational_state",
    "operational_snapshot",
]
