"""Correlation shared by managed external LLM gateway surfaces."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

from .trace import task_id_from_messages


async def resolve_runtime_task_id(
    *,
    raw_task_id: Any,
    messages: Any,
    agent_id: int | None,
) -> UUID | None:
    """Resolve the Task owning a managed-runtime LLM call.

    Explicit transport metadata is authoritative, followed by prompt metadata and
    the in-process execution context. A durable lease lookup covers calls reaching
    another backend worker. It returns no Task when the agent has no unique lease,
    so an ambiguous call can never be silently attached to the wrong Task.
    """
    if raw_task_id:
        return UUID(str(raw_task_id))

    prompt_task_id = task_id_from_messages(messages)
    if prompt_task_id is not None:
        return prompt_task_id

    if agent_id is None:
        return None

    from app.agent import get_current_task

    current_task_id = get_current_task(agent_id)
    if current_task_id is not None:
        return current_task_id

    from app.task import unique_leased_task_for_agent

    return await unique_leased_task_for_agent(agent_id)


async def resolve_runtime_process_run_id(
    *,
    raw_process_run_id: Any,
    workflow_id: Any,
    engine_run_id: Any,
    task_id: UUID | None,
    agent_ids: Collection[int] | None,
) -> UUID | None:
    """Resolve the ProcessRun owning an API call.

    A canonical Galaris run UUID is authoritative. External engines may instead
    identify their workflow and execution; ``app.process`` resolves that pair under
    the caller's agent scope. Calls made by a Task inherit the immutable ProcessRun
    reference stored in the Task snapshot.
    """
    stored_run_id: UUID | None = None
    if task_id is not None:
        from app.task import task_service

        task = await task_service.get_by_id(task_id)
        if task is not None and isinstance(task.data, dict):
            raw_stored_run_id = task.data.get("process_run_id")
            stored_run_id = (
                UUID(str(raw_stored_run_id)) if raw_stored_run_id else None
            )

    resolved_run_id: UUID | None = None
    if raw_process_run_id:
        resolved_run_id = UUID(str(raw_process_run_id))
    elif workflow_id and engine_run_id:
        from app.process import process_service

        run = await process_service.resolve_engine_run(
            str(workflow_id),
            str(engine_run_id),
            agent_ids=agent_ids,
        )
        resolved_run_id = run.id
    else:
        resolved_run_id = stored_run_id

    if (
        resolved_run_id is not None
        and stored_run_id is not None
        and resolved_run_id != stored_run_id
    ):
        raise ValueError(
            f"Task {task_id} belongs to ProcessRun {stored_run_id}, "
            f"not {resolved_run_id}."
        )
    return resolved_run_id


__all__ = ["resolve_runtime_process_run_id", "resolve_runtime_task_id"]
