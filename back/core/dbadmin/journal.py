"""Persistence and display of bounded DbAdmin run summaries."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from core import settings
from core.database import get_db_session

from .contracts import DbAdminResult
from .models import DbAdminIssueRecord, DbAdminRun


def _summary(result: DbAdminResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict.value,
        "issues": len(result.issues),
        "fatal_issues": sum(1 for issue in result.issues if issue.fatal),
        "actions": len(result.action_results),
        "required_columns_remaining": [
            item.key for item in result.transitions.required_columns
        ],
    }


async def persist_result(result: DbAdminResult) -> None:
    """Persist a result after the journal schema exists."""

    run_uuid = UUID(result.run_id)
    async with get_db_session() as session:
        session.add(
            DbAdminRun(
                id=run_uuid,
                mode=result.mode.value,
                verdict=result.verdict.value,
                scope_fingerprint=result.scope_fingerprint,
                target_fingerprint=result.target_fingerprint,
                started_at=result.started_at,
                finished_at=result.finished_at,
                summary=_summary(result),
            )
        )
        # These mappers have no ORM relationship: persist the parent before
        # adding its issue records so their foreign key always resolves.
        await session.flush()
        session.add_all(
            DbAdminIssueRecord(
                run_id=run_uuid,
                phase=issue.phase,
                object_name=issue.object_name,
                fatal=issue.fatal,
                message=issue.message[-4_000:],
            )
            for issue in result.issues[:100]
        )


async def latest_summary() -> dict[str, Any] | None:
    """Return the latest persisted operator summary."""

    async with get_db_session() as session:
        run = await session.scalar(
            select(DbAdminRun).order_by(DbAdminRun.started_at.desc()).limit(1)
        )
        if run is None:
            return None
        return {
            "run_id": str(run.id),
            "mode": run.mode,
            "verdict": run.verdict,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "summary": run.summary,
        }


async def persist_result_best_effort(result: DbAdminResult) -> None:
    try:
        await persist_result(result)
    except Exception as exc:
        message = str(exc).replace("\x00", "")
        if settings.POSTGRES_PASSWORD:
            message = message.replace(settings.POSTGRES_PASSWORD, "***")
        logger.error(
            "DbAdmin could not persist its final diagnostic: {}",
            message[-4_000:],
        )
