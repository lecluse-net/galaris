from typing import Any, List

from fastapi import APIRouter, Body, HTTPException, Response
from loguru import logger
from pydantic import ValidationError

from core.authorize import authorize, Privileges
from core.i18n import render_prompt, tr
from app.agent import AgentOwnerAssertion
from .assertions import ToolCanEditAssertion, tool_can_edit
from .models import Tool as ToolModel
from .schemas import (
    ConnectionSchema,
    FileShareConfig,
    ListenerConfigPublic,
    MessengerConfig,
    McpConfigPublic,
    TaskConfig,
    ToolMcpCatalogPublic,
    ToolMcpTestRequest,
    ToolMcpTestResponse,
    ToolGlobalParamsResponse,
    ToolGlobalParamsUpdate,
    ToolCreate,
    ToolPublic,
    ToolUpdate,
)
from .secrets import (
    public_connection_schema,
    public_listener_config,
    public_messenger_config,
    public_mcp_config,
)
from .mcp_diagnostics import diagnose_mcp_connection
from . import tool_service

router = APIRouter(prefix="/tools", tags=["tools"])


async def _detail(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"tools.errors.{key}"), **values)


def _to_public(record: ToolModel) -> ToolPublic:
    mcp_config = record.mcp_config
    listener_config = record.listener_config
    messenger_config = record.messenger_config
    return ToolPublic(
        id=record.id,
        code=record.code,
        label=record.label,
        description=record.description or "",
        # Legacy native packages may still contain ``{}`` until the upgrade
        # backfill runs. An empty object is not a configurable MCP server.
        has_mcp=bool(mcp_config),
        has_file_share=record.file_share_config is not None,
        has_messenger=messenger_config is not None,
        has_listener=listener_config is not None,
        can_edit=tool_can_edit(record),
        can_disable=record.can_disable,
        conversation_enabled=bool(record.conversation_enabled),
        mcp_config=(
            McpConfigPublic(**public_mcp_config(mcp_config))
            if mcp_config
            else None
        ),
        file_share_config=FileShareConfig(**record.file_share_config) if record.file_share_config else None,
        messenger_config=(
            MessengerConfig(
                **public_messenger_config(
                    messenger_config,
                    secret_fields=tool_service._messenger_secret_fields(  # pyright: ignore[reportPrivateUsage]
                        str(messenger_config.get("service") or "")
                    ),
                )
            )
            if messenger_config
            else None
        ),
        listener_config=(
            ListenerConfigPublic(**public_listener_config(listener_config))
            if listener_config
            else None
        ),
        connection_schema=(
            ConnectionSchema(
                **public_connection_schema(record.connection_schema)
            )
            if record.connection_schema
            else ConnectionSchema()
        ),
        global_params=tool_service.public_global_params(record),
        task_config=TaskConfig(**record.task_config) if record.task_config else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _is_visible(record: ToolModel) -> bool:
    """Every administrator-created Tool remains visible and configurable."""

    del record
    return True


@router.get("", response_model=List[ToolPublic])
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def list_tools():
    records = await tool_service.get_all_tool_records()
    return [_to_public(record) for record in records if _is_visible(record)]


@router.get("/agents/{agent_id}/mcp-tools", response_model=List[ToolMcpCatalogPublic])
@authorize(
    privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT],
    assertion=AgentOwnerAssertion,
)
async def list_agent_mcp_tools(agent_id: int) -> List[ToolMcpCatalogPublic]:
    from app.tools.mcp_loader import list_agent_mcp_tools as _list_agent_mcp_tools

    rows = await _list_agent_mcp_tools(agent_id)
    return [ToolMcpCatalogPublic(**row) for row in rows]


@router.post("/test-mcp", response_model=ToolMcpTestResponse)
@authorize(privileges=Privileges.TOOL_EDIT, assertion=ToolCanEditAssertion)
async def test_mcp_connection(data: ToolMcpTestRequest) -> ToolMcpTestResponse:
    """Test the submitted MCP configuration without persisting it."""

    existing_config: dict[str, Any] | None = None
    if data.tool_id is not None:
        record = await tool_service.get_tool_record_by_id(data.tool_id)
        if record is None:
            return ToolMcpTestResponse(
                success=False,
                message=await _detail("tool_not_found", tool_id=data.tool_id),
            )
        existing_config = record.mcp_config
    return await diagnose_mcp_connection(
        data,
        existing_config=existing_config,
    )


@router.get("/{tool_id}", response_model=ToolPublic)
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def get_tool(tool_id: int):
    record = await tool_service.get_tool_record_by_id(tool_id)
    if not record or not _is_visible(record):
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    return _to_public(record)


@router.get("/{tool_id}/global-params", response_model=ToolGlobalParamsResponse)
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def get_global_params(tool_id: int) -> ToolGlobalParamsResponse:
    """Return safe global connection values for configurable and integrated Tools."""

    record = await tool_service.get_tool_record_by_id(tool_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    return ToolGlobalParamsResponse(
        tool_id=tool_id,
        params=tool_service.public_global_params(record),
    )


@router.put("/{tool_id}/global-params", response_model=ToolGlobalParamsResponse)
@authorize(privileges=Privileges.TOOL_EDIT)
async def update_global_params(
    tool_id: int,
    data: ToolGlobalParamsUpdate,
) -> ToolGlobalParamsResponse:
    """Update inherited values independently from the read-only Tool definition."""

    try:
        record = await tool_service.update_global_params(tool_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    return ToolGlobalParamsResponse(
        tool_id=tool_id,
        params=tool_service.public_global_params(record),
    )


@router.post("", response_model=ToolPublic, status_code=201)
@authorize(privileges=[Privileges.TOOL_EDIT], assertion=ToolCanEditAssertion)
async def create_tool(data: ToolCreate):
    if await tool_service.has_tool(data.code):
        raise HTTPException(
            status_code=409,
            detail=await _detail("tool_exists_code", code=data.code),
        )
    try:
        record = await tool_service.create_tool(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info(f"Tool created: {record.code}")
    return _to_public(record)


@router.put("/{tool_id}", response_model=ToolPublic)
@authorize(privileges=[Privileges.TOOL_EDIT], assertion=ToolCanEditAssertion)
async def update_tool(tool_id: int, data: ToolUpdate):
    try:
        record = await tool_service.update_tool(tool_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not record:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    logger.info(f"Tool updated: {record.code}")
    return _to_public(record)


@router.patch("/{tool_id}/conversation-access", response_model=ToolPublic)
@authorize(privileges=[Privileges.TOOL_EDIT])
async def update_conversation_access(
    tool_id: int,
    enabled: bool = Body(embed=True),
) -> ToolPublic:
    """Toggle conversation projection for optional Tools, including reserved ones."""

    try:
        record = await tool_service.update_conversation_access(tool_id, enabled=enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    return _to_public(record)


@router.delete("/{tool_id}", status_code=204)
@authorize(privileges=[Privileges.TOOL_EDIT], assertion=ToolCanEditAssertion)
async def delete_tool(tool_id: int):
    try:
        deleted = await tool_service.delete_tool(tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    logger.info(f"Tool {tool_id} deleted")


@router.get("/{tool_id}/export", response_class=Response)
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def export_tool(tool_id: int) -> Response:
    """Export a tool as downloadable YAML."""
    record = await tool_service.get_tool_record_by_id(tool_id)
    if not record or not _is_visible(record):
        raise HTTPException(
            status_code=404,
            detail=await _detail("tool_not_found", tool_id=tool_id),
        )
    content = tool_service.serialize_to_yaml(record)
    filename = f"{record.code}.yaml"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportResponse(ToolPublic):
    created: bool


@router.post("/import", response_model=ImportResponse, status_code=200)
@authorize(privileges=[Privileges.TOOL_EDIT], assertion=ToolCanEditAssertion)
async def import_tool(
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
        record, created = await tool_service.import_from_yaml_string(body, overwrite=overwrite)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=await _detail("invalid_tool_definition"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(f"Tool {'created' if created else 'updated'} via import: {record.code}")
    public = _to_public(record)
    return ImportResponse(created=created, **public.model_dump())
