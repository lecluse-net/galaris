"""Preserve documentary resources before separating their optional Memory content."""

from hashlib import sha256
from html import escape

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import convert_to_html, visible_text

from .models import MemoryItem
from .document_backup import (
    backup_documents, document_backup_complete, needs_document_backup, verify_unchanged_sources,
)
from .storage import get_storage


def needs_document_split(delta: SchemaTransitionSet) -> bool:
    # The removed-column delta also qualifies installations that received the
    # earlier expansion-only implementation before this archive was introduced.
    return needs_document_backup(delta)


async def document_split_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await document_backup_complete(session, _delta):
        return False
    if not await session.scalar(text("SELECT transferred FROM galaris_migration.memory_document_split_manifest")):
        return False
    return not bool(await session.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM memory_items node LEFT JOIN documents doc ON doc.memory_item_id = node.id
            WHERE node.node_kind = 'document' AND (doc.id IS NULL OR NOT doc.summary_initialized)
        ) OR EXISTS (
            SELECT 1 FROM memory_revisions revision JOIN documents doc ON doc.memory_item_id = revision.item_id
            LEFT JOIN document_revisions owned ON owned.id = revision.id
            WHERE owned.id IS NULL OR owned.document_id <> doc.id OR owned.revision <> revision.revision
        ) OR EXISTS (
            SELECT 1 FROM memory_items WHERE NOT source_managed AND node_kind = 'memory'
            AND (NOT title_is_projection
                OR EXISTS (SELECT 1 FROM memory_item_grants WHERE item_id = memory_items.id)
                OR EXISTS (SELECT 1 FROM document_user_grants WHERE item_id = memory_items.id)
                OR EXISTS (SELECT 1 FROM document_team_grants WHERE item_id = memory_items.id))
        )
    """)))


async def split_documents(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    created: list[tuple[str, str]] = []
    try:
        await _split_documents(session, _delta, created)
    except BaseException:
        # Resource providers do not participate in the SQL rollback. Compensate
        # only newly created replacements; archived originals remain untouched.
        for provider, pointer in created:
            try:
                await get_storage(provider).delete(pointer)
            except Exception:
                logger.exception("Document migration replacement cleanup failed")
        raise


async def _split_documents(
    session: AsyncSession, _delta: SchemaTransitionSet, created: list[tuple[str, str]],
) -> None:
    if not await document_backup_complete(session, _delta):
        raise RuntimeError("A verified pre-expansion document backup is required")
    if await session.scalar(text("SELECT transferred FROM galaris_migration.memory_document_split_manifest")):
        return  # A later replay must not touch newly authored documents or summaries.
    await verify_unchanged_sources(session)
    # Copy pointers, not bytes: every historical revision and attachment keeps its
    # original resource identity. Include tombstones for historical Chat previews.
    await session.execute(text("""
        WITH archived AS (
            SELECT snapshot, row_key FROM galaris_migration.memory_document_split_rows
            WHERE table_name = 'memory_items'
        ), locked_sources AS (
            SELECT (jsonb_populate_record(NULL::public.documents, snapshot || jsonb_build_object(
                'memory_item_id', snapshot->'id', 'summary_initialized', false,
                'visibility', CASE WHEN snapshot->>'visibility' = 'public' THEN 'shared'
                    ELSE snapshot->>'visibility' END,
                'global_access', CASE WHEN snapshot->>'visibility' = 'public' THEN 1
                    ELSE coalesce((snapshot->>'global_access')::integer, 0) END
            ))).* FROM archived
            JOIN memory_items node ON node.id::text = archived.row_key
            WHERE node_kind = 'document' OR (node_kind = 'memory' AND NOT source_managed AND (
                snapshot->>'visibility' <> 'private' OR (snapshot->>'global_access')::integer <> 0
                OR (snapshot->>'group_access')::integer <> 0
                OR EXISTS (SELECT 1 FROM memory_item_grants WHERE item_id = node.id)
                OR EXISTS (SELECT 1 FROM document_user_grants WHERE item_id = node.id)
                OR EXISTS (SELECT 1 FROM document_team_grants WHERE item_id = node.id)))
            ORDER BY node.id
        )
        INSERT INTO documents (id, memory_item_id, title, provider_code, resource_id, revision,
            document_type, content_type, media_type, content_profile_version, filename,
            content_hash, size_bytes, visibility, global_access, group_access, read_only,
            summary_initialized, created_at, updated_at, deleted_at, created_by, updated_by, deleted_by)
        SELECT id, id, title, provider_code, resource_id, revision, document_type,
            content_type, media_type, content_profile_version, filename, content_hash, size_bytes,
            CASE WHEN visibility = 'public' THEN 'shared' ELSE visibility END,
            CASE WHEN visibility = 'public' THEN 1 ELSE global_access END, group_access, read_only,
            false, created_at, updated_at, deleted_at, created_by, updated_by, deleted_by
        FROM locked_sources node
        ON CONFLICT (memory_item_id) DO NOTHING
    """))
    await session.execute(text("""
        INSERT INTO document_revisions (id, document_id, revision)
        SELECT archived.row_key::uuid, doc.id, (archived.snapshot->>'revision')::integer
        FROM galaris_migration.memory_document_split_rows archived
        JOIN documents doc ON doc.memory_item_id = (archived.snapshot->>'item_id')::uuid
        WHERE archived.table_name = 'memory_revisions'
        ON CONFLICT (id) DO NOTHING
    """))
    # Refuse to clear a source that was not copied exactly. This also distinguishes
    # an unfinished transfer from a summary already edited after a successful run.
    mismatch = await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM documents doc
            JOIN galaris_migration.memory_document_split_rows archived
            ON archived.table_name = 'memory_items' AND archived.row_key = doc.memory_item_id::text
            WHERE NOT doc.summary_initialized AND (doc.resource_id <> archived.snapshot->>'resource_id'
                OR doc.provider_code <> archived.snapshot->>'provider_code'
                OR doc.content_hash <> archived.snapshot->>'content_hash'
                OR doc.revision <> (archived.snapshot->>'revision')::integer))
    """))
    if mismatch:
        raise RuntimeError("Document source changed during the transfer; source content preserved")
    await session.execute(text("""
        INSERT INTO memory_summary_revisions (id, item_id, revision, provider_code, resource_id,
            content_hash, source_document_revision, keywords, temporal, created_at)
        SELECT gen_random_uuid(), node.id, 1, 'native', '', :empty_hash, doc.revision,
            node.keywords, node.temporal, node.created_at
        FROM documents doc JOIN memory_items node ON node.id = doc.memory_item_id
        WHERE NOT doc.summary_initialized
        ON CONFLICT (item_id, revision) DO NOTHING
    """), {"empty_hash": sha256(b"").hexdigest()})
    # Keywords remain on the same graph node, shared by both editors. Neither
    # this transfer nor a replay restores them from an older content snapshot.
    await session.execute(text("""
        UPDATE memory_items node SET node_kind = 'document', provider_code = 'native', resource_id = '',
            content_hash = :empty_hash, size_bytes = 0, revision = 1,
            content_type = 'text', media_type = 'text/html', content_profile_version = 1,
            read_only = node.source_managed, title_is_projection = true,
            lock_version = node.lock_version + 1
        FROM documents doc WHERE node.id = doc.memory_item_id AND NOT doc.summary_initialized
    """), {"empty_hash": sha256(b"").hexdigest()})
    await session.execute(text("UPDATE documents SET summary_initialized = true WHERE NOT summary_initialized"))
    # Structural nodes retain their original export names without a redundant
    # documentary column. Existing metadata, including explicit NULLs, survives.
    await session.execute(text("""
        UPDATE memory_items node SET metadata = node.metadata || jsonb_build_object(
            'memory_filename', archived.snapshot->'filename')
        FROM galaris_migration.memory_document_split_rows archived
        WHERE archived.table_name = 'memory_items' AND archived.row_key = node.id::text
            AND node.node_kind <> 'document' AND archived.snapshot->>'filename' IS NOT NULL
    """))

    # Preserve information from authored memory titles before making titles a
    # derived display projection. Immutable older revisions remain untouched.
    archived = text("""
        SELECT row_key, snapshot->>'provider_code', snapshot->>'resource_id', snapshot->>'title'
        FROM galaris_migration.memory_document_split_rows
        WHERE table_name = 'memory_items' AND row_key = ANY(:identities)
    """)
    while True:
        items = list(await session.scalars(select(MemoryItem).where(
            MemoryItem.node_kind == "memory", MemoryItem.source_managed.is_(False),
            MemoryItem.title_is_projection.is_(False),
        ).execution_options(include_historized=True).order_by(MemoryItem.id).limit(100)))
        if not items:
            break
        sources = {str(row[0]): (str(row[1]), str(row[2]), str(row[3] or "")) for row in
            await session.execute(archived, {"identities": [str(item.id) for item in items]})}
        for item in items:
            if item.deleted_at is None and item.content_type == "text":
                source = sources[str(item.id)]
                storage = get_storage(source[0])
                original = await storage.read(source[1])
                html = convert_to_html(original.decode("utf-8"), item.media_type, profile="rich-text")
                label = source[2].strip()
                if label and label.casefold() not in visible_text(html).casefold():
                    html = f"<p>{escape(label)}</p>{html}"
                payload = html.encode("utf-8")
                if payload != original:
                    from .service import _revision_for  # pyright: ignore[reportPrivateUsage]
                    from .models import MemoryRevision
                    if await session.scalar(select(MemoryRevision.id).where(
                        MemoryRevision.item_id == item.id, MemoryRevision.revision == item.revision,
                    )) is None:
                        session.add(_revision_for(item, author_agent_id=None))
                        await session.flush()
                    replacement = await storage.create(payload)
                    created.append((item.provider_code, replacement))
                    item.resource_id = replacement
                    item.content_hash = sha256(payload).hexdigest()
                    item.size_bytes = len(payload)
                    item.media_type = "text/html"
                    item.content_profile_version = 1
                    item.revision += 1
                    session.add(_revision_for(item, author_agent_id=None))
                item.search_text = visible_text(html)
                item.search_title = item.search_text[:120]
                item.semantic_fingerprint = ""
            item.title_is_projection = True
        await session.flush()
    await session.execute(text("UPDATE galaris_migration.memory_document_split_manifest SET transferred = true"))


def register_document_split(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.memory.document_split_backup", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="immutable-memory-items-revisions-grants-before-documents-v1",
        predicate=needs_document_backup, handler=backup_documents,
        postcondition=document_backup_complete,
    ))
    registry.register_action(DbAdminAction(
        key="app.memory.document_split", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="documents-from-verified-immutable-archive-v1",
        compatible_checksums=frozenset({"separate-documents-preserve-resource-identities-and-history"}),
        predicate=needs_document_split, handler=split_documents,
        postcondition=document_split_complete,
    ))
