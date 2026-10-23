"""Execution evidence shared by native tools and their runtime adapters."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Generator, Literal
from uuid import UUID

EXECUTION_META_KEY = "galaris.execution/v1"
TOOL_ARGUMENTS_META_KEY = "galaris.tool-arguments/v1"

FileIndexingMode = Literal["excluded", "known_uris", "recursive"]
FILE_INDEXING_PARAM = "tools.fileindexing"
MANAGEMENT_SCOPE_PARAM = "tools.management_scope"


@dataclass
class ToolExecutionContext:
    operation_id: UUID
    tool_name: str
    outcome: Literal["unknown", "rejected", "returned"] = "unknown"
    entered: bool = False
    authorization_continuation: str | None = None
    authorization_context: str | None = None
    scope_rejection: Literal["clarify", "deny"] | None = None


_execution: ContextVar[ToolExecutionContext | None] = ContextVar("tool_execution", default=None)


def current_tool_execution() -> ToolExecutionContext | None:
    return _execution.get()


@contextmanager
def tool_execution(context: ToolExecutionContext) -> Generator[ToolExecutionContext]:
    token = _execution.set(context)
    try:
        yield context
    finally:
        _execution.reset(token)


class ToolCallRejectedError(ValueError):
    """An explicit precondition rejected a call before any external effect."""


class ScopePreflightRejected(ToolCallRejectedError):
    """A server-owned scope decision, distinct from correctable argument errors."""

    def __init__(self, decision: Literal["clarify", "deny"], reason: str) -> None:
        super().__init__(reason)
        self.decision: Literal["clarify", "deny"] = decision
