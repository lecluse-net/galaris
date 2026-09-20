"""Injected port to ``app.task`` durable persistence and scheduling.

The agent domain knows neither SQLAlchemy models nor concrete task services. The
adapter is registered when ``app.task`` loads and is then accessed through this narrow
facade.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from uuid import UUID

from .contracts import (
    AgentRunEventV1,
    AgentTask,
    AgentTaskBlockers,
    AgentTaskDraft,
    AgentContextCapsule,
    ExecutionResult,
    TaskPhase,
    TaskTransition,
    WorkingResource,
    WorkingSet,
)


class TaskAmendmentUnavailableError(RuntimeError):
    """The durable Task changed and can no longer accept the requested amendment."""


class TaskAmendmentRevisionConflict(TaskAmendmentUnavailableError):
    """Re-read the target; a stale amendment must not create an implicit duplicate."""


class AgentTaskPort(Protocol):
    async def save(self, task: AgentTask) -> AgentTask: ...
    async def refresh(self, task: AgentTask) -> AgentTask: ...
    async def create(self, draft: AgentTaskDraft) -> AgentTask: ...
    async def replace(self, draft: AgentTaskDraft, *, target_task_id: UUID,
                      expected_revision: int, action_key: str) -> tuple[AgentTask, bool]: ...
    async def get_by_id(self, task_id: UUID) -> AgentTask | None: ...
    async def get_children(self, parent_id: UUID) -> list[AgentTask]: ...
    async def list_for_agent(self, agent_id: int, *, limit: int) -> list[AgentTask]: ...
    async def harness_blockers(self, agent_id: int) -> AgentTaskBlockers: ...
    async def force_terminate_paused_for_agent(
        self, agent_id: int
    ) -> AgentTaskBlockers: ...
    async def operational_state(self, task_id: UUID) -> Mapping[str, Any]: ...
    async def activate_agent_run(
        self, task: AgentTask, trace: Mapping[str, Any]
    ) -> UUID | None: ...
    async def persist_agent_run_state(
        self,
        task_id: UUID,
        *,
        expected_objective: str,
        expected_attempt_id: UUID | None = None,
        data_patch: Mapping[str, Any] | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> None: ...
    async def append_agent_run_event(
        self, task: AgentTask, event: AgentRunEventV1
    ) -> None: ...
    async def get_working_set(self, task_id: UUID) -> WorkingSet: ...
    async def get_context_capsule(
        self, task: AgentTask
    ) -> AgentContextCapsule | None: ...
    async def freeze_context_capsule(
        self, task: AgentTask, capsule: AgentContextCapsule
    ) -> AgentContextCapsule: ...
    async def upsert_working_resource(
        self, task_id: UUID, resource: WorkingResource
    ) -> WorkingResource: ...
    async def amend(
        self,
        *,
        task_id: UUID,
        expected_revision: int,
        instruction: str,
        disposition: str,
        reason: str | None,
        source_kind: str,
        source_id: str,
        idempotency_key: str,
    ) -> AgentTask: ...
    def suspend(self, task: AgentTask, reason: str) -> None: ...
    def release(self, task: AgentTask, reason: str) -> bool: ...
    def clear_pauses(self, task: AgentTask) -> None: ...
    def is_paused_for(self, task: AgentTask, reason: str) -> bool: ...
    def is_held_by_user(self, task: AgentTask) -> bool: ...
    def transition(self, task: AgentTask, event: TaskTransition) -> TaskPhase: ...
    def schedule(self, task_id: UUID, *, fast: bool = False) -> None: ...
    def collab_context(self, task: AgentTask) -> str: ...
    def collab_rounds(self, task: AgentTask) -> int: ...
    async def suspend_on_pending_children(self, task: AgentTask) -> bool: ...
    async def resolve_from_peer_task(self, task: AgentTask) -> None: ...
    async def maybe_fan_in(self, parent_id: UUID | None) -> None: ...
    async def approval_action(self, task: AgentTask) -> str: ...
    async def list_planner_clarification_candidates(self) -> list[AgentTask]: ...
    async def claim_inline_execution(self, task_id: UUID) -> UUID: ...
    async def maintain_inline_execution(self, task_id: UUID, lease_token: UUID) -> None: ...
    async def finish_inline_execution(
        self,
        task_id: UUID,
        lease_token: UUID,
        *,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None: ...


class _TaskPortProxy:
    PAUSE_AWAIT = "await"
    PAUSE_PLAN = "plan"
    PAUSE_CLARIFY = "clarify"
    PAUSE_CHILD = "child"
    DELEGATED_KEY = "delegated"

    def __init__(self) -> None:
        self._implementation: AgentTaskPort | None = None

    def register(self, implementation: AgentTaskPort) -> None:
        self._implementation = implementation

    def _require(self) -> AgentTaskPort:
        if self._implementation is None:
            raise RuntimeError(
                "The app.task port is not registered; module bootstrap is incomplete."
            )
        return self._implementation

    async def save(self, task: AgentTask) -> AgentTask:
        return await self._require().save(task)

    async def refresh(self, task: AgentTask) -> AgentTask:
        return await self._require().refresh(task)

    async def create(self, draft: AgentTaskDraft) -> AgentTask:
        return await self._require().create(draft)

    async def replace(self, draft: AgentTaskDraft, *, target_task_id: UUID,
                      expected_revision: int, action_key: str) -> tuple[AgentTask, bool]:
        return await self._require().replace(draft, target_task_id=target_task_id,
            expected_revision=expected_revision, action_key=action_key)

    async def get_by_id(self, task_id: UUID) -> AgentTask | None:
        return await self._require().get_by_id(task_id)

    async def get_children(self, parent_id: UUID) -> list[AgentTask]:
        return await self._require().get_children(parent_id)

    async def list_for_agent(self, agent_id: int, *, limit: int) -> list[AgentTask]:
        return await self._require().list_for_agent(agent_id, limit=limit)

    async def harness_blockers(self, agent_id: int) -> AgentTaskBlockers:
        return await self._require().harness_blockers(agent_id)

    async def force_terminate_paused_for_agent(
        self, agent_id: int
    ) -> AgentTaskBlockers:
        return await self._require().force_terminate_paused_for_agent(agent_id)

    async def operational_state(self, task_id: UUID) -> Mapping[str, Any]:
        return await self._require().operational_state(task_id)

    async def activate_agent_run(
        self, task: AgentTask, trace: Mapping[str, Any]
    ) -> UUID | None:
        return await self._require().activate_agent_run(task, trace)

    async def persist_agent_run_state(
        self,
        task_id: UUID,
        *,
        expected_objective: str,
        expected_attempt_id: UUID | None = None,
        data_patch: Mapping[str, Any] | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> None:
        await self._require().persist_agent_run_state(
            task_id,
            expected_objective=expected_objective,
            expected_attempt_id=expected_attempt_id,
            data_patch=data_patch,
            execution_result=execution_result,
        )

    async def append_agent_run_event(
        self, task: AgentTask, event: AgentRunEventV1
    ) -> None:
        await self._require().append_agent_run_event(task, event)

    async def get_working_set(self, task_id: UUID) -> WorkingSet:
        return await self._require().get_working_set(task_id)

    async def get_context_capsule(
        self, task: AgentTask
    ) -> AgentContextCapsule | None:
        return await self._require().get_context_capsule(task)

    async def freeze_context_capsule(
        self, task: AgentTask, capsule: AgentContextCapsule
    ) -> AgentContextCapsule:
        return await self._require().freeze_context_capsule(task, capsule)

    async def upsert_working_resource(
        self, task_id: UUID, resource: WorkingResource
    ) -> WorkingResource:
        return await self._require().upsert_working_resource(task_id, resource)

    async def amend(
        self,
        *,
        task_id: UUID,
        expected_revision: int,
        instruction: str,
        disposition: str,
        reason: str | None,
        source_kind: str,
        source_id: str,
        idempotency_key: str,
    ) -> AgentTask:
        return await self._require().amend(
            task_id=task_id,
            expected_revision=expected_revision,
            instruction=instruction,
            disposition=disposition,
            reason=reason,
            source_kind=source_kind,
            source_id=source_id,
            idempotency_key=idempotency_key,
        )

    def suspend(self, task: AgentTask, reason: str) -> None:
        self._require().suspend(task, reason)

    def release(self, task: AgentTask, reason: str) -> bool:
        return self._require().release(task, reason)

    def clear_pauses(self, task: AgentTask) -> None:
        self._require().clear_pauses(task)

    def is_paused_for(self, task: AgentTask, reason: str) -> bool:
        return self._require().is_paused_for(task, reason)

    def is_held_by_user(self, task: AgentTask) -> bool:
        return self._require().is_held_by_user(task)

    def transition(self, task: AgentTask, event: TaskTransition) -> TaskPhase:
        return self._require().transition(task, event)

    def schedule(self, task_id: UUID, *, fast: bool = False) -> None:
        self._require().schedule(task_id, fast=fast)

    def collab_context(self, task: AgentTask) -> str:
        return self._require().collab_context(task)

    def collab_rounds(self, task: AgentTask) -> int:
        return self._require().collab_rounds(task)

    async def suspend_on_pending_children(self, task: AgentTask) -> bool:
        return await self._require().suspend_on_pending_children(task)

    async def resolve_from_peer_task(self, task: AgentTask) -> None:
        await self._require().resolve_from_peer_task(task)

    async def maybe_fan_in(self, parent_id: UUID | None) -> None:
        await self._require().maybe_fan_in(parent_id)

    async def approval_action(self, task: AgentTask) -> str:
        return await self._require().approval_action(task)

    async def list_planner_clarification_candidates(self) -> list[AgentTask]:
        return await self._require().list_planner_clarification_candidates()

    async def claim_inline_execution(self, task_id: UUID) -> UUID:
        return await self._require().claim_inline_execution(task_id)

    async def maintain_inline_execution(self, task_id: UUID, lease_token: UUID) -> None:
        await self._require().maintain_inline_execution(task_id, lease_token)

    async def finish_inline_execution(
        self,
        task_id: UUID,
        lease_token: UUID,
        *,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        await self._require().finish_inline_execution(
            task_id,
            lease_token,
            error=error,
            cancelled=cancelled,
        )


task_port = _TaskPortProxy()


def register_task_port(implementation: AgentTaskPort) -> None:
    task_port.register(implementation)
