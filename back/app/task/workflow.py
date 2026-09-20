"""Typed state machine for the task lifecycle.

PostgreSQL remains the durable source of truth for leases, attempts, and pauses. This
module only defines phase transitions and the action the scheduler must start; it keeps
no parallel in-memory state.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final

from .models import Task, TaskStatus


class TaskAction(str, Enum):
    """Durable actions triggered by the scheduler for a phase."""

    DISPATCH = "dispatch"
    BRIEF = "brief"
    EXECUTE = "execute"
    ADVANCE_PLAN = "advance_plan"


class TaskEvent(str, Enum):
    """Domain events allowed to change a task phase."""

    ROUTE_TO_EXECUTION = "route_to_execution"
    ROUTE_TO_BRIEFING = "route_to_briefing"
    ROUTE_TO_PLAN = "route_to_plan"
    START_EXECUTION = "start_execution"
    BRIEFING_SUCCEEDED = "briefing_succeeded"
    BRIEFING_FAILED = "briefing_failed"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"
    PLAN_SUCCEEDED = "plan_succeeded"
    PLAN_FAILED = "plan_failed"
    FAIL = "fail"
    INTERRUPT_EXECUTION = "interrupt_execution"
    RECOVER_EXECUTION = "recover_execution"
    RETRY = "retry"
    RETRY_PLAN = "retry_plan"
    RETRY_DELIVERY = "retry_delivery"
    RETRY_ROUTING = "retry_routing"
    REVISE = "revise"
    CANCEL = "cancel"
    FORCE_TERMINATE = "force_terminate"
    ACTIVATE_PLAN_STEP = "activate_plan_step"
    RESUME_COLLABORATION = "resume_collaboration"
    COORDINATION_SUCCEEDED = "coordination_succeeded"
    COORDINATION_FAILED = "coordination_failed"


class InvalidTaskTransition(ValueError):
    """Transition rejected by the state machine."""

    def __init__(self, current: TaskStatus, event: TaskEvent) -> None:
        self.current = current
        self.event = event
        super().__init__(
            f"Transition {event.value!r} is not allowed from phase {current.value!r}."
        )


@dataclass(frozen=True)
class TransitionRule:
    sources: frozenset[TaskStatus]
    target: TaskStatus


_ACTIVE: Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.CREATE,
        TaskStatus.PAUSE,  # Read compatibility for legacy rows.
        TaskStatus.DISPATCH,
        TaskStatus.BRIEFING,
        TaskStatus.EXEC,
        TaskStatus.PLAN,
    }
)

TRANSITIONS: Final[dict[TaskEvent, TransitionRule]] = {
    TaskEvent.ROUTE_TO_EXECUTION: TransitionRule(
        frozenset({TaskStatus.CREATE, TaskStatus.DISPATCH}), TaskStatus.DISPATCH
    ),
    TaskEvent.ROUTE_TO_BRIEFING: TransitionRule(
        frozenset({TaskStatus.CREATE, TaskStatus.DISPATCH}), TaskStatus.BRIEFING
    ),
    TaskEvent.ROUTE_TO_PLAN: TransitionRule(
        frozenset({TaskStatus.CREATE, TaskStatus.DISPATCH, TaskStatus.PLAN}),
        TaskStatus.PLAN,
    ),
    TaskEvent.START_EXECUTION: TransitionRule(
        frozenset({TaskStatus.DISPATCH}), TaskStatus.EXEC
    ),
    TaskEvent.BRIEFING_SUCCEEDED: TransitionRule(
        frozenset({TaskStatus.BRIEFING}), TaskStatus.DISPATCH
    ),
    TaskEvent.BRIEFING_FAILED: TransitionRule(
        frozenset({TaskStatus.BRIEFING}), TaskStatus.ERROR
    ),
    TaskEvent.EXECUTION_SUCCEEDED: TransitionRule(
        frozenset({TaskStatus.EXEC}), TaskStatus.SUCCESS
    ),
    TaskEvent.EXECUTION_FAILED: TransitionRule(
        frozenset({TaskStatus.EXEC}), TaskStatus.ERROR
    ),
    TaskEvent.PLAN_SUCCEEDED: TransitionRule(
        frozenset({TaskStatus.PLAN}), TaskStatus.SUCCESS
    ),
    TaskEvent.PLAN_FAILED: TransitionRule(
        frozenset({TaskStatus.PLAN}), TaskStatus.ERROR
    ),
    TaskEvent.FAIL: TransitionRule(_ACTIVE, TaskStatus.ERROR),
    TaskEvent.INTERRUPT_EXECUTION: TransitionRule(
        frozenset({TaskStatus.EXEC}), TaskStatus.DISPATCH
    ),
    TaskEvent.RECOVER_EXECUTION: TransitionRule(
        frozenset({TaskStatus.EXEC}), TaskStatus.DISPATCH
    ),
    TaskEvent.RETRY: TransitionRule(
        frozenset({TaskStatus.ERROR}), TaskStatus.DISPATCH
    ),
    TaskEvent.RETRY_PLAN: TransitionRule(
        frozenset({TaskStatus.ERROR}), TaskStatus.PLAN
    ),
    TaskEvent.RETRY_DELIVERY: TransitionRule(
        frozenset({TaskStatus.SUCCESS, TaskStatus.ERROR}), TaskStatus.DISPATCH
    ),
    TaskEvent.RETRY_ROUTING: TransitionRule(
        frozenset({TaskStatus.ERROR}), TaskStatus.CREATE
    ),
    TaskEvent.REVISE: TransitionRule(
        frozenset({TaskStatus.DISPATCH, TaskStatus.BRIEFING}), TaskStatus.CREATE
    ),
    TaskEvent.CANCEL: TransitionRule(_ACTIVE, TaskStatus.ERROR),
    TaskEvent.FORCE_TERMINATE: TransitionRule(_ACTIVE, TaskStatus.ERROR),
    TaskEvent.ACTIVATE_PLAN_STEP: TransitionRule(
        frozenset({TaskStatus.PLAN, TaskStatus.DISPATCH}), TaskStatus.DISPATCH
    ),
    # Collaboration resumes only from its durable non-terminal suspension point. SUCCESS and
    # ERROR are immutable: no automatic event is ever allowed to reopen a terminal Task.
    TaskEvent.RESUME_COLLABORATION: TransitionRule(
        frozenset({TaskStatus.DISPATCH}),
        TaskStatus.DISPATCH,
    ),
    TaskEvent.COORDINATION_SUCCEEDED: TransitionRule(
        frozenset({TaskStatus.CREATE, TaskStatus.PAUSE, TaskStatus.DISPATCH}),
        TaskStatus.SUCCESS,
    ),
    TaskEvent.COORDINATION_FAILED: TransitionRule(
        frozenset({TaskStatus.CREATE, TaskStatus.PAUSE, TaskStatus.DISPATCH}),
        TaskStatus.ERROR,
    ),
}


SCHEDULER_ACTIONS: Final[dict[TaskStatus, TaskAction]] = {
    TaskStatus.CREATE: TaskAction.DISPATCH,
    TaskStatus.BRIEFING: TaskAction.BRIEF,
    TaskStatus.DISPATCH: TaskAction.EXECUTE,
    TaskStatus.PLAN: TaskAction.ADVANCE_PLAN,
}


def transition(task: Task, event: TaskEvent) -> TaskStatus:
    """Apply ``event`` or raise; invalid transitions are never silent."""

    rule = TRANSITIONS[event]
    if task.status not in rule.sources:
        raise InvalidTaskTransition(task.status, event)
    task.status = rule.target
    return rule.target


def scheduler_action(status: TaskStatus) -> TaskAction | None:
    """Return the executable action for a phase, or ``None`` for a terminal phase."""

    return SCHEDULER_ACTIONS.get(status)


def can_transition(status: TaskStatus, event: TaskEvent) -> bool:
    """Return whether an event is valid without mutating state."""

    return status in TRANSITIONS[event].sources
