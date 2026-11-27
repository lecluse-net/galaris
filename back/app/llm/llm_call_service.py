"""Persistence and real-time publication of LLM calls."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Collection, Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID, uuid4

from loguru import logger
from pydantic import TypeAdapter
from sqlalchemy import Select, and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from core import websocket
from core.database import AsyncSessionLocal, get_db
from core.i18n import render_prompt, tr
from core.params import runtime_settings
from core.user import get_current_token_label, get_current_user_id
from .correlation import current_llm_correlation_ref
from .embedded_runtime import (
    EmbeddedInferenceOrigin, EmbeddedRequestLimitExceeded, EmbeddedTaskInference, bind_embedded_call,
    current_media_inference_origin,
)
from .accounting_scope import record_persisted_call_cost
from .costing import token_cost
from .cost_accounting import COST_EVIDENCE_KEY, call_cost
from .image_trace import compact_request_images, compact_trace_images
from .models import LLMCall
from .purposes import LLMCallPurpose
from .provider_facade import ReasoningEffort, usage_accounting_for
from core.util import as_dict, as_list
from .schemas import LLMCallRead, LLMCallSummary
from .subscription_policy import current_execution_authority
from .trace import (
    content_to_text,
    extract_prompts,
    normalize_deferred_tool_calls,
    usage_counters,
)


_RECONCILIATION_BATCH_SIZE = 500
_STALE_CALL_GRACE_SECONDS = 300
_PROGRESS_PAYLOAD_ADAPTER = TypeAdapter(dict[str, Any])
_call_columns = LLMCall.__table__.c

if TYPE_CHECKING:
    from .admission import AdmissionContext
    from .call_capture import TextCallCapture


class InferenceCallDeletionError(ValueError):
    """The call or a dependent runtime still needs its trace."""


_TASK_REQUIRED_PURPOSES = frozenset(
    {
        LLMCallPurpose.AGENT_PLANNING.value,
        LLMCallPurpose.AGENT_PLANNING_RECOVERY.value,
        LLMCallPurpose.AGENT_SYNTHESIS.value,
    }
)
_ROUND_REQUIRED_PURPOSES = frozenset(
    {
        LLMCallPurpose.CONVERSATION_TEXT.value,
        LLMCallPurpose.CONVERSATION_AUDIO.value,
        LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE.value,
        LLMCallPurpose.CONVERSATION_PROCESS_ADMISSION.value,
        LLMCallPurpose.CONVERSATION_PROCESS_INPUTS.value,
    }
)
_PROCESS_REQUIRED_PURPOSES = frozenset(
    {LLMCallPurpose.PROCESS_EXEC.value}
)
_ATTEMPT_REQUIRED_PURPOSES = frozenset(
    {
        LLMCallPurpose.AGENT_EXEC.value,
        LLMCallPurpose.AGENT_DISPATCH.value,
        *_TASK_REQUIRED_PURPOSES,
    }
)


def _validate_semantic_lineage(
    *,
    purpose: str | None,
    task_id: UUID | None,
    task_attempt_id: UUID | None,
    conversation_round_id: UUID | None,
    process_run_id: UUID | None,
) -> None:
    """Fail before persistence when a first-party purpose lost its durable owner."""

    normalized = str(purpose) if purpose is not None else None
    if normalized in _TASK_REQUIRED_PURPOSES and task_id is None:
        raise ValueError(f"LLM call purpose {normalized!r} requires a Task.")
    if normalized in _ROUND_REQUIRED_PURPOSES and conversation_round_id is None:
        raise ValueError(
            f"LLM call purpose {normalized!r} requires a conversation round."
        )
    if normalized in _PROCESS_REQUIRED_PURPOSES and process_run_id is None:
        raise ValueError(
            f"LLM call purpose {normalized!r} requires a ProcessRun."
        )
    if (
        normalized == LLMCallPurpose.AGENT_DISPATCH.value
        and task_id is None
        and conversation_round_id is None
    ):
        raise ValueError(
            "An agent dispatcher LLM call requires a Task or conversation round."
        )
    if (
        task_id is not None
        and normalized in _ATTEMPT_REQUIRED_PURPOSES
        and task_attempt_id is None
    ):
        raise RuntimeError(
            f"Task {task_id} has no active attempt for LLM call purpose {normalized!r}."
        )


def _project_trace_prompt(
    *,
    purpose: str | None,
    request_prompt: str,
    task_objective: str,
) -> str:
    """Prefer the durable Task objective over runtime-added user reminders."""

    objective = task_objective.strip()
    if purpose == LLMCallPurpose.AGENT_EXEC and objective:
        return objective
    return request_prompt


def apply_agent_scope(
    query: Select[Any],
    agent_ids: Collection[int] | None,
) -> Select[Any]:
    """Restrict human-facing call traces to their effective Agent scope."""

    if agent_ids is None:
        return query
    normalized = tuple(dict.fromkeys(agent_ids))
    if not normalized:
        return query.where(false())

    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.messenger import Room
    from app.process import ProcessRun
    from app.task import Task

    return query.where(
        or_(
            _call_columns.agent_id.in_(normalized),
            exists(
                select(Task.id).where(
                    Task.id == _call_columns.task_id,
                    Task.agent_id.in_(normalized),
                    Task.deleted_at.is_(None),
                )
            ),
            exists(
                select(ConversationRound.id)
                .join(Room, Room.id == ConversationRound.room_id)
                .join(Connection, Connection.id == Room.connection_id)
                .where(
                    ConversationRound.id == _call_columns.conversation_round_id,
                    Connection.agent_id.in_(normalized),
                    Room.deleted_at.is_(None),
                )
            ),
            exists(
                select(ProcessRun.id).where(
                    ProcessRun.id == _call_columns.process_run_id,
                    ProcessRun.launcher_agent_id.in_(normalized),
                    ProcessRun.deleted_at.is_(None),
                )
            ),
        )
    )


def task_owned_call_predicates() -> tuple[ColumnElement[bool], ...]:
    """Distinguish Task pipeline calls from traces linked only as provenance.

    A Task created by a conversation or Process owns its ``agent.*`` pipeline calls
    while retaining that provenance. A direct ``process.exec`` or background mechanism
    can still carry a Task only as context and therefore remains outside Task accounting.
    An embedded attempt's exact reference also includes the specialist calls it started.
    """

    return (or_(
        and_(LLMCall.correlation_ref.is_(None), or_(
            LLMCall.process_run_id.is_(None),
            LLMCall.purpose.in_(tuple(_ATTEMPT_REQUIRED_PURPOSES)),
        )),
        and_(LLMCall.task_attempt_id.is_not(None), LLMCall.correlation_ref == func.concat(
            "task:", LLMCall.task_id, ":attempt:", LLMCall.task_attempt_id,
        )),
    ),)


def _optional_uuid(value: object, *, field: str) -> UUID | None:
    if value is None or not str(value).strip():
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field} on the durable Task.") from exc


async def _task_call_lineage(
    *,
    task_id: UUID,
    agent_id: int | None,
    conversation_round_id: UUID | None,
    process_run_id: UUID | None = None,
    admitted_attempt_id: UUID | None = None,
) -> tuple[str, UUID | None, UUID | None, UUID | None, int | None]:
    """Resolve the Task's requester, attempt, conversation, and Process lineage."""

    from app.conversation import ConversationTaskLink
    from app.task.models import Task, TaskAttempt

    db = get_db()
    task = await db.get(Task, task_id)
    if task is None:
        raise LookupError(
            render_prompt(
                await tr("llm_api.errors.task_not_found"),
                task_id=task_id,
            )
        )
    if agent_id is not None and task.agent_id != agent_id:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.task_wrong_runtime_agent"),
                task_id=task_id,
                agent_id=agent_id,
            )
        )

    linked_round_id = await db.scalar(
        select(ConversationTaskLink.round_id).where(
            ConversationTaskLink.task_id == task_id
        )
    )
    data = task.data if isinstance(task.data, dict) else {}
    stored_round_id = _optional_uuid(
        data.get("conversation_round_id"),
        field="conversation_round_id",
    )
    if (
        linked_round_id is not None
        and stored_round_id is not None
        and linked_round_id != stored_round_id
    ):
        raise ValueError(
            f"Task {task_id} has conflicting conversation round lineage."
        )
    expected_round_id = linked_round_id or stored_round_id
    if (
        conversation_round_id is not None
        and expected_round_id is not None
        and conversation_round_id != expected_round_id
    ):
        raise ValueError(
            f"Task {task_id} belongs to conversation round {expected_round_id}, "
            f"not {conversation_round_id}."
        )
    resolved_round_id = conversation_round_id or expected_round_id
    stored_process_run_id = _optional_uuid(
        data.get("process_run_id"),
        field="process_run_id",
    )
    if (
        process_run_id is not None
        and stored_process_run_id is not None
        and process_run_id != stored_process_run_id
    ):
        raise ValueError(
            f"Task {task_id} belongs to ProcessRun {stored_process_run_id}, "
            f"not {process_run_id}."
        )
    resolved_process_run_id = process_run_id or stored_process_run_id

    task_attempt_id: UUID | None = None
    if admitted_attempt_id is not None:
        attempt = await db.get(TaskAttempt, admitted_attempt_id)
        if attempt is None or attempt.task_id != task_id:
            raise ValueError("The admitted attempt does not belong to the task.")
        task_attempt_id = attempt.id
    elif task.lease_token is not None:
        task_attempt_id = await db.scalar(
            select(TaskAttempt.id).where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.lease_token == task.lease_token,
            )
        )
    return (
        str(task.objective or ""),
        task_attempt_id,
        resolved_round_id,
        resolved_process_run_id,
        task.requester_user_id,
    )


def _public(call: LLMCall) -> dict[str, Any]:
    payload = LLMCallRead.model_validate(call).model_dump(mode="json")
    payload["response_text"] = _clean_text(payload.get("response_text"))
    payload["reasoning"] = _clean_text(payload.get("reasoning"))
    payload["tool_calls"] = [
        tool for tool in (_clean_tool_call(raw) for raw in as_list(payload.get("tool_calls")))
        if tool is not None
    ]
    return payload


def _clean_text(value: Any) -> str:
    text = content_to_text(value).strip()
    return text if text else ""


def _clean_tool_call(raw: Any) -> dict[str, Any] | None:
    tool = normalize_deferred_tool_calls([as_dict(raw)])[0]
    result_is_known = "result" in tool
    result = _clean_text(tool.get("result")) if result_is_known else None
    arguments = as_dict(tool.get("arguments"))
    if result_is_known:
        tool["result"] = result
        if not result and not arguments:
            return None
    tool["arguments"] = arguments
    return tool


def _lineage_score(candidate_messages: Any, current: list[dict[str, Any]]) -> int:
    """Length of the shared prefix between a call history and the current request.

    A call that emitted a tool has a history prefixing the request carrying its result. Parallel
    sessions diverge at their root, so this score disambiguates reused provider tool-call IDs.
    """
    if not isinstance(candidate_messages, list):
        return 0
    matched = 0
    for previous, now_message in zip(as_list(candidate_messages), current):
        prev = as_dict(previous)
        prev_key = (str(prev.get("role") or ""), content_to_text(prev.get("content"))) \
            if isinstance(previous, dict) else None
        now_key = (str(now_message.get("role") or ""), content_to_text(now_message.get("content")))
        if prev_key != now_key:
            break
        matched += 1
    return matched


async def list_calls(
    *,
    task_id: Optional[UUID] = None,
    task_ids: Sequence[UUID] | None = None,
    task_attempt_id: Optional[UUID] = None,
    agent_run_id: Optional[UUID] = None,
    agent_run_ids: Sequence[UUID] | None = None,
    conversation_round_id: Optional[UUID] = None,
    deep_room_id: UUID | None = None,
    process_run_id: Optional[UUID] = None,
    limit: int = 200,
    agent_ids: Collection[int] | None = None,
) -> list[LLMCall]:
    db = get_db()
    query = select(LLMCall).order_by(LLMCall.started_at.desc()).limit(limit)
    if task_id is not None:
        query = query.where(
            LLMCall.task_id == task_id,
            *task_owned_call_predicates(),
        )
    if task_ids is not None:
        normalized_task_ids = tuple(dict.fromkeys(task_ids))
        if not normalized_task_ids:
            return []
        query = query.where(
            LLMCall.task_id.in_(normalized_task_ids),
            *task_owned_call_predicates(),
        )
    if task_attempt_id is not None:
        query = query.where(LLMCall.task_attempt_id == task_attempt_id)
    if agent_run_id is not None:
        query = query.where(LLMCall.agent_run_id == agent_run_id)
    if agent_run_ids is not None:
        query = query.where(LLMCall.agent_run_id.in_(agent_run_ids))
    if conversation_round_id is not None:
        query = query.where(LLMCall.conversation_round_id == conversation_round_id)
    if process_run_id is not None:
        query = query.where(LLMCall.process_run_id == process_run_id)
    query = apply_agent_scope(query, agent_ids)
    query = _apply_deep_room(query, deep_room_id)
    return list(reversed((await db.execute(query)).scalars().all()))


async def list_running_calls(
    *,
    limit: int = 10,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    deep_room_id: UUID | None = None,
    agent_ids: Collection[int] | None = None,
) -> list[LLMCall]:
    """Return the currently running calls, newest first."""
    db = get_db()
    query = select(LLMCall).where(LLMCall.status == "running")
    query = _apply_call_date_range(query, date_from, date_to)
    query = apply_agent_scope(query, agent_ids)
    query = _apply_deep_room(query, deep_room_id)
    query = query.order_by(LLMCall.started_at.desc(), LLMCall.id.desc()).limit(limit)
    return list((await db.execute(query)).scalars().all())


def _apply_deep_room(query: Select[Any], room_id: UUID | None) -> Select[Any]:
    if room_id is None:
        return query
    from app.conversation import DeepSession

    return query.where(_call_columns.deep_session_id.in_(select(DeepSession.id).where(DeepSession.room_id == room_id)))


def _apply_call_date_range(
    query: Select[Any],
    date_from: Optional[date],
    date_to: Optional[date],
) -> Select[Any]:
    if date_from is not None:
        query = query.where(
            _call_columns.started_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        exclusive_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        query = query.where(_call_columns.started_at < exclusive_end)
    return query


async def paginate_history(
    *,
    page: int = 1,
    page_size: int = 50,
    errors_only: bool = False,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    deep_room_id: UUID | None = None,
    agent_ids: Collection[int] | None = None,
) -> tuple[list[LLMCall], int, LLMCallSummary]:
    """Return one newest-first page of calls that are no longer running."""
    db = get_db()
    history_filter = _call_columns.status != "running"
    error_filter = _call_columns.status.not_in(("running", "completed", "cancelled"))
    page_filter = error_filter if errors_only else history_filter
    visible = _call_columns.deleted_at.is_(None)
    # Read the physical table for accounting, including calls hidden from the log.
    totals_query = select(
        func.count(_call_columns.id).filter(visible, page_filter),
        func.count(_call_columns.id).filter(visible, _call_columns.status == "running"),
        func.count(_call_columns.id).filter(visible, _call_columns.status == "completed"),
        func.count(_call_columns.id).filter(visible, error_filter),
        func.coalesce(func.sum(_call_columns.cost), 0.0),
        func.coalesce(func.sum(_call_columns.inference_cost), 0.0),
    )
    totals_query = _apply_call_date_range(totals_query, date_from, date_to)
    totals_query = apply_agent_scope(totals_query, agent_ids)
    totals_query = _apply_deep_room(totals_query, deep_room_id)
    total, running, completed, errors, total_cost, total_inference_cost = (
        await db.execute(totals_query)
    ).one()
    summary = LLMCallSummary(
        running=int(running),
        completed=int(completed),
        errors=int(errors),
        total_cost=float(total_cost),
        total_inference_cost=float(total_inference_cost),
    )
    query = select(LLMCall).where(page_filter)
    query = _apply_call_date_range(query, date_from, date_to)
    query = apply_agent_scope(query, agent_ids)
    query = _apply_deep_room(query, deep_room_id)
    query = (
        query.order_by(LLMCall.started_at.desc(), LLMCall.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(query)).scalars().all()), int(total), summary


async def serialize_calls(calls: Sequence[LLMCall]) -> list[LLMCallRead]:
    """Serialize calls with bulk-loaded supervision context."""
    if not calls:
        return []

    from app.agent.models import Agent
    from app.process.models import ProcessDefinition, ProcessRun
    from app.task.models import Task, TaskStatus

    db = get_db()
    payloads = {call.id: _public(call) for call in calls}
    deep_sessions = {call.deep_session_id for call in calls if call.deep_session_id is not None}
    if deep_sessions:
        from app.conversation import DeepSession

        rooms = {session_id: room_id for session_id, room_id in (await db.execute(
            select(DeepSession.id, DeepSession.room_id).where(DeepSession.id.in_(deep_sessions)),
        )).all()}
        for call in calls:
            if call.deep_session_id is not None:
                payloads[call.id]["deep_room_id"] = rooms.get(call.deep_session_id)
    by_round: dict[UUID, list[dict[str, Any]]] = {}
    by_task: dict[UUID, list[dict[str, Any]]] = {}
    by_agent: dict[int, list[dict[str, Any]]] = {}
    by_process: dict[UUID, list[dict[str, Any]]] = {}
    for call in calls:
        payload = payloads[call.id]
        if call.conversation_round_id is not None:
            by_round.setdefault(call.conversation_round_id, []).append(payload)
        if call.task_id is not None:
            by_task.setdefault(call.task_id, []).append(payload)
        if call.agent_id is not None:
            by_agent.setdefault(call.agent_id, []).append(payload)
        if call.process_run_id is not None:
            by_process.setdefault(call.process_run_id, []).append(payload)

    # Calls created before conversation purposes were propagated were persisted as
    # ``agent.exec``. The durable round is authoritative for the medium, so repair the
    # presentation in bulk without rewriting history or guessing from prompts.
    legacy_conversation_round_ids = {
        call.conversation_round_id
        for call in calls
        if call.task_id is None
        and call.conversation_round_id is not None
        and payloads[call.id].get("purpose")
        in (None, LLMCallPurpose.AGENT_EXEC.value)
    }
    if legacy_conversation_round_ids:
        from app.conversation import ConversationRound

        rows = (
            await db.execute(
                select(ConversationRound.id, ConversationRound.voice_session_id).where(
                    ConversationRound.id.in_(legacy_conversation_round_ids)
                )
            )
        ).all()
        for conversation_round_id, voice_session_id in rows:
            purpose = (
                LLMCallPurpose.CONVERSATION_AUDIO
                if voice_session_id is not None
                else LLMCallPurpose.CONVERSATION_TEXT
            )
            for payload in by_round[conversation_round_id]:
                payload["purpose"] = purpose.value

    task_ids = set(by_task)
    if task_ids:
        rows = (
            await db.execute(
                select(Task.id, Task.label, Task.objective, Task.status).where(
                    Task.id.in_(task_ids),
                    Task.deleted_at.is_(None),
                )
            )
        ).all()
        for task_id, label, objective, status in rows:
            for payload in by_task[task_id]:
                payload["task_label"] = label
                payload["task_status"] = (
                    status.value if isinstance(status, TaskStatus) else str(status)
                )
                if payload["usage"].get("trace_retention") != "expired":
                    payload["prompt"] = _project_trace_prompt(
                        purpose=(
                            str(payload["purpose"])
                            if payload.get("purpose") is not None
                            else None
                        ),
                        request_prompt=str(payload.get("prompt") or ""),
                        task_objective=str(objective or ""),
                    )

    agent_ids = set(by_agent)
    if agent_ids:
        rows = (
            await db.execute(
                select(
                    Agent.id,
                    Agent.first_name,
                    Agent.last_name,
                    Agent.code,
                ).where(
                    Agent.id.in_(agent_ids),
                    Agent.deleted_at.is_(None),
                )
            )
        ).all()
        for agent_id, first_name, last_name, code in rows:
            name = f"{first_name} {last_name}".strip()
            for payload in by_agent[agent_id]:
                payload["agent_name"] = name
                payload["agent_code"] = code

    process_run_ids = set(by_process)
    if process_run_ids:
        rows = (
            await db.execute(
                select(ProcessRun.id, ProcessDefinition.label)
                .join(
                    ProcessDefinition,
                    ProcessDefinition.id == ProcessRun.process_id,
                )
                .where(
                    ProcessRun.id.in_(process_run_ids),
                    ProcessRun.deleted_at.is_(None),
                )
            )
        ).all()
        for process_run_id, label in rows:
            for payload in by_process[process_run_id]:
                payload["process_label"] = label

    return [LLMCallRead.model_validate(payloads[call.id]) for call in calls]


async def serialize_call(call: LLMCall) -> LLMCallRead:
    """Serialize one call with the same context exposed by list endpoints."""
    return (await serialize_calls([call]))[0]


async def get_call(
    call_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> Optional[LLMCall]:
    query = apply_agent_scope(
        select(LLMCall).where(LLMCall.id == call_id),
        agent_ids,
    )
    return await get_db().scalar(query)


async def cost_for_task(task_id: UUID) -> float | None:
    """Return total provider-call cost for a task, or ``None`` when no calls exist."""
    result = await get_db().execute(
        select(func.count(LLMCall.id), func.coalesce(func.sum(LLMCall.cost), 0.0))
        .where(LLMCall.task_id == task_id, *task_owned_call_predicates())
        .execution_options(include_historized=True)
    )
    count, cost = result.one()
    return float(cost) if count else None


async def _cancel_running_calls(
    calls: Sequence[LLMCall],
    *,
    now: datetime,
    reason: str,
) -> int:
    """Close traces without discarding usage, token, cost, or partial output data."""

    if not calls:
        return 0
    db = get_db()
    for call in calls:
        call.status = "cancelled"
        call.completed_at = now
        call.duration = max(0.0, (now - call.started_at).total_seconds())
        call.error = call.error or reason
    await db.commit()
    for call in calls:
        await websocket.emit("llm_call", "update", _public(call), None)
    return len(calls)


async def cancel_running_calls_for_tasks(
    task_ids: Sequence[UUID],
    *,
    reason: str = "LLM trace stopped because its Task was deleted.",
) -> int:
    """Close running traces for deleted Tasks while retaining their accounting data."""

    normalized_ids = tuple(dict.fromkeys(task_ids))
    if not normalized_ids:
        return 0
    calls = list(
        (
            await get_db().scalars(
                select(LLMCall)
                .where(
                    LLMCall.status == "running",
                    LLMCall.task_id.in_(normalized_ids),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    return await _cancel_running_calls(
        calls,
        now=datetime.now(timezone.utc),
        reason=reason,
    )


def _default_stale_after() -> timedelta:
    """Allow the configured Task inactivity timeout plus a finalization safety margin."""

    from core.params import runtime_settings

    seconds = runtime_settings.TASK_ACTION_TIMEOUT_SECONDS + _STALE_CALL_GRACE_SECONDS
    return timedelta(seconds=seconds)


async def reconcile_stale_running_calls(
    *,
    now: datetime | None = None,
    stale_after: timedelta | None = None,
) -> int:
    """Close abandoned traces, never deleting their usage or partial response.

    A trace is eligible immediately for a deleted Task or a terminal execution.
    Otherwise it must be stale and have no live provider permit. A stream without
    observers may have no partial trace writes for its entire lifetime.
    """

    from app.task.models import Task, TaskStatus
    from .provider_scheduler import active_call_ids
    from .models import LLMProviderPermit
    from .provider_permits import discard_expired_permits

    current_time = now or datetime.now(timezone.utc)
    idle_limit = stale_after or _default_stale_after()
    stale_before = current_time - idle_limit
    active_calls = active_call_ids()
    rows = (
        await get_db().execute(
            select(LLMCall, Task.deleted_at, Task.status)
            .outerjoin(Task, Task.id == LLMCall.task_id)
            .where(
                LLMCall.status == "running",
                # Durable inference leases own recovery for these calls, including
                # providers that remain silent longer than the Task timeout.
                LLMCall.inference_attempt_id.is_(None),
                or_(
                    Task.deleted_at.is_not(None),
                    and_(
                        LLMCall.purpose == LLMCallPurpose.AGENT_EXEC,
                        Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                    ),
                    and_(LLMCall.updated_at <= stale_before, LLMCall.id.not_in(active_calls),
                         ~select(LLMProviderPermit.call_id).where(LLMProviderPermit.call_id == LLMCall.id,
                             LLMProviderPermit.expires_at > func.clock_timestamp()).exists()),
                ),
            )
            .order_by(LLMCall.updated_at.asc(), LLMCall.id.asc())
            .limit(_RECONCILIATION_BATCH_SIZE)
            .with_for_update(of=LLMCall, skip_locked=True)
            .execution_options(include_historized=True)
        )
    ).all()
    if not rows:
        await discard_expired_permits()
        return 0

    calls: list[LLMCall] = []
    for call, deleted_at, task_status in rows:
        call.status = "cancelled"
        call.completed_at = current_time
        call.duration = max(0.0, (current_time - call.started_at).total_seconds())
        if call.error is None:
            call.error = (
                "LLM trace stopped because its Task was deleted."
                if deleted_at is not None
                else (
                    "LLM trace stopped after its Task reached terminal status "
                    f"{task_status.value}."
                    if task_status in (TaskStatus.SUCCESS, TaskStatus.ERROR)
                    and call.purpose == LLMCallPurpose.AGENT_EXEC
                    else (
                        "LLM trace stopped after no persisted activity for "
                        f"{int(idle_limit.total_seconds())} seconds."
                    )
                )
            )
        calls.append(call)
    await get_db().flush()
    await discard_expired_permits()
    await get_db().commit()
    for call in calls:
        await websocket.emit("llm_call", "update", _public(call), None)
    reconciled = len(calls)
    if reconciled:
        logger.warning(
            "LLM trace reconciler closed {} abandoned running call(s) without "
            "deleting accounting data",
            reconciled,
        )
    return reconciled


async def cleanup_all(*, agent_ids: Collection[int] | None = None) -> None:
    """Hide eligible calls and preserve their accounting history."""
    from .retention import prune_traces

    db = get_db()
    while await prune_traces(hide=True, agent_ids=agent_ids):
        await db.commit()
    await db.commit()
    await websocket.emit("llm_call", "cleanup", {}, None)


async def delete_call(
    call_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> bool:
    """Hide a completed trace while keeping the physical call in history."""
    from .retention import prune_traces

    db = get_db()
    query = apply_agent_scope(
        select(LLMCall.id, LLMCall.agent_id, LLMCall.task_id, LLMCall.conversation_round_id,
               LLMCall.process_run_id, LLMCall.deleted_at).where(LLMCall.id == call_id),
        agent_ids,
    ).execution_options(include_historized=True)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        return False
    if row.deleted_at is not None:
        return True
    if not await prune_traces(hide=True, agent_ids=agent_ids, call_id=call_id):
        if await db.scalar(select(LLMCall.deleted_at).where(LLMCall.id == call_id)
                           .execution_options(include_historized=True)) is not None:
            return True
        raise InferenceCallDeletionError("This call is running or its trace is still needed.")
    event = {
        "id": str(call_id),
        "agent_id": row.agent_id,
        "task_id": str(row.task_id) if row.task_id else None,
        "conversation_round_id": str(row.conversation_round_id) if row.conversation_round_id else None,
        "process_run_id": str(row.process_run_id) if row.process_run_id else None,
    }
    await db.commit()
    await websocket.emit("llm_call", "delete", event, None)
    return True


async def stop_call(
    call_id: UUID, *, agent_ids: Collection[int] | None = None,
) -> bool:
    """Request provider cancellation while retaining accounting and journal events.

    Lock the inference before checking its generation: a stale UI must never stop
    a replacement attempt. Repeated stops and calls already finished are harmless.
    """
    from . import inference_store
    from .models import LLMInferenceAttempt

    db = get_db()
    call = await get_call(call_id, agent_ids=agent_ids)
    if call is None:
        return False
    if call.inference_attempt_id is None:
        raise ValueError("This call has no controllable inference.")
    inference_id = await db.scalar(
        select(LLMInferenceAttempt.inference_id).where(
            LLMInferenceAttempt.id == call.inference_attempt_id,
        )
    )
    if inference_id is None:
        return False
    operation, attempt = await inference_store.locked(inference_id)
    await db.refresh(call)
    if (
        attempt.id == call.inference_attempt_id
        and call.status == "running"
        and operation.status in {"running", "pausing"}
    ):
        await inference_store.command(inference_id, "stop", uuid4())
    await db.commit()
    return True


async def attach_tool_results(
    *,
    messages: list[dict[str, Any]],
    agent_id: Optional[int],
    task_id: Optional[UUID] = None,
    conversation_round_id: Optional[UUID] = None,
) -> None:
    """Attach incoming tool results to previously recorded tool calls.

    Matching uses ``tool_call_id`` shared by the model request and the next request's tool-result
    message. The scan is scoped to the calling agent and falls back to task ID when the agent is
    unknown. Conversation-prefix scoring resolves provider IDs reused across parallel sessions.
    """
    from .retention import call_trace_is_expired

    raw_results = {
        str(message.get("tool_call_id")): message.get("content")
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    if not raw_results:
        return
    results = as_dict(await asyncio.to_thread(compact_trace_images, raw_results))
    query = select(LLMCall).options(
        load_only(LLMCall.id, LLMCall.tool_calls, raiseload=True),
    ).where(~call_trace_is_expired()).order_by(LLMCall.started_at.desc()).limit(200)
    if task_id is not None:
        query = query.where(LLMCall.task_id == task_id)
    elif conversation_round_id is not None:
        query = query.where(
            LLMCall.conversation_round_id == conversation_round_id
        )
    elif agent_id is not None:
        query = query.where(LLMCall.agent_id == agent_id)
    else:
        return
    db = get_db()
    calls = list((await db.execute(query)).scalars().all())
    tools_by_call = {call.id: [dict(tool) for tool in (call.tool_calls or [])] for call in calls}

    # Candidate call and tool index for every tool-call ID still awaiting a result.
    candidates: dict[str, list[tuple[UUID, int]]] = {}
    for call in calls:
        for index, tool in enumerate(tools_by_call[call.id]):
            service_id = str(tool.get("id") or "")
            if service_id in results and "result" not in tool:
                candidates.setdefault(service_id, []).append((call.id, index))

    if not candidates:
        return
    # Full traces are needed for lineage ties and the unchanged websocket payload,
    # not for the other calls in the bounded history window.
    matching_ids = {call_id for hits in candidates.values() for call_id, _ in hits}
    matched = (await db.scalars(
        select(LLMCall)
        .where(LLMCall.id.in_(matching_ids), ~call_trace_is_expired())
        .order_by(LLMCall.completed_at, LLMCall.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )).all()
    call_by_id = {call.id: call for call in matched}
    for call in matched:
        tools_by_call[call.id] = [dict(tool) for tool in call.tool_calls]
    now = datetime.now(timezone.utc).isoformat()
    dirty: set[UUID] = set()
    for service_id, hits in candidates.items():
        hits = [
            (call_id, index) for call_id, index in hits
            if call_id in call_by_id
            and index < len(tools_by_call[call_id])
            and str(tools_by_call[call_id][index].get("id") or "") == service_id
            and "result" not in tools_by_call[call_id][index]
        ]
        if not hits:
            continue
        if len(hits) > 1:
            # Disambiguate IDs reused across parallel sessions by conversation lineage.
            hits = [max(hits, key=lambda h: _lineage_score(call_by_id[h[0]].request_messages, messages))]
        call_id, index = hits[0]
        tool = tools_by_call[call_id][index]
        if "started_at" not in tool:
            tool["started_at"] = call_by_id[call_id].started_at.isoformat()
        tool["result"] = results[service_id]
        tool["status"] = "completed"
        tool["completed_at"] = now
        dirty.add(call_id)

    changed = [call_by_id[call_id] for call_id in dirty]
    for call in changed:
        call.tool_calls = tools_by_call[call.id]
    if changed:
        await db.commit()
        for call in changed:
            await websocket.emit("llm_call", "update", _public(call), None)


def _merge_tool_results(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    started_at: datetime | None = None,
) -> list[dict[str, Any]]:
    previous_by_id = {str(tool.get("id") or ""): tool for tool in previous}
    start_value = (started_at or datetime.now(timezone.utc)).isoformat()
    merged: list[dict[str, Any]] = []
    for raw_tool in current:
        tool = dict(raw_tool)
        old = previous_by_id.get(str(tool.get("id") or ""))
        tool["started_at"] = old.get("started_at") if old else start_value
        if old and "result" in old:
            tool["result"] = old["result"]
            tool["status"] = old.get("status", "completed")
            tool["completed_at"] = old.get("completed_at")
        merged.append(tool)
    return merged


async def update_running_call(
    call_id: UUID,
    *,
    trace: dict[str, Any],
    first_token_at: Optional[datetime] = None,
    input_rate: float | None = None,
    cached_input_rate: float | None = None,
    output_rate: float | None = None,
) -> None:
    """Publish a partial trace while the provider is streaming."""
    response_text, reasoning, current_tools = await asyncio.to_thread(_compact_trace_output, trace)
    # Do not fetch prompts, input messages or raw responses on every heartbeat.
    fields = (
        "id", "status", "purpose", "task_id", "agent_id", "agent_run_id", "conversation_round_id", "correlation_ref",
        "process_run_id", "response_text", "reasoning", "tool_calls", "updated_at",
        "usage", "is_subscription", "provider_code", "first_token_at", "started_at",
        "duration", "completed_at", "cost", "inference_cost", "cost_estimated", "finish_reason",
        "upstream_request_id", "input_tokens", "output_tokens", "total_tokens",
        "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
    )
    async with AsyncSessionLocal() as db:
        call = await db.scalar(select(LLMCall).where(LLMCall.id == call_id).options(
            load_only(LLMCall.deleted_at, *(getattr(LLMCall, name) for name in fields), raiseload=True),
        ).with_for_update())
        if call is None or call.status != "running":
            return
        previous_text, previous_reasoning = call.response_text or "", call.reasoning or ""
        previous_tools = call.tool_calls or []
        base_updated_at = call.updated_at
        usage = as_dict(trace.get("usage"))
        call.response_text = response_text
        call.reasoning = reasoning
        now = datetime.now(timezone.utc)
        call.tool_calls = _merge_tool_results(
            call.tool_calls or [],
            current_tools,
            started_at=now,
        )
        call.finish_reason = trace.get("finish_reason")
        _update_call_cost(call, usage, input_rate, cached_input_rate, output_rate)
        call.upstream_request_id = trace.get("upstream_request_id")
        call.first_token_at = first_token_at or call.first_token_at
        call.duration = max(0.0, (now - call.started_at).total_seconds())
        await db.commit()
        record_persisted_call_cost(call.id, call.cost, inference_cost=call.inference_cost,
            cost_estimated=call.cost_estimated, is_subscription=call.is_subscription,
            status=call.status, usage=call.usage, purpose=call.purpose)
        payload: dict[str, Any] = {
            name: getattr(call, name) for name in fields
            if name not in {"response_text", "reasoning", "tool_calls", "started_at", "provider_code", "is_subscription"}
        }
        payload["base_updated_at"] = base_updated_at
        for name, previous, current in (
            ("response_text", previous_text, response_text),
            ("reasoning", previous_reasoning, reasoning),
        ):
            payload[name] = ({"append": current[len(previous):]} if current.startswith(previous)
                             else {"replace": current})
        if call.tool_calls != previous_tools:
            payload["tool_calls"] = [tool for tool in (
                _clean_tool_call(raw) for raw in call.tool_calls
            ) if tool is not None]
        payload = _PROGRESS_PAYLOAD_ADAPTER.dump_python(payload, mode="json")
    await websocket.emit("llm_call", "progress", payload, None)


async def create_running_call(
    *,
    purpose: str | None,
    task_id: Optional[UUID],
    task_attempt_id: UUID | None = None,
    agent_run_id: Optional[UUID],
    conversation_round_id: Optional[UUID] = None,
    agent_id: Optional[int],
    llm_id: int,
    provider_name: str,
    provider_code: Optional[str],
    requested_model: str,
    effective_model: str,
    reasoning_effort: ReasoningEffort | None = None,
    stream: bool,
    request_body: dict[str, Any],
    process_run_id: Optional[UUID] = None,
    media_generation_id: UUID | None = None,
    requester_user_id: int | None = None,
    is_subscription: bool = False,
    voice_dialogue: bool = False,
    sdk_request: bool = False,
) -> LLMCall:
    from .call_capture import text_call_capture

    capture = text_call_capture.get()
    embedded_origin = capture.embedded_origin if capture is not None else current_media_inference_origin(purpose)
    verify_internal_attempt = (sdk_request and embedded_origin is None and task_attempt_id is not None
                               and purpose == LLMCallPurpose.AGENT_EXEC)
    embedded_lineage = None
    if embedded_origin is not None:
        embedded_lineage = bind_embedded_call(
            embedded_origin, task_id=task_id, task_attempt_id=task_attempt_id, agent_id=agent_id,
            agent_run_id=agent_run_id, conversation_round_id=conversation_round_id, process_run_id=process_run_id,
        )
        agent_id, agent_run_id = embedded_origin.agent_id, embedded_origin.run_id
        task_id, task_attempt_id = embedded_lineage.task_id, embedded_lineage.task_attempt_id
        conversation_round_id = embedded_lineage.round_id
    if capture is not None and capture.call_limit is not None:
        if capture.calls_started >= capture.call_limit:
            raise RuntimeError("Inference physical call budget exhausted.")
        capture.calls_started += 1
    messages = as_list(request_body.get("messages"))
    typed_messages = [as_dict(m) for m in messages if isinstance(m, dict)]
    task_objective = ""
    task_requester_user_id = None
    if task_id is not None:
        (
            task_objective,
            task_attempt_id,
            conversation_round_id,
            process_run_id,
            task_requester_user_id,
        ) = (
            await _task_call_lineage(
                task_id=task_id,
                agent_id=agent_id,
                conversation_round_id=conversation_round_id,
                process_run_id=process_run_id,
                admitted_attempt_id=task_attempt_id,
            )
        )
    elif task_attempt_id is not None:
        raise ValueError("A task attempt requires its task.")
    round_ = None
    if conversation_round_id is not None:
        from app.connection import Connection
        from app.conversation import ConversationRound
        from app.messenger import Room

        round_ = await get_db().get(ConversationRound, conversation_round_id)
        conversation_agent_id: int | None = None
        if round_ is not None:
            conversation_agent_id = await get_db().scalar(
                select(Connection.agent_id)
                .join(Room, Room.connection_id == Connection.id)
                .where(Room.id == round_.room_id)
                .execution_options(include_historized=True)
            )
        if conversation_agent_id is None:
            raise LookupError(
                f"Conversation round {conversation_round_id} not found."
            )
        if agent_id is not None and conversation_agent_id != agent_id:
            raise ValueError(
                f"Conversation round {conversation_round_id} is not assigned "
                f"to agent {agent_id}."
            )
    if process_run_id is not None:
        from app.process import ProcessRun

        process_run = await get_db().get(ProcessRun, process_run_id)
        if process_run is None:
            raise LookupError(f"Process run {process_run_id} not found.")
        if (
            agent_id is not None
            and process_run.launcher_agent_id != agent_id
        ):
            from app.process.facade import is_activity_inference_agent
            if not await is_activity_inference_agent(process_run.id, agent_id, current_llm_correlation_ref()):
                raise ValueError(
                    f"Process run {process_run_id} is not assigned to agent "
                    f"{agent_id}."
                )
    _validate_semantic_lineage(
        purpose=purpose,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        conversation_round_id=conversation_round_id,
        process_run_id=process_run_id,
    )
    await attach_tool_results(
        messages=typed_messages,
        agent_id=agent_id,
        task_id=task_id,
        conversation_round_id=conversation_round_id,
    )
    prompt, system_prompt = extract_prompts(typed_messages)
    prompt = _project_trace_prompt(
        purpose=purpose,
        request_prompt=prompt,
        task_objective=task_objective,
    )
    stored_messages, stored_prompt, stored_system_prompt = await asyncio.to_thread(
        _compact_request_trace,
        typed_messages,
        prompt,
        system_prompt,
    )
    authority = current_execution_authority()
    api_token_label = authority.api_token_label if authority is not None else None
    if api_token_label is None:
        api_token_label = await get_current_token_label()
    if requester_user_id is None:
        requester_user_id = (get_current_user_id() or (authority.requester_user_id if authority else None)
                             or task_requester_user_id)
    from .profile_fallback import profile_fallback_route
    from .correlation import current_deep_session

    deep_session_id = None
    if task_id is None and conversation_round_id is None and process_run_id is None and media_generation_id is None:
        deep_session_id = embedded_lineage.deep_session_id if embedded_lineage is not None else current_deep_session()
        if deep_session_id is not None:
            from app.conversation import deep_session_agent

            session_agent = await deep_session_agent(deep_session_id)
            if session_agent is None or (agent_id is not None and session_agent != agent_id):
                raise ValueError("The Deep session does not belong to the inference agent.")
            agent_id = session_agent

    submission_id = embedded_lineage.source_id if embedded_lineage is not None and embedded_lineage.deep_session_id is not None else None
    if purpose == LLMCallPurpose.CONVERSATION_DEEP and submission_id is None:
        raise ValueError("A Deep call requires its admitted submission.")
    if submission_id is not None and (deep_session_id is None or submission_id != agent_run_id):
        raise ValueError("An embedded Deep call requires its session and submission.")
    fallback_route = profile_fallback_route.get()
    call = LLMCall(
        purpose=purpose,
        deep_session_id=deep_session_id,
        deep_submission_id=submission_id,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        process_run_id=process_run_id,
        media_generation_id=media_generation_id,
        requester_user_id=requester_user_id,
        api_token_label=api_token_label,
        correlation_ref=embedded_origin.correlation_ref if embedded_origin is not None else current_llm_correlation_ref(),
        agent_id=agent_id,
        llm_id=llm_id,
        provider_name=provider_name,
        fallback_profile_id=fallback_route.profile_id if fallback_route else None,
        fallback_from_llm_id=fallback_route.from_llm_id if fallback_route else None,
        fallback_reason=fallback_route.reason if fallback_route else None,
        provider_code=provider_code,
        requested_model=requested_model,
        effective_model=effective_model,
        reasoning_effort=reasoning_effort,
        status="running",
        stream=stream,
        request_messages=stored_messages,
        prompt=stored_prompt,
        system_prompt=stored_system_prompt,
        is_subscription=is_subscription,
    )
    from .admission import admission_context

    from app.task.facade import task_admission_roots
    roots = await task_admission_roots({task_id}) if task_id is not None else {}
    context = admission_context(
        call.purpose, task_id=call.task_id, conversation_round_id=call.conversation_round_id,
        agent_run_id=call.agent_run_id,
        media_generation_id=call.media_generation_id, process_run_id=call.process_run_id,
        authority=authority, agent_id=call.agent_id, requester_user_id=call.requester_user_id,
        round_is_voice=round_ is not None and round_.voice_session_id is not None,
        voice_dialogue=voice_dialogue,
        task_root=roots.get(task_id) if task_id is not None else None,
    )
    return await _admit_running_call(call, capture, context=context, embedded_origin=embedded_origin,
                                     verify_internal_attempt=verify_internal_attempt)


async def _admit_running_call(
    call: LLMCall, capture: TextCallCapture | None, *, context: AdmissionContext,
    embedded_origin: EmbeddedInferenceOrigin | None, verify_internal_attempt: bool,
) -> LLMCall:
    from . import provider_scheduler
    from .provider_models import LLM, LLMProvider
    from .subscription_policy import enforce_subscription_access
    from core.database import release_db_transaction
    import anyio

    db = get_db()
    provider = await db.scalar(
        select(LLMProvider).join(LLM, LLM.llm_provider_id == LLMProvider.id)
        .where(LLM.id == call.llm_id).execution_options(populate_existing=True)
    )
    if provider is None or not provider.is_active:
        raise LookupError("LLM provider is unavailable.")
    provider_id, limit = provider.id, provider.effective_max_concurrent_calls
    await release_db_transaction()
    permit = await provider_scheduler.acquire_call(
        provider_id, limit, context.priority, owner=context.owner, requester=context.requester, mission=context.mission,
    )
    persisted = False
    try:
        # A queued caller must not start after provider deactivation or after a
        # subscription authority has been revoked while it waited.
        from .provider_permits import lock_capacity
        provider = await lock_capacity(provider_id, context.priority)
        if isinstance(embedded_origin, EmbeddedTaskInference) and call.purpose == embedded_origin.purpose:
            call.requester_user_id = await embedded_origin.authorize(model_loop=True)
        elif embedded_origin is not None:
            call.requester_user_id = await embedded_origin.authorize()
        elif verify_internal_attempt:
            from app.task.facade import authorize_internal_task_inference

            if (call.task_id is None or call.task_attempt_id is None or call.agent_id is None
                    or call.agent_run_id is None):
                raise PermissionError("The Pydantic request has no complete Task attempt identity.")
            call.requester_user_id = await authorize_internal_task_inference(
                call.task_id, call.task_attempt_id, call.agent_id, run_id=call.agent_run_id,
            )
        await enforce_subscription_access(
            provider, task_id=call.task_id, conversation_round_id=call.conversation_round_id,
            process_run_id=call.process_run_id,
        )
        if embedded_origin is not None and call.purpose == embedded_origin.purpose:
            await _enforce_embedded_request_limit(call, embedded_origin)
        await _persist_running_call(call, capture, provider_id=provider_id, priority=context.priority)
        persisted = True
        provider_scheduler.bind_call(call.id, permit)
        from .provider_permits import start_renewal
        start_renewal()
        await websocket.emit("llm_call", "create", _public(call), None)
        return call
    except BaseException:
        with anyio.CancelScope(shield=True):
            if persisted:
                await finalize_call(call.id, trace={}, status="cancelled")
            else:
                await db.rollback()
        raise
    finally:
        if not persisted:
            permit.release()


async def _enforce_embedded_request_limit(call: LLMCall, origin: EmbeddedInferenceOrigin) -> None:
    """Reserve against the logical run, including after a change of worker or attempt."""
    db = get_db()
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"app.llm.embedded:{origin.run_id}", 0))))
    count = await db.scalar(select(func.count()).select_from(LLMCall).where(
        LLMCall.agent_run_id == origin.run_id,
        LLMCall.agent_id == origin.agent_id,
        LLMCall.purpose == origin.purpose,
        LLMCall.task_id == call.task_id,
        LLMCall.conversation_round_id == call.conversation_round_id,
        LLMCall.deep_session_id == call.deep_session_id,
    ).execution_options(include_historized=True))
    if count is not None and count >= (origin.request_limit or runtime_settings.TASK_AGENT_MAX_REQUESTS):
        raise EmbeddedRequestLimitExceeded("The embedded execution has reached its model request limit.")


async def _persist_running_call(call: LLMCall, capture: TextCallCapture | None, *, provider_id: int, priority: int) -> None:
    db = get_db()
    from .call_capture import inference_owner

    owner = inference_owner.get()
    if owner is not None:
        from .inference_store import owned

        await owned(owner)
        call.inference_attempt_id = owner.attempt_id
    from .user_attribution import resolve_call_user

    call.user_id = await resolve_call_user(db, call, get_current_user_id(), current_execution_authority())
    db.add(call)
    await db.flush()
    from .provider_permits import insert_permit
    await insert_permit(call.id, provider_id, priority)
    if capture is not None:
        from .models import LLMCallEvent

        await db.flush()
        db.add(LLMCallEvent(call_id=call.id, sequence=0, payload={
            "kind": "request", "request": capture.request,
        }))
    await db.commit()
    if capture is not None:
        capture.call_id = call.id
        capture.call_ids.append(call.id)


def _compact_request_trace(
    messages: list[dict[str, Any]],
    prompt: str,
    system_prompt: str,
) -> tuple[list[dict[str, Any]], str, str]:
    """Prepare all request-side trace fields for compact persistence."""
    stored_prompt = compact_trace_images(prompt)
    stored_system_prompt = compact_trace_images(system_prompt)
    return (
        compact_request_images(messages),
        stored_prompt if isinstance(stored_prompt, str) else "",
        stored_system_prompt if isinstance(stored_system_prompt, str) else "",
    )


def _compact_trace_output(
    trace: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]]]:
    """Prepare provider output fields for safe, compact persistence."""
    response_text = compact_trace_images(_clean_text(trace.get("response_text")))
    reasoning = compact_trace_images(_clean_text(trace.get("reasoning")))
    tool_calls = compact_trace_images(as_list(trace.get("tool_calls")))
    return (
        response_text if isinstance(response_text, str) else "",
        reasoning if isinstance(reasoning, str) else "",
        [as_dict(tool) for tool in as_list(tool_calls)],
    )


def _amount(value: Any) -> float | None:
    """Normalize a non-negative provider amount without accepting booleans or NaN."""

    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


def _reported_cost(
    usage: dict[str, Any],
    provider_code: str | None,
) -> float | None:
    accounting = usage_accounting_for(provider_code)
    if accounting is not None:
        provider_cost = _amount(accounting.inference_cost(usage))
        if provider_cost is not None:
            return provider_cost
    return _amount(usage.get("cost"))


def _cost(
    usage: dict[str, Any],
    counters: dict[str, int],
    input_rate: float | None,
    cached_input_rate: float | None,
    output_rate: float | None,
    provider_code: str | None = None,
) -> tuple[float, bool]:
    provider_cost = _reported_cost(usage, provider_code)
    if provider_cost is not None:
        return provider_cost, False
    if (_amount(input_rate) is None or _amount(output_rate) is None
            or (cached_input_rate is not None and _amount(cached_input_rate) is None)):
        return 0.0, True
    assert input_rate is not None and output_rate is not None
    prompt_details = as_dict(usage.get("prompt_tokens_details") or usage.get("input_tokens_details"))
    input_includes_cache = "prompt_tokens" in usage or "cached_tokens" in prompt_details
    value = token_cost(
        input_tokens=counters["input_tokens"],
        output_tokens=counters["output_tokens"],
        cache_read_tokens=counters["cache_read_tokens"],
        cache_write_tokens=counters["cache_write_tokens"],
        input_rate=float(input_rate),
        cached_input_rate=cached_input_rate,
        output_rate=float(output_rate),
        input_includes_cache=input_includes_cache,
    )
    return value, True


def _cost_usage(
    usage: dict[str, Any], input_rate: float | None, cached_input_rate: float | None,
    output_rate: float | None, estimated: bool, inference_cost: float,
) -> dict[str, Any]:
    """Freeze only the rates actually used; overwrite any provider-owned namesake."""
    tokens_present = (any(_amount(usage.get(key)) is not None for key in ("input_tokens", "prompt_tokens"))
                      and any(_amount(usage.get(key)) is not None for key in ("output_tokens", "completion_tokens")))
    valid_rates = (_amount(input_rate) is not None and _amount(output_rate) is not None
                   and (cached_input_rate is None or _amount(cached_input_rate) is not None))
    source = "provider" if not estimated else "pricing" if valid_rates and tokens_present else "unknown"
    return {**usage, COST_EVIDENCE_KEY: {"version": "llm-cost/v1", "currency": "USD", "source": source,
        **({"reported_inference_cost": inference_cost} if source == "provider" else {}),
        **({"input_rate": input_rate, "cached_input_rate": cached_input_rate,
            "output_rate": output_rate, "counters": usage_counters(usage),
            "input_includes_cache": "prompt_tokens" in usage or "cached_tokens" in
                as_dict(usage.get("prompt_tokens_details") or usage.get("input_tokens_details"))}
           if source == "pricing" else {})}}


def _update_call_cost(
    call: LLMCall, usage: dict[str, Any], input_rate: float | None, cached_input_rate: float | None,
    output_rate: float | None, *, terminal: bool = False,
) -> bool:
    """Keep terminal provider receipts and fill missing costs from reliable evidence."""
    counters = usage_counters(usage)
    inference_cost, estimated = _cost(usage, counters, input_rate, cached_input_rate, output_rate, call.provider_code)
    previous_usage = call.usage or {}
    previously_reported = as_dict(previous_usage.get(COST_EVIDENCE_KEY)).get("source") == "provider"
    if terminal and previously_reported:
        return False
    evidence = _cost_usage(usage, input_rate, cached_input_rate, output_rate, estimated, inference_cost)
    if terminal and estimated:
        if as_dict(evidence[COST_EVIDENCE_KEY]).get("source") != "pricing":
            return False
        previous_cost = call_cost(
            call_id=call.id, status=call.status, cost=call.cost, inference_cost=call.inference_cost,
            cost_estimated=call.cost_estimated, is_subscription=call.is_subscription, usage=previous_usage,
        )
        if previous_cost.inference_quality != "unknown":
            return False
    if previously_reported and estimated:
        evidence[COST_EVIDENCE_KEY] = previous_usage[COST_EVIDENCE_KEY]
    else:
        call.inference_cost = inference_cost
        call.cost = 0.0 if call.is_subscription else inference_cost
        call.cost_estimated = estimated
    if previous_usage.get("trace_retention") == "expired":
        evidence["trace_retention"] = "expired"
    call.usage = {**previous_usage, COST_EVIDENCE_KEY: evidence[COST_EVIDENCE_KEY]} if terminal else evidence
    if not terminal or estimated:
        for key, value in counters.items():
            setattr(call, key, value)
    return True


async def finalize_call(
    call_id: UUID,
    *,
    trace: dict[str, Any],
    raw_response: str | None = None,
    status: str = "completed",
    error: Optional[str] = None,
    input_rate: float | None = None,
    cached_input_rate: float | None = None,
    output_rate: float | None = None,
    first_token_at: Optional[datetime] = None,
    preserve_completed: bool = False,
    effective_model: str | None = None,
) -> None:
    """Finalize from an independent session, including after a streaming response."""
    from .provider_scheduler import release_call

    try:
        # Trace preparation may wait on the thread pool or process large payloads.
        # Do not hold the call lock: journal writers need it while owning the
        # inference lock, which would also stall heartbeats and lifecycle commands.
        response_text, reasoning, current_tools = await asyncio.to_thread(
            _compact_trace_output, trace
        )
        stored_error = await asyncio.to_thread(compact_trace_images, error)
        async with AsyncSessionLocal() as db:
            from .provider_permits import release_permit
            call = await db.scalar(select(LLMCall).where(LLMCall.id == call_id).with_for_update()
                                   .execution_options(include_historized=True))
            # The reconciler locks the call before removing its expired reservation.
            await release_permit(db, call_id)
            if call is None:
                await db.commit()
                return
            if preserve_completed and call.status == "completed" and status != "completed":
                await db.commit()
                return
            usage = as_dict(trace.get("usage"))
            if call.status != "running":
                if not usage or not _update_call_cost(
                    call, usage, input_rate, cached_input_rate, output_rate, terminal=True,
                ):
                    await db.commit()
                    return
            else:
                if effective_model is not None:
                    call.effective_model = effective_model
                now = datetime.now(timezone.utc)
                call.status = status
                if response_text or not call.response_text:
                    call.response_text = response_text
                if reasoning or not call.reasoning:
                    call.reasoning = reasoning
                if raw_response is not None:
                    call.raw_response = raw_response
                if current_tools:
                    call.tool_calls = _merge_tool_results(
                        call.tool_calls or [],
                        current_tools,
                        started_at=call.started_at,
                    )
                call.finish_reason = trace.get("finish_reason") or call.finish_reason
                if usage:
                    _update_call_cost(call, usage, input_rate, cached_input_rate, output_rate)
                call.upstream_request_id = (
                    trace.get("upstream_request_id") or call.upstream_request_id
                )
                call.error = stored_error if isinstance(stored_error, str) else None
                call.first_token_at = first_token_at or call.first_token_at
                call.completed_at = now
                call.duration = max(0.0, (now - call.started_at).total_seconds())
                if status not in {"running", "completed", "cancelled"}:
                    await _record_failure_incident(db, call)

            await db.commit()
            record_persisted_call_cost(call.id, call.cost, inference_cost=call.inference_cost,
                cost_estimated=call.cost_estimated, is_subscription=call.is_subscription,
                status=call.status, usage=call.usage, purpose=call.purpose)
            payload = _public(call) if call.deleted_at is None else None
    finally:
        release_call(call_id)
    if payload is not None:
        await websocket.emit("llm_call", "update", payload, None)


async def _record_failure_incident(db: AsyncSession, call: LLMCall) -> None:
    """Append the canonical failure snapshot without risking LLM finalization."""

    from core.failure_journal import (
        FailureEvent,
        record_failure_in_session,
    )

    error_message = str(call.error or f"LLM call ended with status {call.status}")
    error_type = error_message.partition(":")[0].strip()
    if not error_type or len(error_type) > 300 or " " in error_type:
        error_type = "LLMCallError"
    event = FailureEvent(
        idempotency_key=f"llm-call:{call.id}",
        kind="llm",
        occurred_at=call.completed_at or datetime.now(timezone.utc),
        phase="provider_response",
        error_type=error_type,
        error_message=error_message,
        retryable=None,
        will_retry=False,
        task_id=call.task_id,
        llm_call_id=call.id,
        conversation_round_id=call.conversation_round_id,
        process_run_id=call.process_run_id,
        agent_id=call.agent_id,
        run_uuid=call.agent_run_id,
        provider_code=call.provider_code,
        model_code=call.effective_model or call.requested_model,
        trace={
            "source": "llm_call",
            "llm_call": {
                "id": call.id,
                "purpose": call.purpose,
                "status": call.status,
                "stream": call.stream,
                "provider_name": call.provider_name,
                "provider_code": call.provider_code,
                "requested_model": call.requested_model,
                "effective_model": call.effective_model,
                "reasoning_effort": call.reasoning_effort,
                "request_messages": call.request_messages,
                "prompt": call.prompt,
                "system_prompt": call.system_prompt,
                "response_text": call.response_text,
                "reasoning": call.reasoning,
                "tool_calls": call.tool_calls,
                "raw_response": call.raw_response,
                "finish_reason": call.finish_reason,
                "usage": call.usage,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "total_tokens": call.total_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "cache_write_tokens": call.cache_write_tokens,
                "reasoning_tokens": call.reasoning_tokens,
                "cost": call.cost,
                "inference_cost": call.inference_cost,
                "upstream_request_external_id": call.upstream_request_id,
                "error": call.error,
                "started_at": call.started_at,
                "first_token_at": call.first_token_at,
                "completed_at": call.completed_at,
                "duration": call.duration,
            },
            "correlation": {
                "task_id": call.task_id,
                "run_uuid": call.agent_run_id,
                "conversation_round_id": call.conversation_round_id,
                "deep_submission_id": call.deep_submission_id,
                "process_run_id": call.process_run_id,
                "agent_id": call.agent_id,
                "correlation_ref": call.correlation_ref,
            },
        },
    )
    try:
        async with db.begin_nested():
            await record_failure_in_session(db, event)
    except Exception:
        logger.exception(
            "Could not persist LLM failure incident for call {}", call.id
        )
