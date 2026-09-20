"""Observe persisted scheduling states without changing scheduling decisions."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, NonNegativeFloat, ValidationError

from sqlalchemy import event, inspect

from .models import Task, TaskStatus


TimingState = Literal["finished", "processing", "user_pause", "external_wait", "backoff", "queue"]


class LifecycleTiming(BaseModel):
    since: AwareDatetime
    observed_since: AwareDatetime
    enqueued_at: AwareDatetime | None = None
    state: TimingState
    phase: str
    until: AwareDatetime | None = None
    seconds: dict[str, NonNegativeFloat] = Field(default_factory=dict[str, float])
    phases: dict[str, dict[str, NonNegativeFloat]] = Field(default_factory=dict[str, dict[str, float]])


def parse_lifecycle(value: object) -> LifecycleTiming | None:
    try:
        return LifecycleTiming.model_validate(value)
    except ValidationError:
        return None


def _state(task: Task, now: datetime) -> TimingState:
    if task.status in {TaskStatus.SUCCESS, TaskStatus.ERROR}:
        return "finished"
    if task.lease_token is not None:
        return "processing"
    if task.paused:
        reasons: Any = (task.data or {}).get("pause_reasons") or []
        return "user_pause" if "user" in reasons else "external_wait"
    if task.next_attempt_at is not None and task.next_attempt_at > now:
        return "backoff"
    return "queue"


def timing_totals(recorded: dict[str, Any], now: datetime) -> dict[str, float]:
    timing = parse_lifecycle(recorded)
    if timing is None:
        return {}
    totals = dict(timing.seconds)
    started = timing.since
    elapsed = max(0.0, (now - started).total_seconds())
    state = timing.state
    if state == "finished":
        return totals
    if state == "backoff" and timing.until:
        until = timing.until
        backoff = min(elapsed, max(0.0, (until - started).total_seconds()))
        totals["backoff"] = totals.get("backoff", 0.0) + backoff
        totals["queue"] = totals.get("queue", 0.0) + elapsed - backoff
    else:
        totals[state] = totals.get(state, 0.0) + elapsed
    return totals


def phase_totals(timing: LifecycleTiming, now: datetime) -> dict[str, dict[str, float]]:
    phases = {phase: dict(seconds) for phase, seconds in timing.phases.items()}
    current = phases.setdefault(timing.phase, {})
    for state, seconds in timing_totals(timing.model_dump(), now).items():
        delta = seconds - timing.seconds.get(state, 0.0)
        if delta > 0:
            current[state] = current.get(state, 0.0) + delta
    return phases


def _observe(task: Task, *, inserted: bool) -> None:
    now = datetime.now(timezone.utc)
    previous = None if inserted else parse_lifecycle(task.lifecycle_timing)
    state = _state(task, now)
    phase = str(getattr(task.status, "value", task.status) or TaskStatus.CREATE.value)
    until = task.next_attempt_at if state == "backoff" else None
    if previous and (previous.state, previous.phase, previous.until) == (state, phase, until):
        return
    totals = timing_totals(previous.model_dump(), now) if previous else {}
    task.lifecycle_timing = LifecycleTiming(since=now, state=state, phase=phase,
        until=until, seconds=totals, phases=phase_totals(previous, now) if previous else {},
        enqueued_at=now if inserted else previous.enqueued_at if previous else None,
        observed_since=previous.observed_since if previous else now).model_dump(mode="json")


def _insert(_mapper: Any, _connection: Any, task: Task) -> None:
    _observe(task, inserted=True)


def _update(_mapper: Any, _connection: Any, task: Task) -> None:
    # Do not turn a historical relationship-only/no-op flush into a versioned
    # Task write: a running executor may still own that revision.
    if task.lifecycle_timing is None and not any(
        inspect(task).attrs[name].history.has_changes()
        for name in ("status", "paused", "lease_token", "next_attempt_at")
    ):
        return
    _observe(task, inserted=False)


event.listen(Task, "before_insert", _insert)
event.listen(Task, "before_update", _update)
