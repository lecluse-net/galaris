"""Human-facing REST API and machine endpoints for processes."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.params import runtime_settings
from core.authorize import Privileges, authorize, independent_auth
from core.i18n import tr
from app.agent import AgentManagementScope, current_management_scope

from . import metrics, process_service
from .schemas import (
    AdminProcessStartRequest,
    ProcessAnalysis,
    ProcessCallbackEvent,
    ProcessDefinitionCreate,
    ProcessDefinitionRead,
    ProcessDefinitionUpdate,
    ProcessRunDetail,
    ProcessRunPage,
    ProcessRunRead,
    ProcessStartResponse,
    ProcessToolRead,
    ProcessEngineHealth,
    ProcessOperationsRead,
)

routes = APIRouter(tags=["processes"])


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def _require_agent(
    scope: AgentManagementScope,
    agent_id: int | None,
) -> None:
    if agent_id is not None and not scope.allows(agent_id):
        raise _not_found(await tr("process.errors.agent_not_found"))


async def _definition_or_404(process_id: int) -> Any:
    scope = await current_management_scope()
    record = await process_service.get_definition(process_id)
    if record is None:
        raise _not_found(await tr("process.errors.process_not_found"))
    await _require_agent(scope, record.agent_id)
    return record


async def _run_or_404(run_id: UUID) -> Any:
    scope = await current_management_scope()
    run = await process_service.get_run(run_id)
    if run is None or not scope.allows(run.launcher_agent_id):
        raise _not_found(await tr("process.errors.run_not_found"))
    return run


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global Agent management is required",
        )


@routes.get("/retention/preview")
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def preview_retention() -> dict[str, int]:
    await _require_global_scope()
    return await process_service.purge_retention(preview=True)


@routes.get("/runs/{run_id}/export")
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def export_process_run(
    run_id: UUID,
    after_event: int = Query(default=0, ge=0),
    page_size: Literal[10, 20, 50, 100, 500] = 50,
) -> dict[str, Any]:
    from .export import export_run

    await _run_or_404(run_id)
    return await export_run(run_id, after_event=after_event, page_size=page_size)


@routes.get("/tools", response_model=list[ProcessToolRead])
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_process_tools() -> list[Any]:
    return await process_service.list_process_tools()


@routes.get("/tools/{tool_code}/health", response_model=ProcessEngineHealth)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_process_tool_health(tool_code: str) -> ProcessEngineHealth:
    try:
        return await process_service.get_tool_health(tool_code)
    except LookupError as exc:
        raise _not_found(str(exc)) from exc


@routes.get("/operations", response_model=ProcessOperationsRead)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_process_operations(
    agent_id: Optional[int] = Query(default=None, gt=0),
) -> ProcessOperationsRead:
    scope = await current_management_scope()
    await _require_agent(scope, agent_id)
    agent_ids = frozenset({agent_id}) if agent_id is not None else scope.agent_ids
    return await process_service.get_operations(agent_ids=agent_ids)


@routes.get("/definitions", response_model=list[ProcessDefinitionRead])
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_definitions(
    agent_id: Optional[int] = Query(default=None, gt=0),
) -> list[Any]:
    scope = await current_management_scope()
    await _require_agent(scope, agent_id)
    return await process_service.list_definitions(
        agent_id=agent_id,
        agent_ids=scope.agent_ids,
    )


@routes.post("/definitions", response_model=ProcessDefinitionRead, status_code=201)
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def create_definition(data: ProcessDefinitionCreate) -> Any:
    try:
        scope = await current_management_scope()
        await _require_agent(scope, data.agent_id)
        return await process_service.create_definition(data)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@routes.post("/definitions/sync")
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def sync_definitions(tool_code: str = "n8n") -> list[dict[str, Any]]:
    try:
        await _require_global_scope()
        return await process_service.sync_tool_definitions(tool_code)
    except HTTPException:
        raise
    except (LookupError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@routes.get("/definitions/{process_id}", response_model=ProcessDefinitionRead)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_definition(process_id: int) -> Any:
    return await _definition_or_404(process_id)


@routes.put("/definitions/{process_id}", response_model=ProcessDefinitionRead)
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def update_definition(process_id: int, data: ProcessDefinitionUpdate) -> Any:
    try:
        await _definition_or_404(process_id)
        scope = await current_management_scope()
        if "agent_id" in data.model_fields_set:
            await _require_agent(scope, data.agent_id)
        record = await process_service.update_definition(process_id, data)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise _not_found(await tr("process.errors.process_not_found"))
    return record


@routes.delete("/definitions/{process_id}", status_code=204)
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def delete_definition(process_id: int) -> None:
    await _definition_or_404(process_id)
    if not await process_service.delete_definition(process_id):
        raise _not_found(await tr("process.errors.process_not_found"))


@routes.post("/runs", response_model=ProcessStartResponse, status_code=202)
@authorize(privileges=Privileges.PROCESS_LAUNCH)
async def create_run(data: AdminProcessStartRequest) -> ProcessStartResponse:
    try:
        scope = await current_management_scope()
        await _require_agent(scope, data.agent_id)
        return await process_service.start_process(
            agent_id=data.agent_id,
            workflow_id=data.workflow_id,
            input_data=data.input,
            files=data.files,
            wait_for_completion=data.wait_for_completion,
            idempotency_key=data.idempotency_key,
            task_id=data.task_id,
            runtime=data.runtime,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@routes.post(
    "/workflows/{workflow_id}/runs/{engine_run_id}/sync",
    response_model=ProcessRunRead,
)
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def sync_engine_run(workflow_id: str, engine_run_id: str) -> ProcessRunRead:
    try:
        scope = await current_management_scope()
        run = await process_service.resolve_engine_run(
            workflow_id,
            engine_run_id,
            agent_ids=scope.agent_ids,
        )
        if run.status not in process_service.TERMINAL_STATUSES:
            run = await process_service.refresh_run(run.id)
        return await process_service._run_read(run)  # pyright: ignore[reportPrivateUsage]
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@routes.get("/runs", response_model=ProcessRunPage)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def read_runs(
    agent_id: Optional[int] = None,
    process_id: Optional[int] = None,
    workflow_id: Optional[str] = None,
    run_status: Optional[str] = Query(default=None, alias="status"),
    active: bool | None = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=255),
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    sort_by: Literal[
        "status", "launcher_agent_id", "created_at", "finished_at"
    ] = "created_at",
    descending: bool = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> ProcessRunPage:
    scope = await current_management_scope()
    await _require_agent(scope, agent_id)
    rows, total = await process_service.paginate_runs(
        agent_id=agent_id,
        process_id=process_id,
        workflow_id=workflow_id,
        status=run_status,
        active=active,
        search=search,
        created_after=created_after,
        created_before=created_before,
        sort_by=sort_by,
        descending=descending,
        page=page,
        page_size=page_size,
        agent_ids=scope.agent_ids,
    )
    return ProcessRunPage(
        items=[
            await process_service._run_read(run)  # pyright: ignore[reportPrivateUsage]
            for run in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@routes.get("/runs/{run_id}", response_model=ProcessRunDetail)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def read_run(run_id: UUID) -> ProcessRunDetail:
    await _run_or_404(run_id)
    detail = await process_service.get_run_detail(run_id)
    if detail is None:
        raise _not_found(await tr("process.errors.run_not_found"))
    return detail


@routes.delete("/runs/{run_id}", status_code=204)
@authorize(privileges=Privileges.PROCESS_ADMIN)
async def delete_run(run_id: UUID) -> None:
    try:
        await _run_or_404(run_id)
        deleted = await process_service.delete_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise _not_found(await tr("process.errors.run_not_found"))


@routes.post("/runs/{run_id}/refresh", response_model=ProcessRunRead)
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def refresh_run(run_id: UUID) -> ProcessRunRead:
    try:
        await _run_or_404(run_id)
        run = await process_service.refresh_run(run_id)
        return await process_service._run_read(run)  # pyright: ignore[reportPrivateUsage]
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@routes.post("/runs/{run_id}/analyze", response_model=ProcessAnalysis)
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def analyze_run(run_id: UUID) -> ProcessAnalysis:
    try:
        await _run_or_404(run_id)
        return await process_service.analyze_run(run_id)
    except LookupError as exc:
        raise _not_found(str(exc)) from exc


@routes.post("/runs/{run_id}/cancel", response_model=ProcessRunRead)
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def cancel_run(run_id: UUID) -> ProcessRunRead:
    try:
        await _run_or_404(run_id)
        run = await process_service.cancel_run(run_id)
        return await process_service._run_read(run)  # pyright: ignore[reportPrivateUsage]
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@routes.post("/runs/{run_id}/retry", response_model=ProcessStartResponse, status_code=202)
@authorize(privileges=[Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN])
async def retry_run(run_id: UUID) -> ProcessStartResponse:
    try:
        await _run_or_404(run_id)
        return await process_service.retry_run(run_id)
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _machine_token(request: Request) -> str:
    value = request.headers.get(runtime_settings.PROCESS_N8N_CALLBACK_AUTH_HEADER, "")
    if not value:
        auth = request.headers.get("Authorization", "")
        value = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    return value


@routes.post("/runs/{run_id}/events")
@independent_auth(reason="Per-run process callback token")
async def receive_event(run_id: UUID, data: ProcessCallbackEvent, request: Request) -> dict[str, Any]:
    try:
        run, duplicate = await process_service.receive_callback(
            run_id, await _machine_token(request), data
        )
        return {"ok": True, "duplicate": duplicate, "run_id": str(run.id), "status": run.status}
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@routes.get("/runs/{run_id}/files/{file_id}")
@independent_auth(reason="Per-run process callback token")
async def download_run_file(run_id: UUID, file_id: str, request: Request) -> FileResponse:
    try:
        ref = await process_service.file_reference(
            run_id, file_id, await _machine_token(request)
        )
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    from app.file_share import (
        ResourceContext,
        materialize_resource,
        parse_resource_uri,
    )

    run = await process_service.get_run(run_id)
    if run is None:
        raise _not_found(await tr("process.errors.run_not_found"))
    temp = tempfile.NamedTemporaryFile(delete=False)
    temp.close()
    temp_path = Path(temp.name)
    console_resource = None
    try:
        reference = parse_resource_uri(ref.uri)
        if reference.scheme == "console":
            from app.console import build_run_resource

            console_resource = await build_run_resource(run.launcher_agent_id)
        await materialize_resource(
            ResourceContext(
                agent_id=run.launcher_agent_id,
                runtime=ref.runtime,
                task_id=ref.task_id,
                console_resource=console_resource,
            ),
            reference,
            temp_path,
            max_bytes=process_service.PROCESS_FILE_MAX_BYTES,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        if console_resource is not None:
            await console_resource.close()
    return FileResponse(
        temp_path,
        filename=ref.filename,
        media_type=ref.content_type,
        background=BackgroundTask(temp_path.unlink, missing_ok=True),
    )


@routes.get("/metrics")
@authorize(privileges=[Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN])
async def read_metrics() -> dict[str, list[dict[str, Any]]]:
    await _require_global_scope()
    return metrics.snapshot()


# `/processes` is the canonical API. Keep the former French path as a hidden,
# deprecated alias so existing n8n callbacks and bookmarks continue to work.
router = APIRouter()
router.include_router(routes, prefix="/processes")
router.include_router(
    routes,
    prefix="/processus",
    include_in_schema=False,
    deprecated=True,
)
