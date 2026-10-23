"""Immutable pre-expansion archive, outside Atlas' declarative public schema."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import SchemaTransitionSet


OBSOLETE_COLUMNS = frozenset({"document_type", "filename", "visibility", "global_access", "group_access"})
ARCHIVED_TABLES = (
    "memory_items", "memory_revisions", "memory_item_grants", "document_user_grants",
    "document_team_grants", "documents", "document_revisions", "memory_summary_revisions",
)


def needs_document_backup(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("documents") or any(
        f"memory_items.{column}" in delta.removed_columns for column in OBSOLETE_COLUMNS
    )


async def archive_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(text(
        "SELECT to_regclass('galaris_migration.memory_document_split_manifest') IS NOT NULL"
    )))


async def document_backup_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await archive_exists(session):
        return False
    return bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM galaris_migration.memory_document_split_manifest)
        AND NOT EXISTS (
            SELECT 1 FROM galaris_migration.memory_document_split_rows
            WHERE digest <> encode(sha256(convert_to(snapshot::text, 'UTF8')), 'hex')
        ) AND NOT EXISTS (
            SELECT 1 FROM (
                SELECT key AS table_name, value::bigint AS expected
                FROM galaris_migration.memory_document_split_manifest,
                     jsonb_each_text(row_counts)
            ) manifest FULL JOIN (
                SELECT table_name, count(*) AS actual
                FROM galaris_migration.memory_document_split_rows GROUP BY table_name
            ) counts USING (table_name)
            WHERE coalesce(expected, 0) <> coalesce(actual, 0) OR expected IS NULL
        )
    """)))


async def backup_documents(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '10s'"))
    # Separate phase transactions require durable tables, never TEMP tables.
    # The archive is retained indefinitely; synchronization never overwrites it.
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS galaris_migration.memory_document_split_rows (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), table_name text NOT NULL,
            row_key text NOT NULL, snapshot jsonb NOT NULL, digest text NOT NULL,
            UNIQUE (table_name, row_key)
        )
    """))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS galaris_migration.memory_document_split_manifest (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            archive_key text NOT NULL UNIQUE CHECK (archive_key = 'documents'),
            created_at timestamptz NOT NULL DEFAULT now(), row_counts jsonb NOT NULL,
            transferred boolean NOT NULL DEFAULT false
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_memory_document_split_resources
        ON galaris_migration.memory_document_split_rows
            ((snapshot->>'provider_code'), (snapshot->>'resource_id'))
        WHERE snapshot->>'resource_id' IS NOT NULL
    """))
    if await session.scalar(text("SELECT count(*) FROM galaris_migration.memory_document_split_manifest")):
        if not await document_backup_complete(session, delta):
            raise RuntimeError("Document migration archive is damaged; original archive preserved")
        return
    counts: dict[str, int] = {}
    for table in ARCHIVED_TABLES:
        if not await session.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": f"public.{table}"}):
            counts[table] = 0
            continue
        # Names come exclusively from the closed constant above. Lock all sources
        # before copying any of them to obtain a consistent multi-table snapshot.
        await session.execute(text(f"LOCK TABLE public.{table} IN SHARE MODE"))
    for table in ARCHIVED_TABLES:
        if table in counts:
            continue
        await session.execute(text(f"""
            INSERT INTO galaris_migration.memory_document_split_rows (table_name, row_key, snapshot, digest)
            SELECT :table, id::text, to_jsonb(source),
                encode(sha256(convert_to(to_jsonb(source)::text, 'UTF8')), 'hex')
            FROM public.{table} source
        """), {"table": table})
        counts[table] = int(await session.scalar(text(f"SELECT count(*) FROM public.{table}")) or 0)
    # Attachment bytes are addressed by manifest IDs rather than the Memory
    # description's resource pointer. Preserve both, including old revisions.
    await session.execute(text("""
        WITH archived_resource_refs AS (
            SELECT snapshot->>'provider_code' AS provider, snapshot->>'resource_id' AS resource
            FROM galaris_migration.memory_document_split_rows
            UNION
            SELECT 'native', attachment->>'id'
            FROM galaris_migration.memory_document_split_rows,
                LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(snapshot->'metadata'->'document_attachments') = 'array'
                        THEN snapshot->'metadata'->'document_attachments' ELSE '[]'::jsonb END ||
                    CASE WHEN jsonb_typeof(snapshot->'metadata'->'retained_document_attachments') = 'array'
                        THEN snapshot->'metadata'->'retained_document_attachments' ELSE '[]'::jsonb END
                ) attachment
        ), resources AS (
            SELECT provider || ':' || resource AS key,
                jsonb_build_object('provider_code', provider, 'resource_id', resource) AS snapshot
            FROM archived_resource_refs WHERE provider IS NOT NULL AND resource IS NOT NULL AND resource <> ''
        )
        INSERT INTO galaris_migration.memory_document_split_rows (table_name, row_key, snapshot, digest)
        SELECT 'resource_references', key, snapshot,
            encode(sha256(convert_to(snapshot::text, 'UTF8')), 'hex') FROM resources
    """))
    counts["resource_references"] = int(await session.scalar(text("""
        SELECT count(*) FROM galaris_migration.memory_document_split_rows WHERE table_name='resource_references'
    """)) or 0)
    from json import dumps
    await session.execute(text("""
        INSERT INTO galaris_migration.memory_document_split_manifest (archive_key, row_counts)
        VALUES ('documents', CAST(:counts AS jsonb))
    """), {"counts": dumps(counts)})
    if not await document_backup_complete(session, delta):
        raise RuntimeError("Document migration archive could not be verified")


async def verify_unchanged_sources(session: AsyncSession) -> None:
    """Reject writes between backup and transfer rather than silently losing them."""
    await session.execute(text("SET LOCAL lock_timeout = '10s'"))
    for table in ARCHIVED_TABLES:
        if not await session.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": f"public.{table}"}):
            continue
        await session.execute(text(f"LOCK TABLE public.{table} IN SHARE ROW EXCLUSIVE MODE"))
        changed = await session.scalar(text(f"""
            SELECT EXISTS (
                SELECT 1 FROM public.{table} source FULL JOIN (
                    SELECT row_key, snapshot FROM galaris_migration.memory_document_split_rows
                    WHERE table_name = :table
                ) archived ON archived.row_key = source.id::text
                WHERE source.id IS NULL OR archived.row_key IS NULL
                    OR NOT to_jsonb(source) @> archived.snapshot
            )
        """), {"table": table})
        # Expansion legitimately creates empty destination tables.
        if changed:
            raise RuntimeError(f"{table} changed after the migration backup; transfer stopped")


async def archived_resources(session: AsyncSession, provider: str, resources: list[str]) -> set[str]:
    """Keep archived bytes reachable even after explicit forget or orphan cleanup."""
    if not resources or not await archive_exists(session):
        return set()
    return set(await session.scalars(text("""
        SELECT snapshot->>'resource_id' FROM galaris_migration.memory_document_split_rows
        WHERE snapshot->>'provider_code' = :provider AND snapshot->>'resource_id' = ANY(:resources)
    """), {"provider": provider, "resources": resources}))
