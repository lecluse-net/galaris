"""DbAdmin conversion of agent editorial fields, preserving exact legacy sources."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import convert_legacy_to_html, RichTextError
from loguru import logger
from .models import Agent


def needs_conversion(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("agents", "profile_media_type")


async def complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    count = await session.scalar(
        select(func.count())
        .select_from(Agent)
        .where(Agent.profile_media_type != "text/html")
        .execution_options(include_historized=True)
    )
    return int(count or 0) == 0


async def convert_batch(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    rows = (
        await session.scalars(
            select(Agent)
            .where(Agent.profile_media_type != "text/html")
            .order_by(Agent.id)
            .limit(500)
            .with_for_update(skip_locked=True)
            .execution_options(include_historized=True)
        )
    ).all()
    for row in rows:
        try:
            converted = {
                key: (
                    convert_legacy_to_html(value, row.profile_media_type)[0]
                    if value is not None
                    else None
                )
                for key, value in {
                    "personality": row.personality,
                    "job_description": row.job_description,
                }.items()
            }
        except RichTextError as exc:
            logger.warning(
                "Agent HTML conversion requires review: agent={} reason={}", row.id, str(exc)
            )
            continue
        row.profile_legacy_source = {
            "personality": row.personality,
            "job_description": row.job_description,
        }
        row.personality = converted["personality"]
        row.job_description = converted["job_description"]
        row.profile_media_type = "text/html"
    await session.flush()


def register_html_conversion(registry: DbAdminRegistry) -> None:
    registry.register_action(
        DbAdminAction(
            key="app.agent.editorial_html",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="html-profile-1-preserve-source",
            predicate=needs_conversion,
            handler=convert_batch,
            postcondition=complete,
        )
    )
