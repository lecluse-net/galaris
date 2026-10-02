"""Remove the obsolete technical avatar workflows during database convergence."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools import ToolModel
from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .models import ProcessDefinition, ProcessRun
from .process_service import TERMINAL_STATUSES, apply_engine_snapshot, refresh_run
from .schemas import EngineError, EngineRunSnapshot


async def _purge_avatar_processes(session: AsyncSession) -> None:
    definitions = list((await session.scalars(select(ProcessDefinition).where(
        ProcessDefinition.tool_id.in_(select(ToolModel.id).where(ToolModel.code == "agent_admin")),
        ProcessDefinition.engine_process_id.regexp_match(r"^agent_admin:[0-9]+:avatar$"),
    ).execution_options(include_historized=True))).all())
    for definition in definitions:
        runs = list((await session.scalars(select(ProcessRun).where(
            ProcessRun.process_id == definition.id,
        ).with_for_update().execution_options(include_historized=True))).all())
        for run in runs:
            if run.deleted_at is None:
                if run.status not in TERMINAL_STATUSES:
                    await apply_engine_snapshot(run, EngineRunSnapshot(status="error", error=EngineError(
                        code="avatar_process_removed",
                        message="Avatar generation now uses a direct function; this obsolete workflow was removed.",
                    )), "avatar.workflow.removed")
                # Settle existing approval receipts and wake any waiting Task before purging.
                if permit := run.launch_snapshot.get("authorization_permit"):
                    from uuid import UUID
                    from app.tools.facade import finish_action
                    await finish_action(UUID(str(permit)), deferred=True,
                        outcome="completed" if run.status == "success" else "failed")
                await refresh_run(run.id)
        # This targeted hard purge is intentional. FK cascades remove jobs, events and
        # conversation links; LLM calls and incidents retain their history with a null FK.
        await session.execute(delete(ProcessRun).where(ProcessRun.process_id == definition.id)
                              .execution_options(synchronize_session=False))
        await session.execute(delete(ProcessDefinition).where(ProcessDefinition.id == definition.id)
                              .execution_options(synchronize_session=False))


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(DbAdminReconciler(
        key="app.process.remove_avatar_workflows", handler=_purge_avatar_processes,
        depends_on=("app.tools.mandatory.tools",),
    ))
    registry.register_reconciler(DbAdminReconciler(
        key="app.process.move_document_analyses", handler=_move_document_analyses,
        depends_on=("app.tools.mandatory.tools",),
    ))


async def _move_document_analyses(session: AsyncSession) -> None:
    """Transfer exact internal workflows atomically, leaving business workflows alone."""
    from app.llm.facade import import_document_analysis

    definitions = list(await session.scalars(select(ProcessDefinition).where(
        ProcessDefinition.tool_id.in_(select(ToolModel.id).where(ToolModel.code == "galaris")),
        ProcessDefinition.engine_process_id.regexp_match(r"^galaris:[0-9]+:document_analysis$"),
    ).execution_options(include_historized=True)))
    for definition in definitions:
        runs = list(await session.scalars(select(ProcessRun).where(
            ProcessRun.process_id == definition.id,
        ).with_for_update().execution_options(include_historized=True)))
        for run in runs:
            await import_document_analysis(run.id, agent_id=run.launcher_agent_id, task_id=run.task_id,
                input_data=run.input, checkpoint=run.engine_metadata,
                status=run.status if run.status in TERMINAL_STATUSES | {"unknown", "cancelling"} else "running",
                output=run.output, error={"code": run.error_code, "message": run.error_message or "Analysis failed"}
                    if run.error_code else None,
                dispatch={**run.launch_snapshot, "claimed": run.engine_run_id is not None},
                idempotency_key=run.idempotency_key if definition.deleted_at is None and run.deleted_at is None else None)
            if run.await_task_id is not None and run.deleted_at is None:
                # Generic Process waiters cannot remain attached to deleted rows.
                if run.status not in TERMINAL_STATUSES:
                    await apply_engine_snapshot(run, EngineRunSnapshot(status="error", error=EngineError(
                        code="document_analysis_moved",
                        message="Analysis moved to document_analysis_get with the same run identifier.",
                    )), "document.analysis.moved")
                await refresh_run(run.id)
        await session.execute(delete(ProcessRun).where(ProcessRun.process_id == definition.id)
            .execution_options(synchronize_session=False))
        await session.execute(delete(ProcessDefinition).where(ProcessDefinition.id == definition.id)
            .execution_options(synchronize_session=False))
