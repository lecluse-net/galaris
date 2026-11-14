from typing import Any, List
import asyncio

from fastapi import APIRouter, Body, HTTPException, Response
from loguru import logger
from pydantic import ValidationError

from core.authorize import authorize, Privileges
from core.i18n import render_prompt, tr
from app.agent import AgentOwnerAssertion
from .assertions import ServiceCanEditAssertion
from .models import Service as ServiceModel
from .schemas import (
    ServiceMcpCatalogPublic,
    ServiceMcpTestRequest,
    ServiceMcpTestResponse,
    ServiceGlobalParamsResponse,
    ServiceGlobalParamsUpdate,
    ServiceCreate,
    ServicePublic,
    ServiceUpdate,
)
from .mcp_diagnostics import diagnose_mcp_connection
from . import service
from .deletion import DeletionConflict, ServiceDeletionImpact
from .permission_catalog import AgentPermissionCatalog
from .capabilities import CapabilityDefinition

from .service_catalog import ServiceCatalog, read_catalog, refresh_catalog

router = APIRouter(prefix="/services", tags=["services"])
from .authorization_router import router as authorization_router
router.include_router(authorization_router)
from .runtime_authorization_router import router as runtime_authorization_router
router.include_router(runtime_authorization_router)


@router.get("/catalog")
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def service_catalogue() -> ServiceCatalog:
    return await asyncio.to_thread(read_catalog)


@router.post("/catalog/refresh")
@authorize(privileges=Privileges.SERVICE_EDIT)
async def refresh_service_catalogue() -> ServiceCatalog:
    return await refresh_catalog()


@router.get("/capabilities")
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def list_supported_capabilities() -> list[CapabilityDefinition]:
    from .capabilities import supported_capabilities
    return supported_capabilities()


from .admin_contracts import CandidateRequest, AdministrationError


@router.post("/mcp-candidates", status_code=201)
@authorize(privileges=Privileges.SERVICE_EDIT)
async def prepare_mcp_candidate(data: CandidateRequest) -> dict[str, object]:
    """Human-only secret entry point; the model receives an agent-bound reference."""
    from app.agent import current_management_scope, agent_service
    from .admin_candidates import prepare_candidate

    scope = await current_management_scope()
    if not scope.allows(data.agent_id) or await agent_service.get(data.agent_id) is None:
        raise HTTPException(status_code=404, detail=await _detail("tool_not_found", service_id=data.agent_id))
    try:
        return prepare_candidate(data)
    except (AdministrationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=await _detail("invalid_tool_definition")) from exc


async def _detail(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"services.errors.{key}"), **values)


async def _validation_detail(error: ValueError) -> str:
    from app.file_share import InvalidResourceServiceCodeError

    if isinstance(error, InvalidResourceServiceCodeError):
        return await _detail("invalid_resource_service_code")
    return str(error)


from .projections import to_public as _to_public


def _is_visible(record: ServiceModel) -> bool:
    """Every administrator-created Service remains visible and configurable."""

    del record
    return True


@router.get("", response_model=List[ServicePublic])
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def list_services():
    records = await service.get_all_service_records()
    return [_to_public(record) for record in records if _is_visible(record)]


@router.get("/agents/{agent_id}/mcp-tools", response_model=List[ServiceMcpCatalogPublic])
@authorize(
    privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT],
    assertion=AgentOwnerAssertion,
)
async def list_agent_mcp_tools(agent_id: int) -> List[ServiceMcpCatalogPublic]:
    from app.services.mcp_loader import list_agent_mcp_tools as _list_agent_mcp_tools

    rows = await _list_agent_mcp_tools(agent_id)
    return [ServiceMcpCatalogPublic(**row) for row in rows]


@router.get("/agents/{agent_id}/permissions", response_model=AgentPermissionCatalog)
@authorize(privileges=[Privileges.PERMISSION_ACCESS, Privileges.PERMISSION_DECIDE, Privileges.PERMISSION_REVOKE])
async def read_agent_permission_catalog(agent_id: int, connection_id: int | None = None) -> AgentPermissionCatalog:
    from app.agent import current_management_scope
    from .permission_catalog import agent_permission_catalog
    if not (await current_management_scope()).allows(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        return await agent_permission_catalog(agent_id, connection_id=connection_id)
    except LookupError as exc:
        raise HTTPException(404, "Agent not found") from exc


@router.post("/test-mcp", response_model=ServiceMcpTestResponse)
@authorize(privileges=Privileges.SERVICE_EDIT, assertion=ServiceCanEditAssertion)
async def test_mcp_connection(data: ServiceMcpTestRequest) -> ServiceMcpTestResponse:
    """Test the submitted MCP configuration without persisting it."""

    existing_config: dict[str, Any] | None = None
    if data.service_id is not None:
        record = await service.get_service_record_by_id(data.service_id)
        if record is None:
            return ServiceMcpTestResponse(
                success=False,
                message=await _detail("tool_not_found", service_id=data.service_id),
            )
        existing_config = record.mcp_config
    return await diagnose_mcp_connection(
        data,
        existing_config=existing_config,
    )


@router.get("/{service_id}", response_model=ServicePublic)
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def get_service(service_id: int):
    record = await service.get_service_record_by_id(service_id)
    if not record or not _is_visible(record):
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    return _to_public(record)


@router.get("/{service_id}/global-params", response_model=ServiceGlobalParamsResponse)
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def get_global_params(service_id: int) -> ServiceGlobalParamsResponse:
    """Return safe global connection values for configurable and integrated Services."""

    record = await service.get_service_record_by_id(service_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    return ServiceGlobalParamsResponse(
        service_id=service_id,
        params=service.public_global_params(record),
    )


@router.put("/{service_id}/global-params", response_model=ServiceGlobalParamsResponse)
@authorize(privileges=Privileges.SERVICE_EDIT)
async def update_global_params(
    service_id: int,
    data: ServiceGlobalParamsUpdate,
) -> ServiceGlobalParamsResponse:
    """Update inherited values independently from the read-only Service definition."""

    try:
        record = await service.update_global_params(service_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    return ServiceGlobalParamsResponse(
        service_id=service_id,
        params=service.public_global_params(record),
    )


@router.post("", response_model=ServicePublic, status_code=201)
@authorize(privileges=[Privileges.SERVICE_EDIT], assertion=ServiceCanEditAssertion)
async def create_service(data: ServiceCreate):
    if await service.has_service(data.code):
        raise HTTPException(
            status_code=409,
            detail=await _detail("tool_exists_code", code=data.code),
        )
    try:
        record = await service.create_service(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=await _validation_detail(exc)) from exc
    logger.info(f"Service created: {record.code}")
    return _to_public(record)


@router.put("/{service_id}", response_model=ServicePublic)
@authorize(privileges=[Privileges.SERVICE_EDIT], assertion=ServiceCanEditAssertion)
async def update_service(service_id: int, data: ServiceUpdate):
    try:
        record = await service.update_service(service_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=await _validation_detail(exc)) from exc
    if not record:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    logger.info(f"Service updated: {record.code}")
    return _to_public(record)


@router.patch("/{service_id}/conversation-access", response_model=ServicePublic)
@authorize(privileges=[Privileges.SERVICE_EDIT])
async def update_conversation_access(
    service_id: int,
    enabled: bool = Body(embed=True),
) -> ServicePublic:
    """Toggle conversation projection for optional Services, including reserved ones."""

    try:
        record = await service.update_conversation_access(service_id, enabled=enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    return _to_public(record)


@router.get("/{service_id}/deletion-impact", response_model=ServiceDeletionImpact)
@authorize(privileges=[Privileges.SERVICE_EDIT], assertion=ServiceCanEditAssertion)
async def service_deletion_impact(service_id: int) -> ServiceDeletionImpact:
    try:
        impact = await service.deletion_impact(service_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if impact is None:
        raise HTTPException(status_code=404, detail=await _detail("tool_not_found", service_id=service_id))
    return impact


@router.delete("/{service_id}", status_code=204)
@authorize(privileges=[Privileges.SERVICE_EDIT], assertion=ServiceCanEditAssertion)
async def delete_service(service_id: int, cascade: bool = False, expected_version: str | None = None):
    try:
        deleted = await service.delete_service(service_id, cascade=cascade, expected_version=expected_version)
    except DeletionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    logger.info(f"Service {service_id} deleted")


@router.get("/{service_id}/export", response_class=Response)
@authorize(privileges=[Privileges.SERVICE_ACCESS, Privileges.SERVICE_EDIT])
async def export_service(service_id: int) -> Response:
    """Export a service as downloadable YAML."""
    record = await service.get_service_record_by_id(service_id)
    if not record or not _is_visible(record):
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", service_id=service_id),
        )
    content = service.serialize_to_yaml(record)
    filename = f"{record.code}.yaml"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportResponse(ServicePublic):
    created: bool


@router.post("/import", response_model=ImportResponse, status_code=200)
@authorize(privileges=[Privileges.SERVICE_EDIT], assertion=ServiceCanEditAssertion)
async def import_service(
    overwrite: bool = False,
    body: str = Body(..., media_type="text/plain"),
) -> ImportResponse:
    """
    Import a tool from YAML.

    - 200 + created=True: a new tool was created.
    - 200 + created=False: an existing tool was replaced with overwrite=true.
    - 409: the tool exists; retry with overwrite=true.
    """
    try:
        record, created = await service.import_from_yaml_string(body, overwrite=overwrite)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=await _detail("invalid_tool_definition"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=await _validation_detail(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(f"Service {'created' if created else 'updated'} via import: {record.code}")
    public = _to_public(record)
    return ImportResponse(created=created, **public.model_dump())
