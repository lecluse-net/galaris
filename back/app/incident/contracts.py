"""Public compatibility re-export for the runtime-neutral failure contract."""

from core.failure_journal import FailureEvent, FailureKind


__all__ = ["FailureEvent", "FailureKind"]
