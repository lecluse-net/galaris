"""DbAdmin contributions for rebuildable memory projections."""

from loguru import logger
from sqlalchemy import String, cast, delete, exists, or_, select, text, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.dbadmin import (
    DbAdminAction, DbAdminPhase, DbAdminReconciler, DbAdminRegistry, SchemaTransitionSet,
)

from .semantic_index import reconcile_embedding_index
from .source_projection import rebuild_source_memories
from .models import MemoryContactIdentity, MemoryItem, MemoryRevision
from .catalogue_projection import reconcile_catalogue_descriptions








async def _reconcile_temporal_timezone(session: AsyncSession) -> None:
    """Keep calendar components while retiring per-memory timezone overrides."""
    for table in ("memory_items", "memory_revisions"):
        await session.execute(text(
            f"UPDATE {table} SET temporal = temporal - 'timezone' "
            "WHERE temporal ? 'timezone'"
        ))
    for table in ("memory_items", "memory_revisions", "memory_candidates", "memory_sources"):
        await session.execute(text(
            f"UPDATE {table} SET metadata = jsonb_set(metadata, '{{temporal}}', "
            "(metadata -> 'temporal') - 'timezone') "
            "WHERE jsonb_typeof(metadata -> 'temporal') = 'object' "
            "AND (metadata -> 'temporal') ? 'timezone'"
        ))


async def _reconcile_catalogue_editability(session: AsyncSession) -> None:
    """Upgrade old generated fiches once; later explicit read-only choices survive."""
    await session.execute(update(MemoryItem).where(
        MemoryItem.managed_source_kind == "file_catalogue",
        MemoryItem.node_kind.in_(("file", "directory")),
        MemoryItem.metadata_["catalogue_editable"].as_boolean().is_not(True),
    ).values(read_only=False, metadata_=MemoryItem.metadata_.op("||")(func.jsonb_build_object("catalogue_editable", True))))


async def _reconcile_catalogue_descriptions(_session: AsyncSession) -> None:
    await reconcile_catalogue_descriptions()


async def _reconcile_internal_user_identities(session: AsyncSession) -> None:
    """Retire only native Chat aliases already represented by the same user."""
    user_identity = aliased(MemoryContactIdentity)
    await session.execute(
        delete(MemoryContactIdentity).where(
            MemoryContactIdentity.identity_kind == "messenger",
            MemoryContactIdentity.namespace == "internal",
            exists(select(user_identity.id).where(
                user_identity.contact_item_id == MemoryContactIdentity.contact_item_id,
                user_identity.owner_agent_id == MemoryContactIdentity.owner_agent_id,
                user_identity.identity_kind == "galaris_user",
                user_identity.namespace == "galaris",
                user_identity.external_id == cast(user_identity.galaris_user_id, String),
                MemoryContactIdentity.external_id == "user:" + cast(user_identity.galaris_user_id, String),
            )),
        )
    )


async def _reconcile_live_contacts(session: AsyncSession) -> None:
    """Retire generated contact bodies while preserving canonical data/history."""
    contacts = select(MemoryItem.id).where(
        MemoryItem.source_managed.is_(True),
        MemoryItem.managed_source_kind == "messenger_contact",
    ).execution_options(include_historized=True)
    await session.execute(update(MemoryItem).where(MemoryItem.id.in_(contacts), or_(
        MemoryItem.memory_content.is_not(None), MemoryItem.memory_content_type != "text",
        MemoryItem.memory_media_type != "application/json", MemoryItem.memory_content_profile_version.is_not(None),
    )).values(
        memory_content=None, memory_content_type="text",
        memory_media_type="application/json", memory_content_profile_version=None,
        updated_at=MemoryItem.updated_at,
    ).execution_options(include_historized=True))
    await session.execute(update(MemoryRevision).where(MemoryRevision.item_id.in_(contacts), or_(
        MemoryRevision.content.is_not(None), MemoryRevision.content_type != "text",
        MemoryRevision.media_type != "application/json", MemoryRevision.content_profile_version.is_not(None),
    )).values(
        content=None, content_type="text", media_type="application/json", content_profile_version=None,
    ))


def needs_document_append_backfill(transitions: SchemaTransitionSet) -> bool:
    return "memory_revisions.reason" in transitions.removed_columns


async def document_append_backfill_complete(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> bool:
    legacy_column = await session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'memory_revisions' "
        "AND column_name = 'reason')"
    ))
    if not legacy_column:
        return True
    pending = await session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM memory_revisions "
        "WHERE reason = 'Document content appended' "
        "AND document_append IS NOT TRUE)"
    ))
    return not pending


async def backfill_document_appends(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> None:
    await session.execute(text(
        "UPDATE memory_revisions SET document_append = true "
        "WHERE reason = 'Document content appended' AND document_append IS NOT TRUE"
    ))


async def _reconcile_source_projections(_session: AsyncSession) -> None:
    result = await rebuild_source_memories(missing_only=True)
    logger.info("Source-memory reconciliation: {}", result.model_dump())
    if result.failures:
        raise RuntimeError(
            "Source-memory reconciliation failed for: " + ", ".join(result.failures)
        )


async def _reconcile_semantic_index(_session: AsyncSession) -> None:
    result = await reconcile_embedding_index(missing_only=True)
    logger.info("Semantic-memory reconciliation: {}", result.model_dump())


async def _reconcile_document_structure(_session: AsyncSession) -> None:
    from .document_structure import reconcile_document_structure
    await reconcile_document_structure()






def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.live_contacts", handler=_reconcile_live_contacts,
        depends_on=("app.memory.source_projections",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.internal_user_identities",
        handler=_reconcile_internal_user_identities,
        depends_on=("app.memory.source_projections",),
    ))
    from .content_migration import register_inline_content
    register_inline_content(registry)
    from .file_attributes_migration import register_file_attributes
    register_file_attributes(registry)
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.temporal_timezone", handler=_reconcile_temporal_timezone,
    ))
    from .url_migration import register_url_backfill
    register_url_backfill(registry)
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.catalogue_descriptions", handler=_reconcile_catalogue_descriptions,
        depends_on=("app.memory.editorial_text",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.catalogue_editability", handler=_reconcile_catalogue_editability,
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.document_structure", handler=_reconcile_document_structure,
        depends_on=("app.memory.editorial_text",),
    ))
    registry.register_action(DbAdminAction(
        key="app.memory.document_append_marker",
        phase=DbAdminPhase.AFTER_EXPAND,
        checksum="preserve-legacy-document-append-retries-v1",
        predicate=needs_document_append_backfill,
        handler=backfill_document_appends,
        postcondition=document_append_backfill_complete,
    ))
    from .html_migration import register_html_conversion

    register_html_conversion(registry)
    from .html_migration import rebuild_html_text
    registry.register_reconciler(DbAdminReconciler(key="app.memory.editorial_text", handler=rebuild_html_text, depends_on=("app.memory.source_projections", "app.memory.live_contacts")))
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.memory.source_projections",
            handler=_reconcile_source_projections,
            depends_on=("app.llm.current_profile", "app.memory.temporal_timezone", "app.memory.goal_document_paths"),
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.memory.semantic_index",
            handler=_reconcile_semantic_index,
            depends_on=("app.memory.source_projections", "app.memory.editorial_text", "app.memory.catalogue_descriptions"),
            required=False,
        )
    )
