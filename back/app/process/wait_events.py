"""Durable intermediate waits and reception of correlated Process events."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, TYPE_CHECKING
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints
from sqlalchemy import select

from app.agent import AgentManagementScope
from core.database import get_db

from .models import ProcessNodeRun, ProcessRun, ProcessRunEvent
from .values import unwrap

if TYPE_CHECKING:
    from .bpmn import Flow, Node

EventName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")]
Correlation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
WAIT_KINDS = frozenset({"timer", "event_wait"})


class TimerSettings(BaseModel):
    delay_seconds: Annotated[int, Field(strict=True, ge=1, le=31_536_000)] | None = None
    at: AwareDatetime | None = None
    date_variable: str | None = None


class EventSettings(BaseModel):
    event_name: EventName
    correlation_variable: str


class ProcessSignal(BaseModel):
    event_id: UUID
    name: EventName
    correlation: Correlation


class PendingWait(BaseModel):
    node_key: str
    flow: str | None = None
    due_at: AwareDatetime | None = None
    name: EventName | None = None
    correlation: Correlation | None = None


class WakeReceipt(BaseModel):
    kind: Literal["timer", "event"]
    node_key: str
    flow: str | None = None
    at: AwareDatetime
    event: ProcessSignal | None = None


def activate_wait(node: Node, data: dict[str, Any], started: datetime, *, flow: Flow | None = None) -> PendingWait:
    flow_id = flow.id if flow else None
    if node.kind == "timer":
        timer = TimerSettings.model_validate(node.config)
        due = started + timedelta(seconds=timer.delay_seconds) if timer.delay_seconds else timer.at
        if timer.date_variable is not None:
            value = data.get(timer.date_variable)
            raw = unwrap(value) if value is not None else None
            if not isinstance(raw, str):
                raise ValueError(f"{node.id}: the deadline input must contain a datetime")
            due = datetime.fromisoformat(raw)
        if due is None:
            raise ValueError(f"{node.id}: the timer needs a deadline")
        return PendingWait(node_key=node.id, flow=flow_id, due_at=due)
    config = EventSettings.model_validate(node.config)
    value = data.get(config.correlation_variable)
    correlation = unwrap(value) if value is not None else None
    if not isinstance(correlation, str):
        raise ValueError(f"{node.id}: the event needs its correlation input")
    return PendingWait(node_key=node.id, flow=flow_id, name=config.event_name, correlation=correlation)


def expired_timer(candidates: list[PendingWait], at: datetime) -> WakeReceipt | None:
    first = min((item for item in candidates if item.due_at is not None and item.due_at <= at),
                key=lambda item: (item.due_at or at, item.node_key), default=None)
    if first is None or first.due_at is None:
        return None
    return WakeReceipt(kind="timer", node_key=first.node_key, flow=first.flow, at=first.due_at)


def pending_waits(occurrence: ProcessNodeRun) -> list[PendingWait]:
    return [PendingWait.model_validate(value) for value in occurrence.context.get("pending_waits", [])]


async def signal_run(identity: UUID, actor: int | AgentManagementScope, signal: ProcessSignal) -> dict[str, Any]:
    """Settle one armed occurrence under the same run lock used by the engine."""
    from .native_runs import require_run
    from .process_service import TERMINAL_STATUSES

    await require_run(identity, actor, control=True)
    db = get_db()
    run = await db.scalar(select(ProcessRun).where(ProcessRun.id == identity)
                          .with_for_update().execution_options(populate_existing=True))
    assert run is not None
    key = f"signal:{signal.event_id}"
    previous = await db.scalar(select(ProcessRunEvent).where(ProcessRunEvent.run_id == identity, ProcessRunEvent.event_id == key))
    if previous is not None:
        if previous.payload.get("event") != signal.model_dump(mode="json"):
            raise ValueError("This event ID was already used for a different signal")
        return dict(previous.payload["receipt"])
    state: dict[str, Any] = dict(run.engine_metadata.get("native", {}))
    if (run.status in TERMINAL_STATUSES or run.status == "cancelling"
            or state.get("status") in TERMINAL_STATUSES or state.get("cancel_requested")):
        raise ValueError("This run no longer accepts events")
    at = datetime.now(timezone.utc)
    occurrences = await db.scalars(select(ProcessNodeRun).where(
        ProcessNodeRun.run_id == identity, ProcessNodeRun.status == "waiting",
        ProcessNodeRun.context["pending_waits"].as_string().is_not(None),
    ).execution_options(populate_existing=True))
    matches: list[tuple[ProcessNodeRun, PendingWait]] = []
    for occurrence in occurrences:
        candidates = pending_waits(occurrence)
        if occurrence.context.get("wake_receipt") or expired_timer(candidates, at):
            continue
        matches.extend((occurrence, item) for item in candidates
                       if item.name == signal.name and item.correlation == signal.correlation)
    if len(matches) != 1:
        raise ValueError("Expected exactly one active wait for this event and correlation")
    occurrence, candidate = matches[0]
    wake = WakeReceipt(kind="event", node_key=candidate.node_key, flow=candidate.flow, at=at, event=signal)
    occurrence.context = {**occurrence.context, "wake_receipt": wake.model_dump(mode="json")}
    if state.pop("wait_refresh_at", None) is not None:
        run.engine_metadata = {**run.engine_metadata, "next_refresh_at": None, "native": state}
    receipt = {"run_id": str(identity), "occurrence_id": str(occurrence.id), "node_key": candidate.node_key}
    db.add(ProcessRunEvent(run_id=identity, event_id=key, source="native", event_type="run.signal.received",
                           payload={"event": signal.model_dump(mode="json"), "receipt": receipt}))
    await db.commit()
    return receipt
