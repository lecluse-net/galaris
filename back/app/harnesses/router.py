"""Harness selection, installation, diagnostics, and supervision API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.agent import (
    AgentTaskBlockers,
    AgentOwnerAssertion,
    current_management_scope,
    get_agent_record,
    get_agent_task_blockers,
    terminate_paused_agent_tasks,
)
from core.authorize import Privileges, authorize

from .contracts import HarnessAction, lifecycle_actions
from .registry import UnknownHarnessProviderError, all_providers, get_provider
from .schemas import (
    HarnessActionResult,
    HarnessCatalogCreate,
    HarnessCatalogRead,
    HarnessCatalogUpdate,
    HarnessLogs,
    HarnessProviderRead,
    HarnessProbe,
    HarnessProbeResult,
    HarnessRead,
    HarnessRuntimeState,
    HarnessSelectionUpdate,
    HarnessTaskBlocker,
    HarnessTaskBlockers,
)
from . import service


router = APIRouter(prefix="/harnesses", tags=["harnesses"])

from .configuration import (
    HarnessConfigurationConflict, HarnessConfigurationRead, HarnessConfigurationUpdate,
    list_configurations, update_configuration,
    configured_provider_capabilities,
)


@router.get("/execution-configurations", response_model=list[HarnessConfigurationRead])
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def read_execution_configurations() -> list[HarnessConfigurationRead]:
    return await list_configurations()


@router.put("/execution-configurations/{provider_code}", response_model=HarnessConfigurationRead)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def save_execution_configuration(
    provider_code: str, data: HarnessConfigurationUpdate,
) -> HarnessConfigurationRead:
    if not (await current_management_scope()).is_global:
        raise HTTPException(status_code=403, detail="Global Agent management is required")
    try:
        return await update_configuration(provider_code, data)
    except HarnessConfigurationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _task_blockers_read(blockers: AgentTaskBlockers) -> HarnessTaskBlockers:
    return HarnessTaskBlockers(
        paused_tasks=[
            HarnessTaskBlocker(id=task.id, label=task.label)
            for task in blockers.paused_tasks
        ],
        active_count=blockers.active_count,
        active_tasks=[
            HarnessTaskBlocker(id=task.id, label=task.label)
            for task in blockers.active_tasks
        ],
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError) and not isinstance(exc, UnknownHarnessProviderError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (service.HarnessConflictError, UnknownHarnessProviderError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/providers", response_model=list[HarnessProviderRead])
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def list_harness_providers() -> list[HarnessProviderRead]:
    return [
        HarnessProviderRead(
            code=provider.code,
            label=provider.label,
            driver_code=provider.driver_code,
            containerized=provider.containerized,
            max_parallel_tasks=provider.max_parallel_tasks,
            capabilities=sorted(provider.capabilities()),
        )
        for provider in all_providers()
    ]


@router.get("/catalog", response_model=list[HarnessCatalogRead])
@authorize(
    privileges=[
        Privileges.PARAMS_ACCESS,
        Privileges.PARAMS_EDIT,
        Privileges.AGENT_ACCESS,
        Privileges.AGENT_EDIT,
    ]
)
async def list_harness_catalogue(
    enabled_only: bool = Query(default=False),
) -> list[HarnessCatalogRead]:
    scope = await current_management_scope()
    return await service.list_catalogue(
        enabled_only=enabled_only,
        agent_ids=scope.agent_ids,
    )


@router.post("/catalog", response_model=HarnessCatalogRead, status_code=201)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def create_harness(data: HarnessCatalogCreate) -> HarnessCatalogRead:
    try:
        return await service.create_catalogue_harness(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/catalog/probe", response_model=HarnessProbeResult)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def probe_harness(data: HarnessProbe) -> HarnessProbeResult:
    try:
        return await service.probe_openai_harness(data)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/catalog/{harness_id}", response_model=HarnessCatalogRead)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def read_harness(harness_id: UUID) -> HarnessCatalogRead:
    try:
        scope = await current_management_scope()
        return await service.get_catalogue_harness(
            harness_id,
            agent_ids=scope.agent_ids,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/catalog/{harness_id}", response_model=HarnessCatalogRead)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def update_harness(
    harness_id: UUID,
    data: HarnessCatalogUpdate,
) -> HarnessCatalogRead:
    try:
        if not (await current_management_scope()).is_global:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global Agent management is required",
            )
        return await service.update_catalogue_harness(harness_id, data)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/catalog/{harness_id}", status_code=204)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def delete_harness(harness_id: UUID) -> None:
    try:
        if not (await current_management_scope()).is_global:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Global Agent management is required",
            )
        await service.delete_catalogue_harness(harness_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/agents/{id}", response_model=HarnessRead)
@authorize(
    privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT],
    assertion=AgentOwnerAssertion,
)
async def read_agent_harness(id: int) -> HarnessRead:
    try:
        return await service.get_for_agent(id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/agents/{id}",
    response_model=HarnessRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def install_agent_harness(
    id: int,
    data: HarnessSelectionUpdate,
    background_tasks: BackgroundTasks,
) -> HarnessRead:
    try:
        selected, cleanup = await service.install(id, data)
        if cleanup is not None:
            background_tasks.add_task(service.cleanup_previous_runtime, cleanup)
        return selected
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agents/{id}",
    response_model=HarnessRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def select_internal_harness(
    id: int,
    background_tasks: BackgroundTasks,
) -> HarnessRead:
    try:
        selected, cleanup = await service.select_internal(id)
        if cleanup is not None:
            background_tasks.add_task(service.cleanup_previous_runtime, cleanup)
        return selected
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents/{id}/task-blockers",
    response_model=HarnessTaskBlockers,
)
@authorize(privileges=Privileges.TASK_EDIT, assertion=AgentOwnerAssertion)
async def harness_task_blockers(id: int) -> HarnessTaskBlockers:
    return _task_blockers_read(await get_agent_task_blockers(id))


@router.post(
    "/agents/{id}/task-blockers/terminate-paused",
    response_model=HarnessTaskBlockers,
)
@authorize(privileges=Privileges.TASK_EDIT, assertion=AgentOwnerAssertion)
async def terminate_harness_paused_tasks(id: int) -> HarnessTaskBlockers:
    return _task_blockers_read(await terminate_paused_agent_tasks(id))


async def _selected(id: int):
    agent = await get_agent_record(id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    target = await service.resolve_target(agent)
    if target is None:
        raise HTTPException(
            status_code=409,
            detail="The internal Harness has no external runtime to supervise.",
        )
    return agent, target, get_provider(target.provider_code)


@router.get("/agents/{id}/status", response_model=HarnessRuntimeState)
@authorize(
    privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT],
    assertion=AgentOwnerAssertion,
)
async def harness_status(id: int) -> HarnessRuntimeState:
    agent = await get_agent_record(id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    target = await service.resolve_target(agent)
    if target is None:
        return HarnessRuntimeState(
            status="internal",
            lifecycle_status="internal",
            managed=False,
            capabilities=[],
        )
    provider = get_provider(target.provider_code)
    from .skill_sync import skill_sync_status

    skills_status, skills_error = await skill_sync_status(id)
    capabilities = sorted(await configured_provider_capabilities(target.provider_code))
    if target.status != "ready":
        return HarnessRuntimeState(
            status=target.status,
            lifecycle_status=target.status,
            managed=provider.containerized,
            capabilities=capabilities,
            last_error=target.last_error or skills_error,
            skills_status=skills_status,
        )
    if "status" not in capabilities:
        return HarnessRuntimeState(
            status=target.status,
            lifecycle_status=target.status,
            managed=provider.containerized,
            capabilities=capabilities,
            last_error=target.last_error or skills_error,
            skills_status=skills_status,
        )
    try:
        runtime_status = await provider.status(agent)
    except Exception as exc:
        raise _http_error(exc) from exc
    return HarnessRuntimeState(
        status=runtime_status,
        lifecycle_status=target.status,
        managed=provider.containerized,
        capabilities=capabilities,
        last_error=target.last_error or skills_error,
        skills_status=skills_status,
    )


@router.post(
    "/agents/{id}/actions/{action}",
    response_model=HarnessActionResult,
    status_code=status.HTTP_202_ACCEPTED,
)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def run_harness_action(
    id: int,
    action: HarnessAction,
    background_tasks: BackgroundTasks,
) -> HarnessActionResult:
    agent, target, _provider = await _selected(id)
    if target.status in {"provisioning", "deprovisioning"}:
        raise HTTPException(
            status_code=409,
            detail="A Harness operation is already in progress.",
        )
    if action not in lifecycle_actions(target.status):
        raise HTTPException(
            status_code=409,
            detail="Use restart or update to create the selected Harness runtime.",
        )
    capability = "refresh" if action == "refresh" else action
    if capability not in await configured_provider_capabilities(target.provider_code):
        raise HTTPException(status_code=409, detail=f"Unsupported Harness action: {action}.")
    del agent
    background_tasks.add_task(service.run_action_in_background, id, action)
    return HarnessActionResult(status=f"{action}_queued")


@router.get("/agents/{id}/logs", response_model=HarnessLogs)
@authorize(
    privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT],
    assertion=AgentOwnerAssertion,
)
async def harness_logs(
    id: int,
    lines: int = Query(default=300, ge=1, le=5_000),
) -> HarnessLogs:
    agent, target, provider = await _selected(id)
    if "logs" not in await configured_provider_capabilities(target.provider_code):
        raise HTTPException(status_code=409, detail="This Harness does not expose logs.")
    if target.status != "ready":
        return HarnessLogs(lines=[target.last_error] if target.last_error else [])
    try:
        return HarnessLogs(lines=await provider.logs(agent, lines))
    except Exception as exc:
        raise _http_error(exc) from exc


__all__ = ["router"]
