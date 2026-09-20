"""Ephemeral context hand-off to the Hermes MemoryProvider plugin.

The task scheduler guarantees at most one active task per agent. This small
process-local cache therefore lets Hermes reuse the brief already ranked by
``app.memory`` without performing a second search or copying it into the task
prompt twice. The governed-memory MCP tools remain the durable fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


@dataclass(frozen=True)
class PreparedMemoryContext:
    task_id: UUID
    context: str
    expires_at: datetime


_prepared: dict[int, PreparedMemoryContext] = {}
_TTL = timedelta(hours=1)


def bind_memory_context(*, agent_id: int, task_id: UUID, context: str) -> None:
    """Publish one immutable brief immediately before starting a Hermes run."""

    _prepared[agent_id] = PreparedMemoryContext(
        task_id=task_id,
        context=context,
        expires_at=datetime.now(timezone.utc) + _TTL,
    )


def get_memory_context(
    *, agent_id: int, task_id: UUID
) -> PreparedMemoryContext | None:
    prepared = _prepared.get(agent_id)
    if prepared is None:
        return None
    if prepared.expires_at <= datetime.now(timezone.utc):
        _prepared.pop(agent_id, None)
        return None
    return prepared if prepared.task_id == task_id else None


def clear_memory_context(*, agent_id: int, task_id: UUID) -> None:
    prepared = _prepared.get(agent_id)
    if prepared is not None and prepared.task_id == task_id:
        _prepared.pop(agent_id, None)


def reset_memory_contexts() -> None:
    _prepared.clear()


__all__ = [
    "PreparedMemoryContext",
    "bind_memory_context",
    "clear_memory_context",
    "get_memory_context",
    "reset_memory_contexts",
]
