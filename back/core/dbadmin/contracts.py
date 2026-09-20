"""Public contracts for declarative database synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DbAdminMode(StrEnum):
    """Execution context; it never changes the desired database state."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class DbAdminVerdict(StrEnum):
    """Terminal synchronization verdict decided by DbAdmin."""

    CONVERGED = "converged"
    STAGED = "staged"
    DEGRADED = "degraded"
    FATAL = "fatal"


class DbAdminPhase(StrEnum):
    """Stable phases available to idempotent upgrade actions."""

    BEFORE_EXPAND = "before_expand"
    AFTER_EXPAND = "after_expand"
    AFTER_DATASET = "after_dataset"
    AFTER_CONTRACT = "after_contract"


class DbAdminActionStatus(StrEnum):
    """Outcome of one registered action."""

    APPLIED = "applied"
    ALREADY_SATISFIED = "already_satisfied"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DbAdminIssue:
    """One scrubbed and operator-visible synchronization issue."""

    phase: str
    message: str
    object_name: str | None = None
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class RequiredColumnTransition:
    """A new required column that must first be added as nullable."""

    table_name: str
    column_name: str

    @property
    def key(self) -> str:
        return f"{self.table_name}.{self.column_name}"


@dataclass(frozen=True, slots=True)
class EnumTransition:
    """Difference between one live PostgreSQL enum and its declared target."""

    name: str
    live_values: tuple[str, ...]
    target_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemaObjectTransition:
    """Observed definition change; evidence only, never authorization to discard data."""

    table_name: str
    object_name: str
    kind: str
    live_definition: str | None
    target_definition: str | None


@dataclass(frozen=True, slots=True)
class SchemaTransitionSet:
    """Immutable transition evidence shared by every DbAdmin phase."""

    added_tables: frozenset[str] = frozenset()
    removed_tables: frozenset[str] = frozenset()
    added_columns: frozenset[str] = frozenset()
    removed_columns: frozenset[str] = frozenset()
    required_columns: tuple[RequiredColumnTransition, ...] = ()
    enums: tuple[EnumTransition, ...] = ()
    definitions: tuple[SchemaObjectTransition, ...] = ()

    def table_added(self, table_name: str) -> bool:
        return table_name in self.added_tables

    def column_added(self, table_name: str, column_name: str) -> bool:
        return f"{table_name}.{column_name}" in self.added_columns


@dataclass(frozen=True, slots=True)
class DbAdminActionResult:
    """Durable diagnostic returned by an upgrade action."""

    key: str
    phase: DbAdminPhase
    status: DbAdminActionStatus
    message: str = ""


@dataclass(frozen=True, slots=True)
class DbAdminResult:
    """Complete, bounded result of one synchronization run."""

    run_id: str
    mode: DbAdminMode
    verdict: DbAdminVerdict
    started_at: datetime
    finished_at: datetime
    scope_fingerprint: str
    target_fingerprint: str
    transitions: SchemaTransitionSet = SchemaTransitionSet()
    action_results: tuple[DbAdminActionResult, ...] = ()
    issues: tuple[DbAdminIssue, ...] = ()

    @property
    def exit_code(self) -> int:
        return 1 if self.verdict is DbAdminVerdict.FATAL else 0


class DbAdminFatalError(RuntimeError):
    """Raised when serving traffic would be unsafe after synchronization."""
