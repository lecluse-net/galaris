"""DbAdmin contributions for rebuildable memory projections."""

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminAction, DbAdminPhase, DbAdminReconciler, DbAdminRegistry, SchemaTransitionSet,
)

from .goal_document_adapter import (
    reconcile_goal_document_paths,
    register_goal_document_adapter,
)
from .semantic_index import reconcile_embedding_index
from .source_projection import rebuild_source_memories


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
    register_goal_document_adapter()
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


async def _reconcile_goal_document_paths(session: AsyncSession) -> None:
    changed = await reconcile_goal_document_paths(session)
    logger.info("Goal-document path reconciliation: changed={}", changed)


async def _enqueue_goal_folders(_session: AsyncSession) -> None:
    from app.goal import Goal
    from .goal_folders import enqueue_goal_folder_reconciliation

    if await _session.scalar(select(Goal.id).limit(1)) is not None:
        await enqueue_goal_folder_reconciliation()


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(DbAdminReconciler(
        key="app.memory.goal_folders", handler=_enqueue_goal_folders,
        depends_on=("app.memory.goal_document_paths", "app.memory.document_structure"),
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
    registry.register_reconciler(DbAdminReconciler(key="app.memory.editorial_text", handler=rebuild_html_text, depends_on=("app.memory.source_projections",)))
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.memory.goal_document_paths",
            handler=_reconcile_goal_document_paths,
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.memory.source_projections",
            handler=_reconcile_source_projections,
            depends_on=("app.llm.current_profile",),
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.memory.semantic_index",
            handler=_reconcile_semantic_index,
            depends_on=("app.memory.source_projections", "app.memory.editorial_text"),
            required=False,
        )
    )
