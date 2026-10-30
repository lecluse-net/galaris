"""Verified, additive transfer from native text files into their owning SQL rows.

The immutable backup lives outside Atlas' public schema. Source files are never
removed. Run through DbAdmin with application writers stopped during the switch.
"""

from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import complete_io

from core.storage import NativeFileStorage
from .contracts import ResourceNotFoundError


TABLES = ("memory_items", "documents", "memory_revisions", "document_revisions", "memory_summary_revisions")
ARCHIVE = "galaris_migration.memory_text_contents"


def _exclude_live_contacts(table: str, alias: str) -> str:
    if table not in {"memory_items", "memory_revisions"}:
        return ""
    key = "id" if table == "memory_items" else "item_id"
    return (
        " AND NOT EXISTS (SELECT 1 FROM memory_items contact "
        f"WHERE contact.id = {alias}.{key} AND contact.source_managed "
        "AND contact.managed_source_kind = 'messenger_contact')"
    )


def needs_inline_content(delta: SchemaTransitionSet) -> bool:
    return any(delta.table_added(table) or delta.column_added(table, "content") for table in TABLES)


def _native_text(table: str) -> str:
    text_type = "" if table.endswith("_summary_revisions") else " AND content_type IN ('text', 'json')"
    return ("provider_code = 'native' AND resource_id NOT IN ('forgotten', 'merged')"
            + text_type + _exclude_live_contacts(table, table))


async def _read_source(resource_ref: str, root: Path) -> bytes:
    if not resource_ref:
        return b""
    try:
        if str(UUID(resource_ref)) != resource_ref:
            raise ValueError()
        path = await NativeFileStorage(root).path_for_read(resource_ref)
        return await complete_io(path.read_bytes)
    except (OSError, ValueError, ResourceNotFoundError):
        raise ValueError("Referenced native text is unavailable; migration sources were preserved") from None


async def inline_content_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await session.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": ARCHIVE}):
        return False
    for table in TABLES:
        if table == "memory_summary_revisions" and not await session.scalar(text("SELECT to_regclass('public.memory_summary_revisions') IS NOT NULL")):
            continue
        if await session.scalar(text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {_native_text(table)} AND content IS NULL)")):
            return False
        damaged = await session.scalar(text(f"""
            SELECT EXISTS (
                SELECT 1 FROM {ARCHIVE} backup
                LEFT JOIN {table} target ON target.id = backup.row_key
                WHERE backup.table_name = :table AND (
                    backup.sha256 <> encode(sha256(convert_to(backup.content, 'UTF8')), 'hex')
                    OR backup.size_bytes <> octet_length(backup.content)
                    OR (target.id IS NOT NULL AND target.resource_id = backup.resource_ref
                        {_exclude_live_contacts(table, 'target')} AND (
                        target.content IS NULL
                        OR convert_to(target.content, 'UTF8') <> convert_to(backup.content, 'UTF8')
                    ))
                )
            )
        """), {"table": table})
        if damaged:
            return False
    return True


async def migrate_inline_content(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {ARCHIVE} (
            table_name text NOT NULL, row_key uuid NOT NULL, resource_ref text NOT NULL,
            content text NOT NULL, sha256 text NOT NULL, size_bytes bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (table_name, row_key)
        )
    """))
    root = Path(settings.GALARIS_MEMORY_ROOT)
    for table in TABLES:
        if table == "memory_summary_revisions" and not await session.scalar(text("SELECT to_regclass('public.memory_summary_revisions') IS NOT NULL")):
            continue
        # A fixed order and row locks prevent a metadata write from racing the
        # transfer. Upgrade orchestration must also stop old application writers.
        while True:
            rows = (await session.execute(text(f"""
                SELECT id, resource_id, content_hash FROM {table}
                WHERE {_native_text(table)} AND content IS NULL ORDER BY id LIMIT 100 FOR UPDATE
            """))).all()
            if not rows:
                break
            for row in rows:
                payload = await _read_source(str(row.resource_id), root)
                digest = sha256(payload).hexdigest()
                if row.content_hash and str(row.content_hash) != digest:
                    raise ValueError("Native text checksum mismatch; migration sources were preserved")
                try:
                    content = payload.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError("Native text is not UTF-8; migration sources were preserved") from None
                if "\x00" in content:
                    raise ValueError("Native text contains NUL; migration sources were preserved")
                parameters = {"table": table, "key": row.id, "ref": row.resource_id,
                              "content": content, "digest": digest, "size": len(payload)}
                await session.execute(text(f"""
                    INSERT INTO {ARCHIVE} (table_name, row_key, resource_ref, content, sha256, size_bytes)
                    VALUES (:table, :key, :ref, :content, :digest, :size)
                    ON CONFLICT (table_name, row_key) DO NOTHING
                """), parameters)
                matches = await session.scalar(text(f"""
                    SELECT resource_ref = :ref AND sha256 = :digest AND size_bytes = :size
                        AND convert_to(content, 'UTF8') = convert_to(CAST(:content AS text), 'UTF8')
                    FROM {ARCHIVE} WHERE table_name = :table AND row_key = :key
                """), parameters)
                if not matches:
                    raise ValueError("Native text differs from its migration backup; sources were preserved")
                await session.execute(text(f"UPDATE {table} SET content = :content WHERE id = :key"), parameters)
    if not await inline_content_complete(session, _delta):
        raise ValueError("Native text migration verification failed; sources were preserved")


def register_inline_content(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.memory.inline_text_contents", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="row-owned-text-with-immutable-backup-v1", predicate=needs_inline_content,
        handler=migrate_inline_content, postcondition=inline_content_complete,
    ))
