"""DbAdmin preparation of file attributes, URL integrity and usage foreign keys."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


def needs_reference_preparation(transitions: SchemaTransitionSet) -> bool:
    return any(change.target_definition is not None and (
        (change.table_name == "memory_urls" and change.object_name == "uq_memory_urls_node_url")
        or (change.table_name == "memory_items" and change.object_name == "fk_memory_items_primary_url")
        or (change.table_name == "memory_usages" and change.kind == "foreign_key")
    ) for change in transitions.definitions)


async def _urls_exist(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass('public.memory_urls') IS NOT NULL")))


async def prepare_references(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    if await session.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='galaris_migration' AND table_name='memory_usage_orphan_tasks' AND column_name='usage_id')")):
        await session.execute(text("ALTER TABLE galaris_migration.memory_usage_orphan_tasks RENAME COLUMN usage_id TO id"))
    # Keep historical task references for audit before making the live FK nullable.
    if await session.scalar(text("SELECT EXISTS (SELECT 1 FROM memory_usages usage WHERE usage.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks WHERE id=usage.task_id))")):
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
        await session.execute(text("CREATE TABLE IF NOT EXISTS galaris_migration.memory_usage_orphan_tasks (id uuid PRIMARY KEY, task_ref uuid NOT NULL)"))
        await session.execute(text("INSERT INTO galaris_migration.memory_usage_orphan_tasks SELECT usage.id, usage.task_id FROM memory_usages usage WHERE usage.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks WHERE id=usage.task_id) ON CONFLICT DO NOTHING"))
        await session.execute(text("UPDATE memory_usages usage SET task_id=NULL WHERE task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks WHERE id=usage.task_id)"))
    if not await _urls_exist(session):
        return
    await session.execute(text("UPDATE memory_items SET primary_url=NULL WHERE length(btrim(primary_url))=0"))
    await session.execute(text("UPDATE file_catalog_entries SET memory_url_id=NULL WHERE memory_url_id IN (SELECT id FROM memory_urls WHERE length(btrim(url))=0)"))
    await session.execute(text("DELETE FROM memory_urls WHERE length(btrim(url))=0"))
    await session.execute(text("""
        WITH locations AS (SELECT id, first_value(id) OVER (
            PARTITION BY memory_node_id, url ORDER BY id) canonical FROM memory_urls)
        UPDATE file_catalog_entries entry SET memory_url_id=locations.canonical
        FROM locations WHERE entry.memory_url_id=locations.id AND locations.id<>locations.canonical
    """))
    await session.execute(text("""
        DELETE FROM memory_urls duplicate USING memory_urls canonical
        WHERE duplicate.memory_node_id=canonical.memory_node_id AND duplicate.url=canonical.url
          AND duplicate.id>canonical.id
    """))
    await session.execute(text("""
        INSERT INTO memory_urls (id, memory_node_id, url)
        SELECT gen_random_uuid(), node.id, node.primary_url FROM memory_items node
        WHERE node.primary_url IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM memory_urls WHERE memory_node_id=node.id AND url=node.primary_url)
    """))


async def references_prepared(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    if await session.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='galaris_migration' AND table_name='memory_usage_orphan_tasks' AND column_name='usage_id')")):
        return False
    if await session.scalar(text("SELECT EXISTS (SELECT 1 FROM memory_usages usage WHERE usage.task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks WHERE id=usage.task_id))")):
        return False
    if not await _urls_exist(session):
        return True
    return not bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM memory_urls GROUP BY memory_node_id, url HAVING count(*)>1)
        OR EXISTS (SELECT 1 FROM memory_urls WHERE length(btrim(url))=0)
        OR EXISTS (SELECT 1 FROM memory_items node WHERE primary_url IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM memory_urls WHERE memory_node_id=node.id AND url=node.primary_url))
    """)))


def needs_file_attributes(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("memory_items", "file_media_type") or transitions.column_added("memory_items", "file_size_bytes")


async def backfill_file_attributes(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    await session.execute(text("""
        UPDATE memory_items SET
            file_media_type=coalesce(file_media_type, metadata->>'resource_media_type'),
            file_size_bytes=coalesce(file_size_bytes, CASE
                WHEN jsonb_typeof(metadata->'resource_size_bytes')='number'
                 AND (metadata->>'resource_size_bytes') ~ '^[0-9]{1,18}$'
                THEN (metadata->>'resource_size_bytes')::bigint END),
            metadata=metadata-'resource_media_type'-'resource_size_bytes'
        WHERE metadata ?| ARRAY['resource_media_type', 'resource_size_bytes']
    """))
    await session.execute(text("""
        UPDATE memory_items node SET
            file_media_type=coalesce(node.file_media_type, entry.descriptor->>'media_type'),
            file_size_bytes=coalesce(node.file_size_bytes, CASE
                WHEN jsonb_typeof(entry.descriptor->'size')='number'
                 AND (entry.descriptor->>'size') ~ '^[0-9]{1,18}$'
                THEN (entry.descriptor->>'size')::bigint END)
        FROM memory_urls location, file_catalog_entries entry
        WHERE node.id=location.memory_node_id AND entry.memory_url_id=location.id
          AND node.node_kind='file'
    """))


async def attributes_backfilled(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return not bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM memory_items WHERE metadata ?| ARRAY['resource_media_type', 'resource_size_bytes'])
        OR EXISTS (SELECT 1 FROM memory_items node JOIN memory_urls location ON location.memory_node_id=node.id
            JOIN file_catalog_entries entry ON entry.memory_url_id=location.id WHERE node.node_kind='file'
            AND ((node.file_media_type IS NULL AND entry.descriptor->>'media_type' IS NOT NULL)
              OR (node.file_size_bytes IS NULL AND jsonb_typeof(entry.descriptor->'size')='number'
                  AND (entry.descriptor->>'size') ~ '^[0-9]{1,18}$')))
    """)))


def register_file_attributes(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.memory.reference_integrity", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="preserve-urls-and-orphan-task-audit-v2", predicate=needs_reference_preparation,
        compatible_checksums=frozenset({"preserve-urls-and-orphan-task-audit-v1"}),
        handler=prepare_references, postcondition=references_prepared,
    ))
    registry.register_action(DbAdminAction(
        key="app.memory.file_attributes", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="dedicated-original-file-attributes-v1", predicate=needs_file_attributes,
        handler=backfill_file_attributes, postcondition=attributes_backfilled,
    ))
