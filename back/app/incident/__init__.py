"""Durable failure journal for LLM and tool execution incidents."""

from .contracts import FailureEvent
from .retention import prune_traces
from .models import FailureIncident, FailureIncidentTrace, FailurePattern
from .service import (
    mark_run_recovered,
    mark_run_recovered_isolated,
    record_failure,
    record_failure_isolated,
)


def register_runtime() -> None:
    """Bind this application module to the core observability port."""

    from core.failure_journal import register_failure_journal

    register_failure_journal(
        record_in_session=record_failure,
        record_isolated=record_failure_isolated,
        mark_recovered=mark_run_recovered_isolated,
    )


__all__ = [
    "FailureEvent",
    "prune_traces",
    "FailureIncident",
    "FailureIncidentTrace",
    "FailurePattern",
    "mark_run_recovered",
    "mark_run_recovered_isolated",
    "record_failure",
    "record_failure_isolated",
    "register_runtime",
]
