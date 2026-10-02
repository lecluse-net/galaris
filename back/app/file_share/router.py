"""API routes exposing file-sharing bridges and configuration parameters."""

from fastapi import APIRouter, HTTPException, Query
from uuid import UUID
from core.database import get_db
from app.agent import current_management_scope
from .indexing import start_index_run, cancel_index_run, index_progress, retry_repairs
from .indexing_contracts import FileIndexRequest, FileIndexProgress, FileIndexPage
from .resource_contracts import ResourceContext

from core.authorize import authorize, Privileges

from .bridges import FileShareBridgeInfo, available_bridges

router = APIRouter(prefix="/file-share", tags=["file-share"])


@router.get("/bridges", response_model=list[FileShareBridgeInfo])
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def list_bridges() -> list[FileShareBridgeInfo]:
    """List available file-sharing bridges and required parameters."""
    return available_bridges()


async def _index_access(agent_id: int) -> None:
    if not (await current_management_scope()).allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


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
