"""Durable ``app.task`` adapter for the generic ``app.agent`` domain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from app.agent.contracts import (
    AgentRunEventV1,
    AgentTask,
    AgentTaskDraft,
    AgentTaskBlocker,
    AgentTaskBlockers,
    AgentContextCapsule,
    ExecutionResult,
    StaleAgentRunError,
    TaskMessage,
    TaskPhase,
    TaskTransition,
    WorkingResource,
    WorkingSet,
)
from app.agent.task_port import TaskAmendmentUnavailableError, register_task_port
from sqlalchemy import select

from . import collab, task_service
from .models import Task, TaskAttempt, TaskStatus
from .schemas import TaskCreate
from .workflow import TaskEvent, transition


_AGENT_EVENT_TEXT_LIMIT = 4_000
_AGENT_EVENT_TOOL_LIMIT = 100


def _bounded_agent_event(event: AgentRunEventV1) -> dict[str, object]:
    """Project a semantic event without copying prompts or verbose tool payloads."""

    persisted: dict[str, object] = {
        "schema_version": event.schema_version,
        "identity": event.identity.model_dump(mode="json"),
        "sequence": event.sequence,
        "kind": event.kind,
        "occurred_at": event.occurred_at.isoformat(),
    }
    if event.usage is not None:
        persisted["usage"] = event.usage.model_dump(mode="json")
    scalar_payload = {
        key: value
        for key, value in event.payload.items()
        if isinstance(value, (str, int, float, bool, type(None)))
        and len(str(value)) <= 1_000
    }
    if scalar_payload:
        persisted["payload"] = scalar_payload
    if event.message is not None:
        persisted["message"] = {
            "type": event.message.type,
            "tool_name": event.message.tool_name,
            "success": event.message.success,
            "content": event.message.content[:_AGENT_EVENT_TEXT_LIMIT],
            "execution_time": event.message.execution_time,
            "cost": event.message.cost,
        }
    if event.result is not None:
        persisted["result"] = {
            "success": event.result.success,
            "result": event.result.result[:_AGENT_EVENT_TEXT_LIMIT],
            "execution_time": event.result.execution_time,
            "cost": event.result.cost,
            "tools_used": event.result.tools_used[:_AGENT_EVENT_TOOL_LIMIT],
            "usage": event.result.usage.model_dump(mode="json"),
        }
    return persisted


class SqlAlchemyAgentTaskAdapter:
    async def save(self, task: Any) -> Any:
        return await task_service.save(task)

    async def refresh(self, task: Any) -> Any:
        from core.database import get_db

        await get_db().refresh(task)
        return task

    async def create(self, draft: AgentTaskDraft) -> Any:
        return await task_service.create(
            TaskCreate(
                label=draft.label,
                objective=draft.objective,
                status=TaskStatus(draft.status.value),
                paused=draft.paused,
                ai=draft.ai,
                effort=draft.effort,
                agent_id=draft.agent_id,
                goal_id=draft.goal_id,
                requester_agent_id=draft.requester_agent_id,
                messenger_connection_id=draft.messenger_connection_id,
                message_platform=draft.message_platform,
                message_group_id=draft.message_group_id,
                data=dict(draft.data) if draft.data is not None else None,
                messages=(
                    [TaskMessage.model_validate(item) for item in draft.messages]
                    if draft.messages is not None
                    else None
                ),
                parent_id=draft.parent_id,
                source_task_id=draft.source_task_id,
                plan=dict(draft.plan) if draft.plan is not None else None,
            ),
            **({"idempotency_key": draft.idempotency_key} if draft.idempotency_key is not None else {}),
        )

    async def get_by_id(self, task_id: UUID) -> Any | None:
        return await task_service.get_by_id(task_id)

    async def replace(self, draft: AgentTaskDraft, *, target_task_id: UUID,
                      expected_revision: int, action_key: str) -> tuple[Any, bool]:
        from core.database import get_db
        from .replacement import prepare_replacement

        if draft.parent_id is not None:
            raise TaskAmendmentUnavailableError("Replacement requires a root Task.")
        candidate = task_service.build(TaskCreate(
            label=draft.label, objective=draft.objective, status=TaskStatus.CREATE,
            paused=draft.paused, ai=draft.ai, effort=draft.effort,
            agent_id=draft.agent_id, requester_agent_id=draft.requester_agent_id,
            messenger_connection_id=draft.messenger_connection_id,
            message_platform=draft.message_platform, message_group_id=draft.message_group_id,
            data=dict(draft.data) if draft.data else None,
        ))
        await task_service.apply_requester_lineage(candidate)
        try:
            task = await prepare_replacement(candidate, predecessor_id=target_task_id,
                expected_revision=expected_revision, action_key=action_key)
        except task_service.TaskConflictError as exc:
            await get_db().rollback()
            raise TaskAmendmentUnavailableError(str(exc)) from exc
        created = task is candidate
        await get_db().commit()
        if created:
            predecessor = await get_db().get(Task, target_task_id)
            if predecessor is not None:
                await task_service.publish_updated(predecessor)
            await task_service.publish_created(task)
        return task, created

    async def get_children(self, parent_id: UUID) -> list[Any]:
        return list(await task_service.get_children(parent_id))

    async def list_for_agent(self, agent_id: int, *, limit: int) -> list[Any]:
        from core.database import get_db

        query = Task.histo_filter(
            select(Task)
            .where(
                Task.agent_id == agent_id,
                Task.parent_id.is_(None),
                Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR)),
            )
            .order_by(Task.updated_at.desc(), Task.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
        return list((await get_db().scalars(query)).all())

    async def harness_blockers(self, agent_id: int) -> AgentTaskBlockers:
        from core.database import get_db

        query = Task.histo_filter(
            select(Task)
            .where(
                Task.agent_id == agent_id,
                Task.parent_id.is_(None),
                Task.status.not_in((TaskStatus.SUCCESS, TaskStatus.ERROR)),
            )
            .order_by(Task.updated_at.desc(), Task.created_at.desc())
        )
        tasks = list((await get_db().scalars(query)).all())
        return AgentTaskBlockers(
            paused_tasks=tuple(
                AgentTaskBlocker(id=task.id, label=task.label)
                for task in tasks
                if task.paused
            ),
            active_count=sum(not task.paused for task in tasks),
            active_tasks=tuple(
                AgentTaskBlocker(id=task.id, label=task.label)
                for task in tasks
                if not task.paused
            ),
        )

    async def force_terminate_paused_for_agent(
        self, agent_id: int
    ) -> AgentTaskBlockers:
        blockers = await self.harness_blockers(agent_id)
        for blocker in blockers.paused_tasks:
            await task_service.force_terminate(blocker.id, None)
        return await self.harness_blockers(agent_id)

    async def operational_state(self, task_id: UUID) -> dict[str, Any]:
        from .operational_state import inspect_operational_state

        task = await task_service.get_by_id(task_id)
        if task is None:
            return {}
        return dict(await inspect_operational_state(task))

    async def activate_agent_run(
        self, task: Any, trace: Mapping[str, Any]
    ) -> UUID | None:
        """Bind a logical run to the current durable scheduler attempt."""

        lease_token = getattr(task, "lease_token", None)
        if not isinstance(lease_token, UUID):
            # Unit/taskless callers have no scheduler attempt. They still receive the
            # transport contract, but there is deliberately no false durable attempt ID.
            return None
        from core.database import get_db

        db = get_db()
        current = (await db.execute(select(Task.lease_token, Task.lease_expires_at, Task.status)
            .where(Task.id == task.id).with_for_update())).one_or_none()
        if (current is None or current.lease_token != lease_token
                or current.status in (TaskStatus.SUCCESS, TaskStatus.ERROR)
                or (current.lease_expires_at is not None
                    and current.lease_expires_at <= datetime.now(timezone.utc))):
            raise StaleAgentRunError("The task lease no longer belongs to this worker.")
        attempt = await db.scalar(
            select(TaskAttempt)
            .where(TaskAttempt.lease_token == lease_token)
            .where(TaskAttempt.task_id == task.id)
            .with_for_update()
        )
        if attempt is None or attempt.status != "CLAIMED":
            raise StaleAgentRunError("The task attempt is no longer active.")
        normalized = {str(key): value for key, value in trace.items()}
        normalized["attempt_id"] = str(attempt.id)
        existing_data = dict(attempt.data or {})
        existing_run = existing_data.get("agent_run")
        existing_run_data: Mapping[str, object] = (
            cast(Mapping[str, object], existing_run)
            if isinstance(existing_run, Mapping)
            else cast(Mapping[str, object], {})
        )
        same_run = bool(existing_run_data) and str(
            existing_run_data.get("request_run_id") or ""
        ) == str(normalized.get("request_run_id") or "")
        attempt.data = {
            **existing_data,
            "agent_run": normalized,
            "agent_events": (
                existing_data.get("agent_events") if same_run else []
            ),
        }
        task.data = {
            **(getattr(task, "data", None) or {}),
            "_agent_run_identity": normalized,
        }
        await task_service.save(task)
        return attempt.id

    async def persist_agent_run_state(
        self,
        task_id: UUID,
        *,
        expected_objective: str,
        expected_attempt_id: UUID | None = None,
        data_patch: Mapping[str, Any] | None = None,
        execution_result: ExecutionResult | None = None,
    ) -> None:
        """Persist one run snapshot in its own serialized transaction.

        Parallel tool tasks must never refresh, mutate, or commit the scheduler's ambient
        ORM instance. Locking and reloading the durable row here also merges Working Set
        updates committed by tools before the checkpoint is written.
        """

        from core.database import get_db_session

        async with get_db_session() as db:
            task = await db.scalar(
                Task.histo_filter(
                    select(Task).where(Task.id == task_id).with_for_update()
                )
            )
            if task is None:
                raise LookupError(f"Task {task_id} no longer exists.")
            attempt: TaskAttempt | None = None
            if expected_attempt_id is not None:
                attempt = await db.scalar(select(TaskAttempt).where(
                    TaskAttempt.id == expected_attempt_id,
                    TaskAttempt.task_id == task_id,
                ).with_for_update())
                if (attempt is None or attempt.status != "CLAIMED"
                        or task.lease_token != attempt.lease_token
                        or (task.lease_expires_at is not None
                            and task.lease_expires_at <= datetime.now(timezone.utc))
                        or task.status in (TaskStatus.SUCCESS, TaskStatus.ERROR)):
                    raise StaleAgentRunError("The task attempt no longer owns this execution checkpoint.")
            if str(task.objective or "") != expected_objective:
                raise StaleAgentRunError(
                    "The Task objective changed while this agent run was active; "
                    "discarding the stale run so the amended objective can execute."
                )
            if data_patch:
                delivery = data_patch.get("_delivery_receipt")
                if isinstance(delivery, Mapping) and cast(Mapping[str, Any], delivery).get("status") == "started" and task.data and task.data.get("_delivery_receipt"):
                    raise StaleAgentRunError("A prior delivery receipt already exists; the send was not dispatched again.")
                task.data = {**(task.data or {}), **dict(data_patch)}
                if attempt is not None and "_agent_run_checkpoint" in data_patch:
                    attempt.data = {
                        **(attempt.data or {}),
                        "agent_checkpoint": data_patch["_agent_run_checkpoint"],
                    }
                if attempt is not None and delivery is not None:
                    attempt.data = {**(attempt.data or {}), "delivery_receipt": delivery}
            if execution_result is not None:
                task.set_execution_result(execution_result)
            await task_service.save(task)

        from . import scheduler

        scheduler.notify_task_activity(task_id)

    async def append_agent_run_event(
        self, task: Any, event: AgentRunEventV1
    ) -> None:
        """Append one bounded semantic event to the active attempt timeline."""

        lease_token = getattr(task, "lease_token", None)
        if not isinstance(lease_token, UUID):
            return
        from core.database import get_db_session

        # The timeline is a non-authoritative projection. Persist it independently so
        # its commit cannot close a savepoint owned by a tool or by the task workflow.
        async with get_db_session() as db:
            attempt = await db.scalar(
                select(TaskAttempt)
                .where(TaskAttempt.lease_token == lease_token)
                .with_for_update()
            )
            if attempt is None:
                return
            data = dict(attempt.data or {})
            raw_events = data.get("agent_events")
            events: list[dict[str, object]] = (
                [
                    cast(dict[str, object], raw_event)
                    for raw_event in cast(list[object], raw_events)
                    if isinstance(raw_event, dict)
                ]
                if isinstance(raw_events, list)
                else []
            )
            events.append(_bounded_agent_event(event))
            # Semantic events are sparse, nevertheless bound corrupted or future drivers.
            data["agent_events"] = events[-1_000:]
            attempt.data = data

        from . import scheduler

        scheduler.notify_task_activity(task.id)

    async def get_working_set(self, task_id: UUID) -> WorkingSet:
        from core.database import get_db_session
        from .working_set import get_working_set

        async with get_db_session():
            return await get_working_set(task_id)

    async def get_context_capsule(
        self, task: AgentTask
    ) -> AgentContextCapsule | None:
        from .working_set import get_context_capsule

        return await get_context_capsule(task.id)

    async def freeze_context_capsule(
        self, task: AgentTask, capsule: AgentContextCapsule
    ) -> AgentContextCapsule:
        from .working_set import freeze_context_capsule

        return await freeze_context_capsule(task.id, capsule)

    async def upsert_working_resource(
        self, task_id: UUID, resource: WorkingResource
    ) -> WorkingResource:
        from core.database import get_db_session
        from .working_set import upsert_working_resource

        async with get_db_session():
            return await upsert_working_resource(task_id, resource)

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
    ) -> Any:
        from .amendment_service import amend_task

        try:
            result = await amend_task(
                task_id=task_id,
                expected_revision=expected_revision,
                instruction=instruction,
                disposition=disposition,
                reason=reason,
                source_kind=source_kind,
                source_id=source_id,
                idempotency_key=idempotency_key,
            )
        except task_service.TaskRevisionConflict as exc:
            from app.agent.task_port import TaskAmendmentRevisionConflict

            raise TaskAmendmentRevisionConflict(str(exc)) from exc
        except task_service.TaskEditConflict as exc:
            raise TaskAmendmentUnavailableError(str(exc)) from exc
        return result.task

    def suspend(self, task: Any, reason: str) -> None:
        task_service.suspend(task, reason)

    def release(self, task: Any, reason: str) -> bool:
        return task_service.release(task, reason)

    def clear_pauses(self, task: Any) -> None:
        task_service.clear_pauses(task)

    def is_paused_for(self, task: Any, reason: str) -> bool:
        return task_service.is_paused_for(task, reason)

    def is_held_by_user(self, task: Any) -> bool:
        return task_service.is_held_by_user(task)

    def transition(self, task: Any, event: TaskTransition) -> TaskPhase:
        return TaskPhase(transition(task, TaskEvent(event.value)).value)

    def schedule(self, task_id: UUID, *, fast: bool = False) -> None:
        from .runner import go_next

        if fast:
            go_next(task_id, fast=True)
        else:
            go_next(task_id)

    def collab_context(self, task: Any) -> str:
        return collab.collab_context(task)

    def collab_rounds(self, task: Any) -> int:
        return collab.collab_rounds(task)

    async def suspend_on_pending_children(self, task: Any) -> bool:
        return await collab.suspend_on_pending_children(task)

    async def resolve_from_peer_task(self, task: Any) -> None:
        await collab.resolve_from_peer_task(task)

    async def maybe_fan_in(self, parent_id: UUID | None) -> None:
        await collab.maybe_fan_in(parent_id)

    async def approval_action(self, task: Any) -> str:
        return await task_service.approval_action(task)

    async def list_planner_clarification_candidates(self) -> list[Any]:
        from core.database import get_db
        from .models import Task

        query = Task.histo_filter(
            select(Task).where(
                Task.paused.is_(True),
                Task.plan.is_(None),
                Task.parent_id.is_(None),
            )
        )
        return list((await get_db().scalars(query)).all())

    async def claim_inline_execution(self, task_id: UUID) -> UUID:
        from . import scheduler

        return await scheduler.claim_inline_execution(task_id)

    async def maintain_inline_execution(self, task_id: UUID, lease_token: UUID) -> None:
        from . import scheduler

        await scheduler.maintain_inline_execution(task_id, lease_token)

    async def finish_inline_execution(
        self,
        task_id: UUID,
        lease_token: UUID,
        *,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        from . import scheduler

        await scheduler.finish_inline_execution(
            task_id,
            lease_token,
            error=error,
            cancelled=cancelled,
        )


register_task_port(SqlAlchemyAgentTaskAdapter())


def as_agent_task(task: Task) -> AgentTask:
    """Narrow the ORM-to-domain boundary in one explicit, audited location."""

    return cast(AgentTask, task)


def as_agent_tasks(tasks: Sequence[Task]) -> list[AgentTask]:
    return [as_agent_task(task) for task in tasks]
