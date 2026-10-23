"""Retain the existing document capabilities of non-administrator roles."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

from .independence import needs_independence

_TABLE = "galaris_migration.document_role_capabilities"


async def preserved(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": _TABLE}))


async def preserve(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text(f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
        role_id integer NOT NULL, code text NOT NULL, PRIMARY KEY(role_id,code))"""))
    if not await session.scalar(text("SELECT to_regclass('public.role_privileges') IS NOT NULL")):
        return
    await session.execute(text(f"""INSERT INTO {_TABLE}(role_id,code)
        SELECT rp.role_id,replace(p.code,'MEMORY_','DOCUMENT_')
        FROM role_privileges rp JOIN privileges p ON p.id=rp.privilege_id
        WHERE p.code IN ('MEMORY_ACCESS','MEMORY_EDIT','MEMORY_ADMIN','MEMORY_ASSIGN_ALL_USERS')
        ON CONFLICT DO NOTHING"""))


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await preserved(session, _delta):
        return False
    return not bool(await session.scalar(text(f"""SELECT EXISTS (
        SELECT 1 FROM {_TABLE} old JOIN roles r ON r.id=old.role_id
        LEFT JOIN privileges p ON p.code=old.code
        LEFT JOIN role_privileges rp ON rp.role_id=old.role_id AND rp.privilege_id=p.id
        WHERE rp.role_id IS NULL)""")))


async def restore(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await session.execute(text(f"""INSERT INTO role_privileges(role_id,privilege_id)
        SELECT old.role_id,p.id FROM {_TABLE} old JOIN roles r ON r.id=old.role_id
        JOIN privileges p ON p.code=old.code ON CONFLICT DO NOTHING"""))


def register_privilege_migration(registry: DbAdminRegistry) -> None:
    for name, phase, handler, postcondition in (
        ("preserve", DbAdminPhase.BEFORE_EXPAND, preserve, preserved),
        ("restore", DbAdminPhase.AFTER_DATASET, restore, complete),
    ):
        registry.register_action(DbAdminAction(
            key=f"app.document.role_capabilities_{name}", phase=phase,
            checksum="preserve-equivalent-document-role-capabilities-v1",
            predicate=needs_independence, handler=handler, postcondition=postcondition,
        ))
