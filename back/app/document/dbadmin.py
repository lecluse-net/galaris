"""Canonical documentary transfers; historical action identities remain resumable."""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminReconciler, DbAdminRegistry, SchemaTransitionSet
from .independence import register_independence, transfer_complete, needs_independence
from .document_backup import needs_document_backup, backup_documents, document_backup_complete
from . import document_thumbnail_cache


def needs_thumbnails(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("documents") or delta.column_added("documents","thumbnail_id")


async def clean_thumbnails(_session: AsyncSession,_delta: SchemaTransitionSet) -> None:
    await asyncio.to_thread(document_thumbnail_cache.discard_all_legacy)


async def thumbnails_clean(_session: AsyncSession,_delta: SchemaTransitionSet) -> bool:
    return await asyncio.to_thread(lambda: next(document_thumbnail_cache.legacy_files(),None) is None)


async def reconcile_sharing(_session: AsyncSession) -> None:
    from .sharing_inheritance import reconcile_sharing as reconcile
    await reconcile()


async def reconcile_goal_paths(session: AsyncSession) -> None:
    from .goal_document_adapter import reconcile_goal_document_paths, register_goal_document_adapter
    register_goal_document_adapter()
    await reconcile_goal_document_paths(session)


async def retire_goal_filing(session: AsyncSession) -> None:
    """Retire automatic filing without removing anyone's personal folders."""
    from sqlalchemy import text
    await session.execute(text("""UPDATE document_automation_jobs SET status='success',
        locked_at=NULL, last_error=NULL WHERE kind='goal_folder_reconcile'
        AND status IN ('pending','running')"""))
    await session.execute(text("""UPDATE documents SET metadata=metadata-'document_path'
        WHERE metadata->>'goal_document_kind' IN ('description','tracking')
        AND metadata ? 'document_path'"""))


def needs_filing_retirement(delta: SchemaTransitionSet) -> bool:
    return "document_tags.goal_id" in delta.removed_columns


async def retire_filing(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await retire_goal_filing(session)


async def filing_retired(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    from sqlalchemy import text
    return not await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM document_automation_jobs
        WHERE kind='goal_folder_reconcile' AND status IN ('pending','running'))
        OR EXISTS(SELECT 1 FROM documents WHERE metadata->>'goal_document_kind'
        IN ('description','tracking') AND metadata ? 'document_path')"""))


async def verify_historical_transfer(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    if not await transfer_complete(session, delta):
        raise RuntimeError("The canonical Document transfer must complete before retiring the historical split action")


def register_dbadmin(registry: DbAdminRegistry) -> None:
    from .unification import register as register_typed_documents
    register_typed_documents(registry)
    from .summary_retirement import register
    from .resource_summaries import reconcile
    register(registry)
    async def summaries(_session: AsyncSession) -> None:
        await reconcile()
    registry.register_reconciler(DbAdminReconciler(key="app.document.current_summaries", handler=summaries))
    from .privilege_migration import register_privilege_migration
    from .tool_migration import register_tool_migration
    register_privilege_migration(registry)
    register_tool_migration(registry)
    register_independence(registry)
    registry.register_action(DbAdminAction(key="app.memory.document_split_backup",phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="immutable-memory-items-revisions-grants-before-documents-v1",predicate=needs_document_backup,
        handler=backup_documents,postcondition=document_backup_complete))
    registry.register_action(DbAdminAction(key="app.memory.document_split",phase=DbAdminPhase.AFTER_EXPAND,
        checksum="autonomous-documents-preserve-historical-split-obligations-v1",
        compatible_checksums=frozenset({"documents-from-verified-immutable-archive-v1","separate-documents-preserve-resource-identities-and-history"}),
        predicate=needs_independence,handler=verify_historical_transfer,postcondition=transfer_complete))
    registry.register_action(DbAdminAction(key="app.memory.document_thumbnail_pointer",phase=DbAdminPhase.AFTER_EXPAND,
        checksum="single-document-thumbnail-without-revision-sidecars-v1",predicate=needs_thumbnails,
        handler=clean_thumbnails,postcondition=thumbnails_clean))
    registry.register_reconciler(DbAdminReconciler(key="app.document.sharing_inheritance",handler=reconcile_sharing))
    registry.register_reconciler(DbAdminReconciler(key="app.memory.goal_document_paths",handler=reconcile_goal_paths))
    registry.register_action(DbAdminAction(key="app.document.retire_goal_filing",
        phase=DbAdminPhase.AFTER_EXPAND, checksum="manual-classification-without-goal-folder-metadata-v1",
        predicate=needs_filing_retirement, handler=retire_filing, postcondition=filing_retired))
