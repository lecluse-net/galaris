"""Cumulative, bounded UI checkpoints, independent from effect/retry checkpoints."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.agent import AgentLiveEvent, AIResult
from core.database import get_db_session
from .activity_snapshot import LiveActivity
from .models import TaskAttempt
from .trace_projection import project_tool_payload


@dataclass
class _Progress:
    result: AIResult
    sequence: int
    last_tick: float
    observed: bool


_cache: dict[tuple[UUID, UUID, UUID | None], _Progress] = {}
_MAX_MESSAGES = 40
_MAX_CHARS = 4_000


def _bound_snapshot(result: AIResult) -> None:
    result.prompt = ""
    result.system_prompt = ""
    result.metadata = {}
    result.messages = result.messages[-_MAX_MESSAGES:]
    for message in result.messages:
        message.tool_arguments = project_tool_payload(message.tool_arguments)
        message.tool_result = project_tool_payload(message.tool_result)
        message.content = message.content[-_MAX_CHARS:]


async def checkpoint_live_event(
    event: AgentLiveEvent, *, track_fragments: bool = True,
) -> LiveActivity | None:
    key = (event.task_id, event.run_id, event.attempt_id)
    attempt_filter = (TaskAttempt.id == event.attempt_id,) if event.attempt_id else ()
    cached = _cache.get(key)
    if cached is None:
        async with get_db_session() as db:
            raw = await db.scalar(select(TaskAttempt.data["live_activity"]).where(
                TaskAttempt.task_id == event.task_id,
                *attempt_filter,
                TaskAttempt.data["agent_run"]["request_run_id"].as_string() == str(event.run_id),
            ).order_by(TaskAttempt.attempt_number.desc()).limit(1))
        if raw:
            previous = LiveActivity.model_validate(raw)
            if event.sequence <= previous.sequence:
                return None
            result = previous.result
            _bound_snapshot(result)
        else:
            result = AIResult(prompt="")
    elif event.sequence <= cached.sequence:
        return None
    else:
        result = cached.result
    if event.result is not None:
        result = AIResult.model_validate(event.result.model_dump())
        _bound_snapshot(result)
    elif event.message is not None:
        message = event.message.model_copy(deep=event.message.usage is not None)
        message.tool_arguments = project_tool_payload(message.tool_arguments)
        message.tool_result = project_tool_payload(message.tool_result)
        changed = result.add_message(message)
        if changed is not None:
            changed.content = changed.content[-_MAX_CHARS:]
        if len(result.messages) > _MAX_MESSAGES:
            del result.messages[:-_MAX_MESSAGES]
    result.result = result.result[-_MAX_CHARS:]
    terminal = event.kind in {"result", "failed", "cancelled"}
    now = time.monotonic()
    tool_event = event.message is not None and event.message.type == "tool" and event.message.tool_name != "thinking"
    completed_block = event.message is not None and event.message.stream_complete is True
    periodic = cached is not None and now - cached.last_tick >= 1.0
    persist = (terminal or tool_event or completed_block or cached is None
               or track_fragments and (periodic or not cached.observed))
    snapshot = None
    activity = False
    if persist:
        snapshot = LiveActivity(run_id=event.run_id, attempt_id=event.attempt_id, sequence=event.sequence, result=result,
                                last_activity_at=datetime.now(timezone.utc))
        async with get_db_session() as db:
            recorded = await db.scalar(update(TaskAttempt).where(
                TaskAttempt.task_id == event.task_id,
                *attempt_filter,
                TaskAttempt.data["agent_run"]["request_run_id"].as_string() == str(event.run_id),
                TaskAttempt.status == "CLAIMED",
            ).values(data=func.jsonb_set(
                func.coalesce(TaskAttempt.data, cast({}, JSONB)),
                cast(["live_activity"], ARRAY(Text)), cast(snapshot.model_dump(mode="json"), JSONB),
            )).returning(TaskAttempt.id).execution_options(synchronize_session=False))
        activity = recorded is not None
    elif periodic:
        # The scheduler needs evidence of progress even when no UI is watching.
        # Keep this advisory heartbeat local; real checkpoints still check the lease.
        activity = True

    if activity and event.kind == "message":
        from . import scheduler

        scheduler.notify_task_activity(event.task_id)
    if terminal:
        _cache.pop(key, None)
    else:
        if key not in _cache and len(_cache) >= 128:
            _cache.pop(next(iter(_cache)))
        _cache[key] = _Progress(result, event.sequence, now if persist or periodic or cached is None else cached.last_tick,
                                track_fragments)
    return snapshot
