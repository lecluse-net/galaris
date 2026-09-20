"""DbAdmin conversion of task editorial fields, preserving exact legacy sources."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import convert_legacy_to_html, RichTextError
from loguru import logger
from .models import Task


def needs_conversion(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("tasks", "objective_media_type")


async def complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    count = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.objective_media_type != "text/html")
        .execution_options(include_historized=True)
    )
    return int(count or 0) == 0


async def convert_batch(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    rows = (
        await session.scalars(
            select(Task)
            .where(Task.objective_media_type != "text/html")
            .order_by(Task.id)
            .limit(500)
            .with_for_update(skip_locked=True)
            .execution_options(include_historized=True)
        )
    ).all()
    for row in rows:
        try:
            converted = (
                convert_legacy_to_html(row.objective, row.objective_media_type)[0]
                if row.objective is not None
                else None
            )
        except RichTextError as exc:
            logger.warning(
                "Task HTML conversion requires review: task={} reason={}", row.id, str(exc)
            )
            continue
        row.objective_legacy_source = row.objective
        row.objective = converted
        row.objective_media_type = "text/html"
    await session.flush()


def register_html_conversion(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.task.editorial_html",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="html-profile-1-preserve-source",
            predicate=needs_conversion,
            handler=convert_batch,
            postcondition=complete,
        )
    )
