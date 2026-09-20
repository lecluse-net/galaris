"""Prune verbose traces while preserving accounting and active work."""

from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Collection
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, and_, case, delete, false, func, or_, select

from core.database import get_db
from core.params import runtime_settings
from .models import LLMCall, LLMCallEvent

TraceOwner = Literal["conversation_round", "process_run"]
_releases: dict[TraceOwner, Callable[[], Select[tuple[UUID]]]] = {}


def register_trace_release(
    owner: TraceOwner, released_ids: Callable[[], Select[tuple[UUID]]]
) -> None:
    """Register the owning domain's positive proof of causal completion."""
    _releases[owner] = released_ids


async def preview_trace_retention(*, agent_ids: Collection[int] | None = None) -> dict[str, int]:
    """Count protection reasons without returning prompts or modifying rows."""
    from app.task import protected_task_ids
    from .llm_call_service import apply_agent_scope

    days = runtime_settings.LLM_TRACE_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
        (LLMCall.inference_attempt_id.is_not(None), "inference"),
        (LLMCall.status.not_in(("completed", "error", "cancelled")), "active"),
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
        else_="eligible" if days else "disabled",
    )
    statement = select(reason, func.count()).where(
        or_(
            LLMCall.prompt != "",
            LLMCall.system_prompt != "",
            LLMCall.raw_response != "",
            LLMCall.response_text != "",
            LLMCall.reasoning != "",
            LLMCall.request_messages != [],
            LLMCall.tool_calls != [],
            select(LLMCallEvent.id).where(LLMCallEvent.call_id == LLMCall.id).exists(),
        )
    )
    statement = apply_agent_scope(statement, agent_ids)
    rows = await get_db().execute(statement.group_by(reason))
    return {str(reason): int(count) for reason, count in rows}


async def prune_traces(*, preview: bool = False, batch_size: int = 100) -> int:
    """Clear completed, old diagnostic payloads in bounded locked batches.

    Calls tied to unregistered or unfinished consumers are retained. Task calls
    are retained while their causal component has active work. Unrelated active
    tasks do not retain every trace. Usage, costs, errors and IDs always survive.
    """
    days = runtime_settings.LLM_TRACE_RETENTION_DAYS
    if days == 0:
        return 0
    from app.task import protected_task_ids

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = get_db()
    rows = list(
        (
            await db.scalars(
                select(LLMCall)
                .where(
                    # Durable inference replay owns this journal independently of
                    # the diagnostic trace retention policy.
                    LLMCall.inference_attempt_id.is_(None),
                    LLMCall.status.in_(("completed", "error", "cancelled")),
                    LLMCall.completed_at < cutoff,
                    LLMCall.updated_at < cutoff,
                    or_(
                        LLMCall.conversation_round_id.is_(None),
                        LLMCall.conversation_round_id.in_(_releases["conversation_round"]())
                        if "conversation_round" in _releases
                        else false(),
                    ),
                    or_(
                        LLMCall.process_run_id.is_(None),
                        LLMCall.process_run_id.in_(_releases["process_run"]())
                        if "process_run" in _releases
                        else false(),
                    ),
                    or_(LLMCall.task_id.is_(None), LLMCall.task_id.not_in(protected_task_ids())),
                    or_(
                        LLMCall.prompt != "",
                        LLMCall.system_prompt != "",
                        LLMCall.raw_response != "",
                        LLMCall.response_text != "",
                        LLMCall.reasoning != "",
                        LLMCall.request_messages != [],
                        LLMCall.tool_calls != [],
                        select(LLMCallEvent.id).where(LLMCallEvent.call_id == LLMCall.id).exists(),
                    ),
                )
                .order_by(LLMCall.completed_at, LLMCall.id)
                .limit(max(1, min(batch_size, 500)))
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not preview:
        if rows:
            await db.execute(
                delete(LLMCallEvent).where(LLMCallEvent.call_id.in_([call.id for call in rows]))
            )
        for call in rows:
            call.prompt = call.system_prompt = call.raw_response = ""
            call.response_text = call.reasoning = ""
            call.request_messages = []
            call.tool_calls = []
            call.usage = {**call.usage, "trace_retention": "expired"}
        await db.flush()
    return len(rows)
