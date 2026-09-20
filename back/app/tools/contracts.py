"""Execution evidence shared by native tools and their runtime adapters."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Generator, Literal
from uuid import UUID

EXECUTION_META_KEY = "galaris.execution/v1"


@dataclass
class ToolExecutionContext:
    operation_id: UUID
    tool_name: str
    outcome: Literal["unknown", "rejected", "returned"] = "unknown"
    entered: bool = False


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
