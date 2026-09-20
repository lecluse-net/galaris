"""In-memory active-task registry used by stateless per-agent MCP gateways.

Executors push and pop around a run. The implicit per-agent lookup is deliberately
available only when exactly one Task is active, so future concurrency fails closed
instead of attributing an LLM or tool call to an arbitrary sibling run.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

_active: dict[int, list[UUID]] = defaultdict(list)


def push(agent_id: int | None, task_id: UUID) -> None:
    """Mark ``task_id`` as an active run for ``agent_id``."""
    if agent_id is None:
        return
    _active[agent_id].append(task_id)


def pop(agent_id: int | None, task_id: UUID) -> None:
    """Remove ``task_id`` from the active runs for ``agent_id``."""
    if agent_id is None:
        return
    stack = _active.get(agent_id)
    if not stack:
        return
    try:
        stack.remove(task_id)
    except ValueError:
        pass
    if not stack:
        _active.pop(agent_id, None)


def get_current_task(agent_id: int) -> UUID | None:
    """Return the sole active Task, or no implicit correlation when ambiguous."""
    stack = _active.get(agent_id)
    return stack[0] if stack is not None and len(stack) == 1 else None


def current(agent_id: int) -> UUID | None:
    """Backward-compatible alias for ``get_current_task``."""
    return get_current_task(agent_id)
