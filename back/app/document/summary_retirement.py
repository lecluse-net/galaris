"""Preserve the current summary before retiring its intentionally obsolete history."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


def needed(delta: SchemaTransitionSet) -> bool:
    return "document_summary_revisions" in delta.removed_tables


async def preserve_current(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    if not await session.scalar(text("SELECT to_regclass('public.document_summary_revisions') IS NOT NULL")):
        return
    await session.execute(text("""UPDATE documents d SET summary_content = r.content
        FROM document_summary_revisions r
        WHERE d.summary_provider_code='native' AND d.summary_content IS NULL
          AND r.provider_code='native' AND r.resource_id=d.summary_resource_id
          AND r.content IS NOT NULL"""))


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await session.scalar(text("SELECT to_regclass('public.document_summary_revisions') IS NOT NULL")):
        return True
    return not bool(await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM documents d
        JOIN document_summary_revisions r ON r.resource_id=d.summary_resource_id
        WHERE d.summary_provider_code='native' AND d.summary_content IS NULL
          AND r.provider_code='native' AND r.content IS NOT NULL)""")))


def register(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.document.retire_summary_history",
        phase=DbAdminPhase.BEFORE_EXPAND, checksum="preserve-current-summary-before-retiring-history",
        predicate=needed, handler=preserve_current, postcondition=complete))
