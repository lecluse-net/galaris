"""Preserve the current summary before retiring its intentionally obsolete history."""

from collections.abc import Collection

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

_ARCHIVE = "galaris_migration.document_summary_history_sources"


async def archive_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": _ARCHIVE}))


async def preserved_resources(session: AsyncSession, provider: str, pointers: Collection[str]) -> set[str]:
    """Retired summary pointers still retain their original stored bytes."""
    if not pointers or not await archive_exists(session):
        return set()
    return set(await session.scalars(text(f"SELECT snapshot->>'resource_id' FROM {_ARCHIVE} WHERE snapshot->>'provider_code'=:provider AND snapshot->>'resource_id'=ANY(CAST(:pointers AS text[]))"),
        {"provider": provider, "pointers": list(pointers)}))


def needed(delta: SchemaTransitionSet) -> bool:
    return "document_summary_revisions" in delta.removed_tables


async def preserve_current(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    if not await session.scalar(text("SELECT to_regclass('public.document_summary_revisions') IS NOT NULL")):
        return
    await session.execute(text("LOCK TABLE document_summary_revisions IN SHARE MODE"))
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_ARCHIVE} (identity uuid PRIMARY KEY, snapshot jsonb NOT NULL, digest text NOT NULL)"))
    await session.execute(text(f"INSERT INTO {_ARCHIVE} SELECT id,to_jsonb(r),encode(sha256(convert_to(to_jsonb(r)::text,'UTF8')),'hex') FROM document_summary_revisions r ON CONFLICT DO NOTHING"))
    if not await _archive_complete(session):
        raise RuntimeError("Historical summary source changed or its archive is damaged; retirement refused")
    await session.execute(text("""UPDATE documents d SET summary_content = r.content
        FROM document_summary_revisions r
        WHERE d.summary_provider_code='native' AND d.summary_content IS NULL
          AND r.provider_code='native' AND r.resource_id=d.summary_resource_id
          AND r.content IS NOT NULL"""))


async def _archive_complete(session: AsyncSession) -> bool:
    if not await archive_exists(session):
        return False
    return not bool(await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE}
        WHERE digest<>encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')) OR EXISTS(
        SELECT 1 FROM document_summary_revisions r LEFT JOIN {_ARCHIVE} a ON a.identity=r.id
        WHERE a.identity IS NULL OR a.snapshot IS DISTINCT FROM to_jsonb(r))""")))


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await session.scalar(text("SELECT to_regclass('public.document_summary_revisions') IS NOT NULL")):
        return True
    if not await _archive_complete(session):
        return False
    return not bool(await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM documents d
        JOIN document_summary_revisions r ON r.resource_id=d.summary_resource_id
        WHERE d.summary_provider_code='native' AND d.summary_content IS NULL
          AND r.provider_code='native' AND r.content IS NOT NULL)""")))


def register(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.document.retire_summary_history",
        phase=DbAdminPhase.BEFORE_EXPAND, checksum="preserve-current-summary-before-retiring-history",
        predicate=needed, handler=preserve_current, postcondition=complete))
