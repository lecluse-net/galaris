"""Prune verbose traces while preserving accounting and active work."""

from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Collection
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, Text, and_, case, cast, column, delete, false, func, literal, or_, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.orm import load_only

from core.database import get_db
from core.params import runtime_settings
from .models import LLMCall, LLMCallEvent, LLMInference, LLMInferenceAttempt
from .timing import first_output_timestamp

TraceOwner = Literal["conversation_round", "process_run"]
_releases: dict[TraceOwner, Callable[[], Select[tuple[UUID]]]] = {}

_MAX_RETENTION_DAYS = 7
_ARCHIVED_PROMPT_LENGTH = 500
_EVENT_BATCH_SIZE = 5000
_EVENT_REPLAY_WINDOW = timedelta(minutes=10)
_CLOSED_CALL_STATUSES = ("completed", "error", "cancelled")
_CLOSED_ATTEMPT_STATUSES = ("completed", "failed", "stopped", "paused", "interrupted")


def _cutoff() -> datetime:
    configured = runtime_settings.LLM_TRACE_RETENTION_DAYS
    return datetime.now(timezone.utc) - timedelta(days=min(configured or _MAX_RETENTION_DAYS, _MAX_RETENTION_DAYS))


def _finished_attempt(cutoff: datetime | None, *, require_closed_inference: bool = False) -> ColumnElement[bool]:
    query = select(LLMInferenceAttempt.id).where(
        LLMInferenceAttempt.id == LLMCall.inference_attempt_id,
        LLMInferenceAttempt.status.in_(_CLOSED_ATTEMPT_STATUSES),
        LLMInferenceAttempt.completed_at.is_not(None) if cutoff is None else LLMInferenceAttempt.completed_at < cutoff,
        LLMInferenceAttempt.final_sequence.is_not(None),
        LLMInferenceAttempt.result.is_not(None),
    )
    if require_closed_inference:
        query = query.join(LLMInference).where(LLMInference.status.in_(("completed", "failed", "stopped")))
    return query.exists()


def call_trace_is_expired() -> ColumnElement[bool]:
    return LLMCall.usage["trace_retention"].astext.is_not_distinct_from("expired")


def _has_details() -> ColumnElement[bool]:
    return or_(
        LLMCall.system_prompt != "",
        LLMCall.raw_response != "",
        LLMCall.response_text != "",
        LLMCall.reasoning != "",
        LLMCall.request_messages != [],
        and_(~call_trace_is_expired(), or_(LLMCall.prompt != "", LLMCall.tool_calls != [])),
    )


def _tool_summaries() -> ColumnElement[list[dict[str, str]]]:
    """Project tool metadata in PostgreSQL without transferring the arguments or results."""
    empty = cast([], JSONB)
    tools = case((func.jsonb_typeof(LLMCall.tool_calls) == "array", LLMCall.tool_calls), else_=empty)
    entries = func.jsonb_array_elements(tools).table_valued(
        column("value", JSONB), with_ordinality="position",
    ).render_derived()
    tool = entries.c.value
    name = case(
        (tool["name"].astext == "tool_call",
         func.coalesce(func.nullif(func.btrim(tool["arguments"]["name"].astext), ""), tool["name"].astext)),
        else_=tool["name"].astext,
    )
    summary = func.jsonb_strip_nulls(func.jsonb_build_object(
        "id", tool["id"].astext,
        "type", tool["type"].astext,
        "name", name,
        "status", tool["status"].astext,
        "started_at", tool["started_at"].astext,
        "completed_at", tool["completed_at"].astext,
    ))
    return select(type_coerce(
        func.coalesce(func.jsonb_agg(aggregate_order_by(summary, entries.c.position)), empty), JSONB,
    )).where(func.jsonb_typeof(tool) == "object").correlate(LLMCall).scalar_subquery()


async def prune_call_events() -> int:
    """Expire replay buffers once the call and its durable attempt have settled."""
    cutoff = datetime.now(timezone.utc) - _EVENT_REPLAY_WINDOW
    db = get_db()
    call_ids = (await db.scalars(select(LLMCall.id).where(
        select(LLMCallEvent.id).where(LLMCallEvent.created_at < cutoff).correlate(None).exists(),
        LLMCall.status.in_(_CLOSED_CALL_STATUSES),
        LLMCall.completed_at < cutoff,
        or_(LLMCall.inference_attempt_id.is_(None), _finished_attempt(cutoff)),
        select(LLMCallEvent.id).where(
            LLMCallEvent.call_id == LLMCall.id, LLMCallEvent.created_at < cutoff,
        ).exists(),
    ).order_by(LLMCall.completed_at, LLMCall.id).limit(100).with_for_update(skip_locked=True)
        .execution_options(include_historized=True))).all()
    if not call_ids:
        return 0
    first_output = first_output_timestamp()
    await db.execute(update(LLMCall).where(
        LLMCall.id.in_(call_ids), LLMCall.first_output_at.is_(None), first_output.is_not(None),
    ).values(first_output_at=first_output, updated_at=LLMCall.updated_at)
        .execution_options(synchronize_session=False))
    expired = (
        select(LLMCallEvent.id)
        .where(LLMCallEvent.call_id.in_(call_ids), LLMCallEvent.created_at < cutoff)
        .order_by(LLMCallEvent.created_at, LLMCallEvent.id)
        .limit(_EVENT_BATCH_SIZE)
        .cte("expired_call_events")
    )
    removed = (
        delete(LLMCallEvent)
        .where(LLMCallEvent.id.in_(select(expired.c.id)))
        .returning(LLMCallEvent.id)
        .execution_options(synchronize_session=False)
        .cte("removed_call_events")
    )
    return int(await db.scalar(select(func.count()).select_from(removed)) or 0)


def register_trace_release(
    owner: TraceOwner, released_ids: Callable[[], Select[tuple[UUID]]]
) -> None:
    """Register the owning domain's positive proof of causal completion."""
    _releases[owner] = released_ids


async def preview_trace_retention(*, agent_ids: Collection[int] | None = None) -> dict[str, int]:
    """Count protection reasons without returning prompts or modifying rows."""
    from app.task import protected_task_ids
    from .llm_call_service import apply_agent_scope

    cutoff = _cutoff()
    conversation_released = (
        LLMCall.conversation_round_id.in_(_releases["conversation_round"]())
        if "conversation_round" in _releases
        else false()
    )
    process_released = (
        LLMCall.process_run_id.in_(_releases["process_run"]())
        if "process_run" in _releases
        else false()
    )
    reason = case(
        (and_(LLMCall.inference_attempt_id.is_not(None), ~_finished_attempt(cutoff)), "inference"),
        (LLMCall.status.not_in(_CLOSED_CALL_STATUSES), "active"),
        (
            or_(
                LLMCall.completed_at.is_(None),
                LLMCall.completed_at >= cutoff,
                LLMCall.updated_at.is_(None),
                LLMCall.updated_at >= cutoff,
            ),
            "recent",
        ),
        (and_(LLMCall.conversation_round_id.is_not(None), ~conversation_released), "conversation"),
        (and_(LLMCall.process_run_id.is_not(None), ~process_released), "process"),
        (LLMCall.task_id.in_(protected_task_ids()), "task"),
        else_="eligible",
    )
    statement = select(reason, func.count()).where(_has_details())
    statement = apply_agent_scope(statement, agent_ids)
    rows = await get_db().execute(statement.group_by(reason))
    return {str(reason): int(count) for reason, count in rows}


async def prune_traces(
    *, preview: bool = False, batch_size: int = 100, hide: bool = False,
    agent_ids: Collection[int] | None = None, call_id: UUID | None = None,
) -> int:
    """Compact diagnostic payloads and optionally hide them from the log.

    Calls tied to unregistered or unfinished consumers are retained. Task calls
    are retained while their causal component has active work. Usage, costs,
    timings, errors, IDs, prompt excerpts and tool summaries survive.
    """
    from app.task import protected_task_ids
    from .llm_call_service import apply_agent_scope

    cutoff = _cutoff()
    db = get_db()
    prompt_excerpt = literal("") if preview else func.left(LLMCall.prompt, _ARCHIVED_PROMPT_LENGTH, type_=Text())
    summaries = literal([], JSONB) if preview else _tool_summaries()
    query = (
        select(LLMCall, first_output_timestamp(), prompt_excerpt, summaries)
        .options(load_only(LLMCall.id, LLMCall.usage, LLMCall.first_output_at,
                           LLMCall.deleted_at, LLMCall.updated_at, raiseload=True))
        .where(
            or_(LLMCall.inference_attempt_id.is_(None),
                _finished_attempt(None if hide else cutoff, require_closed_inference=hide)),
            LLMCall.status.in_(_CLOSED_CALL_STATUSES),
            LLMCall.completed_at.is_not(None),
            or_(
                LLMCall.conversation_round_id.is_(None),
                LLMCall.conversation_round_id.in_(_releases["conversation_round"]())
                if "conversation_round" in _releases else false(),
            ),
            or_(
                LLMCall.process_run_id.is_(None),
                LLMCall.process_run_id.in_(_releases["process_run"]())
                if "process_run" in _releases else false(),
            ),
            or_(LLMCall.task_id.is_(None), LLMCall.task_id.not_in(protected_task_ids())),
        )
    )
    if not hide:
        query = query.where(LLMCall.completed_at < cutoff, LLMCall.updated_at < cutoff, _has_details())
    if call_id is not None:
        query = query.where(LLMCall.id == call_id)
    rows = (await db.execute(apply_agent_scope(query, agent_ids)
        .order_by(LLMCall.completed_at, LLMCall.id)
        .limit(max(1, min(batch_size, 500)))
        .with_for_update(skip_locked=call_id is None))).all()
    if not preview:
        for call, first_output_at, archived_prompt, tool_summaries in rows:
            call.prompt = archived_prompt
            call.system_prompt = call.raw_response = ""
            call.response_text = call.reasoning = ""
            call.request_messages = []
            call.tool_calls = tool_summaries
            call.first_output_at = first_output_at
            call.usage = {**call.usage, "trace_retention": "expired"}
            if hide:
                call.soft_delete()
        await db.flush()
    return len(rows)
