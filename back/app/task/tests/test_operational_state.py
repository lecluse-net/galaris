from uuid import uuid4

from app.task.models import Task, TaskStatus
from app.task.operational_state import operational_snapshot


def _task(**values: object) -> Task:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "revision": 1,
        "label": "Task",
        "objective": "Deliver the report",
        "status": TaskStatus.DISPATCH,
        "paused": False,
        "ai": True,
        "cost": 0.0,
        "agent_id": 7,
    }
    defaults.update(values)
    return Task(**defaults)


def test_parent_wait_explains_agent_question_and_deadline() -> None:
    parent = _task(paused=True, data={"pause_reasons": ["await"]})
    child = _task(
        label="Ask Sophie",
        objective="Which fiscal period should I use?",
        parent_id=parent.id,
        paused=True,
        ai=False,
        data={
            "pause_reasons": ["await"],
            "awaiting_reply": {
                "peer_user_id": "sophie",
                "peer_display": "Sophie",
                "room_id": "room-1",
                "asked_at": "2026-08-03T10:00:00+00:00",
                "deadline": "2026-08-03T10:30:00+00:00",
            },
        },
    )

    snapshot = operational_snapshot(parent, [child])

    assert snapshot["operational_state"] == "WAITING"
    assert snapshot["resume_phase"] == "DISPATCH"
    assert snapshot["amendable"] is True
    assert snapshot["waits"] == [
        {
            "kind": "AGENT_REPLY",
            "status": "PENDING",
            "coordination_task_id": str(child.id),
            "response_task_id": None,
            "question": "Which fiscal period should I use?",
            "peer_user_id": "sophie",
            "peer_display": "Sophie",
            "room_id": "room-1",
            "asked_at": "2026-08-03T10:00:00+00:00",
            "deadline": "2026-08-03T10:30:00+00:00",
        }
    ]


def test_planned_task_is_not_silently_amendable() -> None:
    task = _task(plan={"steps": [], "cursor": 0})

    snapshot = operational_snapshot(task)

    assert snapshot["operational_state"] == "QUEUED"
    assert snapshot["amendable"] is False
    assert "materialized plan" in str(snapshot["amend_blocker"])


def test_coordination_child_exposes_its_own_wait() -> None:
    child = _task(
        paused=True,
        ai=False,
        data={
            "pause_reasons": ["await"],
            "awaiting_reply": {
                "kind": "process",
                "run_id": "process-run-1",
                "process_label": "Daily report",
                "deadline": "2026-08-03T11:00:00+00:00",
            },
        },
    )

    snapshot = operational_snapshot(child)

    assert snapshot["waits"][0]["kind"] == "PROCESS"
    assert snapshot["waits"][0]["process_run_id"] == "process-run-1"
