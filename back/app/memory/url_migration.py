"""Preserve legacy URL associations before DbAdmin contracts their columns."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


def needs_url_backfill(transitions: SchemaTransitionSet) -> bool:
    return "memory_urls" in transitions.added_tables or "file_catalog_entries.memory_item_id" in transitions.removed_columns


async def _legacy_catalogue(session: AsyncSession) -> bool:
    return bool(await session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='file_catalog_entries' AND column_name='memory_item_id')"
    )))


async def backfill_memory_urls(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    if await _legacy_catalogue(session):
        await session.execute(text("""
            INSERT INTO memory_urls (id, memory_node_id, url)
            SELECT gen_random_uuid(), candidate.memory_item_id, candidate.uri
            FROM (SELECT DISTINCT memory_item_id, uri FROM file_catalog_entries
                  WHERE memory_item_id IS NOT NULL AND present) candidate
            WHERE NOT EXISTS (SELECT 1 FROM memory_urls location
                WHERE location.memory_node_id=candidate.memory_item_id AND location.url=candidate.uri)
        """))
        await session.execute(text("""
            UPDATE file_catalog_entries entry SET memory_url_id=location.id
            FROM memory_urls location
            WHERE entry.present AND entry.memory_item_id=location.memory_node_id
              AND entry.uri=location.url AND entry.memory_url_id IS NULL
        """))
    # The catalogue's live observations supersede historical resource provenance.
    # Other nodes retain every URL previously supplied in metadata or provenance.
    await session.execute(text("""
        INSERT INTO memory_urls (id, memory_node_id, url)
        SELECT gen_random_uuid(), candidate.node_id, candidate.url
        FROM (
            SELECT DISTINCT node.id node_id, evidence.url
            FROM memory_items node CROSS JOIN LATERAL (
                SELECT node.metadata->>'resource_uri' url
                WHERE jsonb_typeof(node.metadata->'resource_uri')='string'
                UNION
                SELECT jsonb_array_elements_text(CASE
                    WHEN jsonb_typeof(node.metadata->'resource_uris')='array'
                    THEN node.metadata->'resource_uris' ELSE '[]'::jsonb END)
                UNION
                SELECT source_ref FROM memory_sources
                WHERE item_id=node.id AND source_kind IN ('resource', 'attachment')
                  AND strpos(source_ref, '://')>0
            ) evidence
            WHERE node.managed_source_kind IS DISTINCT FROM 'file_catalogue'
              AND evidence.url IS NOT NULL AND evidence.url<>''
        ) candidate
        WHERE NOT EXISTS (SELECT 1 FROM memory_urls location
            WHERE location.memory_node_id=candidate.node_id AND location.url=candidate.url)
    """))
    await session.execute(text("""
        DELETE FROM memory_sources WHERE source_kind IN ('resource', 'attachment')
          AND strpos(source_ref, '://')>0
    """))
    for table in ("memory_items", "memory_revisions", "memory_sources"):
        if table == "memory_items":
            await session.execute(text("""
                UPDATE memory_items node SET primary_url=coalesce(
                    (SELECT location.url FROM memory_urls location
                     WHERE location.memory_node_id=node.id AND location.url=node.metadata->>'resource_uri' LIMIT 1),
                    (SELECT location.url FROM memory_urls location
                     WHERE location.memory_node_id=node.id ORDER BY location.url LIMIT 1))
                WHERE node.primary_url IS NULL
            """))
        await session.execute(text(
            f"UPDATE {table} SET metadata=metadata-'resource_uri'-'resource_uris' "
            "WHERE metadata ?| ARRAY['resource_uri', 'resource_uris']"
        ))


async def memory_urls_backfill_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    if await _legacy_catalogue(session):
        pending = await session.scalar(text("""
            SELECT EXISTS (SELECT 1 FROM file_catalog_entries entry
            LEFT JOIN memory_urls location ON location.id=entry.memory_url_id
            WHERE entry.present AND entry.memory_item_id IS NOT NULL
              AND (location.id IS NULL OR location.memory_node_id<>entry.memory_item_id OR location.url<>entry.uri))
        """))
        if pending:
            return False
    return not bool(await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM memory_items WHERE metadata ?| ARRAY['resource_uri', 'resource_uris'])
        OR EXISTS (SELECT 1 FROM memory_revisions WHERE metadata ?| ARRAY['resource_uri', 'resource_uris'])
        OR EXISTS (SELECT 1 FROM memory_sources WHERE metadata ?| ARRAY['resource_uri', 'resource_uris'])
        OR EXISTS (SELECT 1 FROM memory_sources WHERE source_kind IN ('resource', 'attachment') AND strpos(source_ref, '://')>0)
        OR EXISTS (SELECT 1 FROM memory_items node WHERE
            (node.primary_url IS NULL AND EXISTS (SELECT 1 FROM memory_urls WHERE memory_node_id=node.id))
            OR (node.primary_url IS NOT NULL AND NOT EXISTS (SELECT 1 FROM memory_urls WHERE memory_node_id=node.id AND url=node.primary_url)))
    """)))


def register_url_backfill(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.memory.url_associations", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="single-memory-url-relation-v1", predicate=needs_url_backfill,
        handler=backfill_memory_urls, postcondition=memory_urls_backfill_complete,
    ))
