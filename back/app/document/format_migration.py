"""Transfer the former format column before DbAdmin contracts the source."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


def needed(delta: SchemaTransitionSet) -> bool:
    return "documents.document_type" in delta.removed_columns


async def source_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='documents' AND column_name='document_type')""")))


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await source_exists(session):
        return True
    return not await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM documents
        WHERE document_format IS DISTINCT FROM CASE document_type
            WHEN 'html' THEN 'text' WHEN 'form' THEN 'text' WHEN 'dataset' THEN 'data'
            ELSE document_type END)"""))


async def transfer(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    if await source_exists(session):
        await session.execute(text("""UPDATE documents SET document_format=CASE document_type
            WHEN 'html' THEN 'text' WHEN 'form' THEN 'text' WHEN 'dataset' THEN 'data'
            ELSE document_type END
            WHERE document_format IS DISTINCT FROM CASE document_type
                WHEN 'html' THEN 'text' WHEN 'form' THEN 'text' WHEN 'dataset' THEN 'data'
                ELSE document_type END"""))


def register(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.document.format_column", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="document-format-from-original-column-v1", predicate=needed, handler=transfer,
        postcondition=complete, requires_schema=frozenset({"documents.document_format"})))
