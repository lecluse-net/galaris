"""Move the current description into Goal HTML; retain the tracking Document."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.storage import get_storage
from uuid import UUID


def needs_content(delta: SchemaTransitionSet) -> bool:
    return "goals.description_document_id" in delta.removed_columns


async def retirement_ready(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    nullable = await session.scalar(text("""SELECT is_nullable FROM information_schema.columns
        WHERE table_schema='public' AND table_name='goals' AND column_name='description_document_id'"""))
    return nullable is None or nullable == "YES"


async def prepare_retirement(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    if not await retirement_ready(session, delta):
        # Keep existing source references while allowing the new runtime to
        # create Goals when another nonfatal preparation defers contraction.
        await session.execute(text("ALTER TABLE public.goals ALTER COLUMN description_document_id DROP NOT NULL"))


async def content_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if await session.scalar(text("""SELECT EXISTS(
        SELECT 1 FROM goals WHERE description IS NULL
    )""")):
        return False
    # A completed transfer remains satisfied after Atlas removes the old FKs.
    if not await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM pg_attribute
        WHERE attrelid=to_regclass('goals') AND attname='description_document_id'
        AND NOT attisdropped)""")):
        return True
    if await session.scalar(text("""SELECT EXISTS(
        SELECT 1 FROM documents d JOIN goals g ON
          d.id = g.description_document_id
        WHERE d.deleted_at IS NULL
    )""")):
        return False
    # Copy and source retirement commit atomically. Subsequent legitimate edits
    # of a transferred Goal must not be compared to its retired Document forever.
    return True


async def description_source(session: AsyncSession, identity: UUID) -> str:
    source = (await session.execute(text("""SELECT content, provider_code,
        resource_id, media_type FROM documents WHERE id=:id FOR UPDATE"""),
        {"id": identity})).mappings().one_or_none()
    if source is None:
        raise ValueError("Cannot transfer Goal content: source Document is missing")
    if not str(source["media_type"]).startswith("text/"):
        raise ValueError("Cannot transfer Goal content: source is not text")
    if source["content"] is not None:
        return str(source["content"])
    return (await get_storage(source["provider_code"]).read(source["resource_id"])).decode("utf-8")


async def transfer_content(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    # Scalar SQL intentionally includes deleted Goals and Documents. Never lose a
    # recoverable Goal's current text. The source columns survive until contraction.
    if await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM goals d JOIN goals t
        ON d.description_document_id=t.tracking_document_id)""")):
        raise ValueError("Refusing to retire a description also used for tracking")
    rows = (await session.execute(text("""SELECT id, description_document_id,
        tracking_document_id, description FROM goals
        WHERE description_document_id IS NOT NULL ORDER BY id FOR UPDATE"""))).mappings()
    for goal in rows:
        content = await description_source(session, goal["description_document_id"])
        if goal["description"] is None:
            await session.execute(text("UPDATE goals SET description=:content WHERE id=:id"),
                                  {"id": goal["id"], "content": content})
        elif goal["description"] != content:
            raise ValueError("Cannot retire Goal Document: current contents differ")
        # Retire only the description resource after its current HTML was copied.
        # The tracking Document, its identity, content, history and ACL stay intact.
        await session.execute(text("""UPDATE documents SET deleted_at=coalesce(deleted_at,now())
            WHERE id = :description"""),
            {"description": goal["description_document_id"]})


def register_dbadmin(registry: DbAdminRegistry) -> None:
    from .agenda_upgrade import register_agenda_upgrade

    register_agenda_upgrade(registry)
    registry.register_action(DbAdminAction(
        key="app.goal.prepare_description_retirement", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="retained-description-reference-allows-new-goals-v1",
        predicate=needs_content, handler=prepare_retirement, postcondition=retirement_ready,
    ))
    registry.register_action(DbAdminAction(
        key="app.goal.current_content", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="current-description-html-with-staged-goal-writes-v2",
        compatible_checksums=frozenset({"current-description-html-into-goal-keep-tracking-document-v1"}),
        predicate=needs_content, handler=transfer_content, postcondition=content_complete,
    ))
