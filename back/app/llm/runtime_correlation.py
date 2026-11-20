"""Correlation shared by managed external LLM gateway surfaces."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request

from core.i18n import tr

from .trace import task_id_from_messages


@asynccontextmanager
async def runtime_deep_scope(request: Request, agent_id: int | None) -> AsyncGenerator[bool, None]:
    """Authenticate session attribution independently from a task attempt."""
    credential = request.headers.get("X-Galaris-Deep-Context")
    if credential is None:
        yield False
        return
    from app.conversation import authorize_deep_runtime
    from core.util import get_encryption_service
    from .correlation import deep_inference_scope
    from .subscription_policy import llm_execution_scope

    try:
        if agent_id is None or request.headers.get("X-Galaris-Run-Context"):
            raise PermissionError("A Deep session requires its managed runtime principal.")
        identity = get_encryption_service().decrypt(credential)
        if not identity.startswith("galaris:deep:v1:"):
            raise PermissionError("Invalid Deep session credential.")
        session_id = UUID(identity.removeprefix("galaris:deep:v1:"))
        requester = await authorize_deep_runtime(session_id, agent_id)
    except (InvalidToken, PermissionError, ValueError, RuntimeError) as exc:
        raise HTTPException(403, await tr("llm_api.errors.runtime_run_context_invalid")) from exc
    with deep_inference_scope(session_id), llm_execution_scope(requester_user_id=requester):
        yield True


@dataclass(frozen=True, slots=True)
class RuntimeLLMTask:
    task_id: UUID
    run_id: UUID
    attempt_id: UUID


async def resolve_runtime_llm_task(
    request: Request,
    *,
    task_ids: tuple[object, ...],
    run_ids: tuple[object, ...],
) -> RuntimeLLMTask | None:
    """Resolve authenticated attribution before admitting a durable inference."""
    from app.services.facade import RuntimePrincipal, resolve_runtime_run_grant, runtime_dispatch_ready

    principal = getattr(request.state, "runtime_llm_principal", None)
    credential = request.headers.get("X-Galaris-Run-Context")
    if credential is None:
        if isinstance(principal, RuntimePrincipal):
            from app.agent import configured_harness_selection, get_agent_record

            agent = await get_agent_record(principal.agent_id)
            selection = await configured_harness_selection(agent) if agent is not None else None
            if selection is not None and selection.metadata.get("run_scoped_llm") is True:
                raise HTTPException(401, await tr("llm_api.errors.runtime_run_context_required"))
        return None

    try:
        if not isinstance(principal, RuntimePrincipal) or not credential:
            raise PermissionError("A managed runtime principal is required")
        grant = await resolve_runtime_run_grant(credential, principal=principal)
        if not grant.context_key.startswith("task:") or grant.attempt_key is None or not await runtime_dispatch_ready(grant):
            raise PermissionError("An active task attempt context is required")
        task_id = UUID(grant.context_key.removeprefix("task:"))
        if any(value is not None and UUID(str(value)) != task_id for value in task_ids):
            raise PermissionError("Conflicting runtime task")
        if any(value is not None and UUID(str(value)) != grant.run_key for value in run_ids):
            raise PermissionError("Conflicting runtime run")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(403, await tr("llm_api.errors.runtime_run_context_invalid")) from exc

    return RuntimeLLMTask(task_id, grant.run_key, grant.attempt_key)


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


__all__ = ["resolve_runtime_llm_task", "resolve_runtime_process_run_id", "resolve_runtime_task_id"]
