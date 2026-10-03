"""API routes exposing file-sharing bridges and configuration parameters."""

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from collections.abc import AsyncIterator
import asyncio
from uuid import UUID
from core.database import get_db
from app.agent import current_management_scope
from .indexing import start_index_run, cancel_index_run, index_progress, retry_repairs
from .indexing_contracts import FileIndexRequest, FileIndexProgress, FileIndexPage
from .resource_contracts import ResourceContext

from core.authorize import authorize, Privileges

from .bridges import FileShareBridgeInfo, available_bridges
from . import catalogue_resources

router = APIRouter(prefix="/file-share", tags=["file-share"])


@router.get("/bridges", response_model=list[FileShareBridgeInfo])
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def list_bridges() -> list[FileShareBridgeInfo]:
    """List available file-sharing bridges and required parameters."""
    return available_bridges()


async def _index_access(agent_id: int) -> None:
    if not (await current_management_scope()).allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


@router.get("/items/{item_id}/resources", response_model=list[catalogue_resources.CatalogueResource])
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def read_item_resources(item_id: UUID, agent_id: int) -> list[catalogue_resources.CatalogueResource]:
    await _index_access(agent_id)
    return await catalogue_resources.resources(item_id, agent_id)


@router.get("/items/{item_id}/resources/{entry_id}/thumbnail", response_class=Response)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def read_item_resource_thumbnail(item_id: UUID, entry_id: UUID, agent_id: int) -> Response:
    await _index_access(agent_id)
    try:
        data = await catalogue_resources.thumbnail(item_id, agent_id, entry_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Thumbnail unavailable")
        return Response(data, media_type="image/png", headers={"Cache-Control": "private, no-store"})
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Resource unavailable") from error


@router.get("/items/{item_id}/resources/{entry_id}/content", response_class=StreamingResponse)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def read_item_resource_content(item_id: UUID, entry_id: UUID, agent_id: int, preview: bool = True) -> StreamingResponse:
    await _index_access(agent_id)
    manager = catalogue_resources.content(item_id, agent_id, entry_id, preview=preview)
    try:
        source = await manager.__aenter__()
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Resource unavailable") from error
    async def chunks() -> AsyncIterator[bytes]:
        try:
            with source.path.open("rb") as file:
                while data := await asyncio.to_thread(file.read, 64 * 1024):
                    yield data
        finally:
            await manager.__aexit__(None, None, None)
    return StreamingResponse(chunks(), media_type=source.media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/indexing", response_model=FileIndexPage)
@authorize(privileges=Privileges.MEMORY_ACCESS)
async def read_indexing(agent_id: int, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> FileIndexPage:
    await _index_access(agent_id)
    return await index_progress(agent_id, page, page_size)


@router.post("/indexing", response_model=FileIndexProgress)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def create_indexing(data: FileIndexRequest) -> FileIndexProgress:
    await _index_access(data.agent_id)
    try:
        run = await start_index_run(ResourceContext(agent_id=data.agent_id, runtime="internal"),
            data.root_uri, max_entries=data.max_entries, max_depth=data.max_depth)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await get_db().commit()
    return FileIndexProgress.model_validate(run)


@router.post("/indexing/{run_id}/cancel")
@authorize(privileges=Privileges.MEMORY_EDIT)
async def cancel_indexing(run_id: UUID, agent_id: int) -> dict[str, bool]:
    await _index_access(agent_id)
    if not await cancel_index_run(run_id, agent_id):
        raise HTTPException(status_code=404, detail="Index run not found")
    await get_db().commit()
    return {"cancelled": True}


@router.post("/indexing/repairs/retry")
@authorize(privileges=Privileges.MEMORY_EDIT)
async def retry_index_repairs(agent_id: int) -> dict[str, int]:
    await _index_access(agent_id)
    return {"retried": await retry_repairs(agent_id)}
