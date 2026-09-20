from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator
from uuid import UUID

if TYPE_CHECKING:
    from app.agent.contracts import AIMessage
    from app.task.models import Task


def go_next(task_id: UUID, delay: float = 0.0, fast: bool = False) -> None:
    """Ask the durable scheduler to resume pending task processing."""
    from app.task import scheduler as task_scheduler

    task_scheduler.wake(task_id, delay=delay, fast=fast)


async def run_stream(task: "Task") -> "AsyncIterator[AIMessage]":
    """Compatibility wrapper that delegates streaming to the agent facade."""
    from app.agent import stream_workflow
    from .agent_adapter import as_agent_task

    async for message in stream_workflow(as_agent_task(task)):
        yield message
