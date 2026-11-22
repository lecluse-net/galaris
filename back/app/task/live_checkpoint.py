"""Cumulative, bounded UI checkpoints, independent from effect/retry checkpoints."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.agent import AgentLiveEvent, AIResult
from core.database import get_db_session
from .activity_snapshot import LiveActivity
from .models import TaskAttempt
from .trace_projection import project_tool_payload

_cache: dict[tuple[UUID, UUID, UUID | None], tuple[LiveActivity, float]] = {}
_MAX_MESSAGES = 40
_MAX_CHARS = 4_000


def mark_live_snapshot_published(event: AgentLiveEvent) -> None:
    """Pace the next snapshot from the end of its WebSocket authorization and delivery."""
    key = (event.task_id, event.run_id, event.attempt_id)
    cached = _cache.get(key)
    if cached is not None and cached[0].sequence == event.sequence:
        _cache[key] = (cached[0], time.monotonic())


async def checkpoint_live_event(event: AgentLiveEvent) -> LiveActivity | None:
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
        previous = LiveActivity.model_validate(raw) if raw else None
    else:
        previous = cached[0]
    if previous and event.sequence <= previous.sequence:
        return None
    result = previous.result.model_copy(deep=True) if previous else AIResult(prompt="")
    if event.result is not None:
        result = AIResult.model_validate(event.result.model_dump())
    elif event.message is not None:
        message = event.message.model_copy(deep=True)
        result.add_message(message)
    result.prompt = ""
    result.system_prompt = ""
    result.metadata = {}
    result.result = result.result[-_MAX_CHARS:]
    result.messages = result.messages[-_MAX_MESSAGES:]
    for message in result.messages:
        message.content = message.content[-_MAX_CHARS:]
        message.tool_arguments = project_tool_payload(message.tool_arguments)
        message.tool_result = project_tool_payload(message.tool_result)
    snapshot = LiveActivity(run_id=event.run_id, attempt_id=event.attempt_id, sequence=event.sequence, result=result,
                            last_activity_at=datetime.now(timezone.utc))
    terminal = event.kind in {"result", "failed", "cancelled"}
    now = time.monotonic()
    tool_event = event.message is not None and event.message.type == "tool" and event.message.tool_name != "thinking"
    completed_block = event.message is not None and event.message.stream_complete is True
    persist = terminal or tool_event or completed_block or cached is None or now - cached[1] >= 1.0
    if persist:
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
        if recorded is not None and event.kind == "message":
            from . import scheduler

            scheduler.notify_task_activity(event.task_id)
    if terminal:
        _cache.pop(key, None)
    else:
        if key not in _cache and len(_cache) >= 128:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (snapshot, now if persist else cached[1] if cached else now)
    return snapshot if persist else None
