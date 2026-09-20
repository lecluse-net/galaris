"""Backlog of terminal results whose notification remains unproved."""

from datetime import datetime, timezone
import logfire
from sqlalchemy import func, select
from app.process import ProcessRun
from app.task import Task, TaskStatus
from core.database import get_db
from .models import ConversationProcessLink, ConversationTaskLink

_age = logfire.metric_gauge("conversation_oldest_notification_seconds", unit="s")
_uncertain = logfire.metric_gauge("conversation_unknown_notifications")


async def record_progress_metrics() -> None:
    now = datetime.now(timezone.utc)
    for kind, statement in (
        (
            "task",
            select(
                func.min(Task.updated_at),
                func.count(ConversationTaskLink.id).filter(
                    ConversationTaskLink.notification_state == "UNKNOWN"
                ),
            )
            .join(ConversationTaskLink, ConversationTaskLink.task_id == Task.id)
            .where(
                Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                ConversationTaskLink.notification_state.not_in(("DELIVERED", "SKIPPED")),
            ),
        ),
        (
            "process",
            select(
                func.min(ProcessRun.finished_at),
                func.count(ConversationProcessLink.id).filter(
                    ConversationProcessLink.notification_state == "UNKNOWN"
                ),
            )
            .join(ConversationProcessLink, ConversationProcessLink.process_run_id == ProcessRun.id)
            .where(
                ProcessRun.status.in_(("success", "error", "cancelled")),
                ConversationProcessLink.notification_state.not_in(("DELIVERED", "SKIPPED")),
            ),
        ),
    ):
        oldest, unknown = (await get_db().execute(statement)).one()
        _age.set(max(0, (now - oldest).total_seconds()) if oldest else 0, {"kind": kind})
        _uncertain.set(int(unknown or 0), {"kind": kind})
