"""Public resource operations authorized exclusively by the parent Process."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent import AgentManagementScope
from app.tools.facade import ToolDeletionSelection, AfterToolDeletion
from core.database import get_db
from core.storage import DiskFileDriver, StoredFile, retire_file_reference, retire_file_references, rename_stored_file
from core.util import complete_io

from .models import ProcessRunFile
from .run_data import lock_run, require_active, run_files, stage_run_file, validate_run_data


async def prepare_tool_deletion(selection: ToolDeletionSelection) -> AfterToolDeletion | None:
    """Retire owned file aliases; settle collaboration waits after the purge commits."""
    from .models import ProcessRun
    run_ids = [key[0] for key in selection.get("process_runs", ()) if isinstance(key[0], UUID)]
    if not run_ids:
        return None
    rows = (await get_db().execute(select(ProcessRun.id, ProcessRun.await_task_id,
        ProcessRun.status, ProcessRun.output, ProcessRun.error_message,
        ProcessRun.launch_snapshot, ProcessRun.await_resolved_at).where(ProcessRun.id.in_(run_ids)))).all()
    from .process_service import TERMINAL_STATUSES
    waits = [(row.id, row.await_task_id, row.status if row.status in TERMINAL_STATUSES else "cancelled",
              row.output, row.error_message or "The owning Tool was deleted.",
              str(row.launch_snapshot.get("process_label") or row.launch_snapshot.get("workflow_id") or row.id))
             for row in rows if row.await_task_id is not None and row.await_resolved_at is None]
    for run_id in run_ids:
        await retire_file_references(f"galaris://processes/runs/{run_id}/attachments/")

    async def settle_waits() -> None:
        from app.task import collab
        for run_id, task_id, status, output, error, label in waits:
            await collab.resolve_process_await(await_task_id=task_id, process_label=label,
                run_id=run_id, status=status, output=output, error=error)

    return settle_waits


async def read_run_data(identity: UUID, actor: int | AgentManagementScope) -> dict[str, Any]:
    from .native_runs import require_run
    run = await require_run(identity, actor)
    from .native_access import accessible_clause
    from .models import ProcessDefinition
    can_write = bool(await get_db().scalar(select(ProcessDefinition.id).where(
        ProcessDefinition.id == run.process_id, accessible_clause(actor, write=True))))
    from .process_service import TERMINAL_STATUSES
    from app.tools import has_process_admin_access
    if isinstance(actor, int) and await has_process_admin_access(actor):
        can_write = True
    native = run.engine_metadata.get("native", {})
    can_write = (can_write and run.status not in TERMINAL_STATUSES and
        native.get("status") not in TERMINAL_STATUSES and not native.get("cancel_requested") and
        run.launch_snapshot.get("definition", {}).get("graph", {}).get("schema_version") != "galaris.bpmn/v2")
    return {"id": str(identity), "data": deepcopy(run.data), "revision": run.data_revision,
        "files": await run_files(identity), "can_write": can_write}


async def write_run_data(identity: UUID, actor: int | AgentManagementScope, data: dict[str, Any],
                         *, expected_revision: int | None) -> dict[str, Any]:
    from app.file_share import ResourceRevisionConflict
    from .native_runs import require_run
    run = await lock_run(identity)
    await require_run(identity, actor, control=True)
    require_active(run)
    if run.launch_snapshot.get("definition", {}).get("graph", {}).get("schema_version") == "galaris.bpmn/v2":
        raise PermissionError("Only the engine can integrate typed run data; submit the activity output")
    if expected_revision is None or expected_revision != run.data_revision:
        raise ResourceRevisionConflict("Run data revision changed; reread before saving")
    run.data = validate_run_data(data)
    run.data_revision += 1
    await get_db().commit()
    return await read_run_data(identity, actor)


async def run_file_path(identity: UUID, file_id: UUID, actor: int | AgentManagementScope) -> tuple[dict[str, Any], Path]:
    from .native_runs import require_run
    await require_run(identity, actor)
    row = await get_db().scalar(select(ProcessRunFile).where(ProcessRunFile.run_id == identity,
        ProcessRunFile.file_id == file_id, ProcessRunFile.uri == f"galaris://processes/runs/{identity}/attachments/{file_id}"))
    stored = await get_db().get(StoredFile, file_id) if row is not None else None
    if row is None or stored is None or stored.backend != "disk":
        raise FileNotFoundError("Run attachment not found")
    return {"uri": row.uri, "name": stored.name, "media_type": stored.media_type,
        "size": stored.size_bytes, "checksum": stored.sha256}, DiskFileDriver().path(stored.storage_key)


async def rename_run_file(identity: UUID, file_id: UUID, actor: int | AgentManagementScope, name: str) -> None:
    from .native_runs import require_run
    await require_run(identity, actor, control=True)
    await run_file_path(identity, file_id, actor)
    await rename_stored_file(file_id, name)
    await get_db().commit()


async def add_run_file(identity: UUID, actor: int, content: bytes, *, name: str) -> dict[str, Any]:
    from .native_runs import require_run
    from app.memory import validate_attachment_content
    run = await lock_run(identity)
    await require_run(identity, actor, control=True)
    require_active(run)
    if run.launch_snapshot.get("definition", {}).get("graph", {}).get("schema_version") == "galaris.bpmn/v2":
        raise PermissionError("Only the engine publishes typed run attachments; submit output_files")
    media_type = validate_attachment_content(None, name, content)
    with TemporaryDirectory(prefix="galaris-run-file-") as directory:
        path = Path(directory) / "upload"
        await complete_io(path.write_bytes, content)
        receipt = await stage_run_file(run, path, name=name, media_type=media_type)
    await get_db().commit()
    return receipt


async def delete_run_file(identity: UUID, file_id: UUID, actor: int) -> None:
    from .native_runs import require_run
    run = await lock_run(identity)
    await require_run(identity, actor, control=True)
    require_active(run)
    if run.launch_snapshot.get("definition", {}).get("graph", {}).get("schema_version") == "galaris.bpmn/v2":
        raise PermissionError("Only the engine publishes typed run attachments")
    metadata, _ = await run_file_path(identity, file_id, actor)
    row = await get_db().scalar(select(ProcessRunFile).where(ProcessRunFile.run_id == identity,
        ProcessRunFile.uri == metadata["uri"]))
    assert row is not None
    row.soft_delete()
    await retire_file_reference(metadata["uri"])
    await get_db().commit()
