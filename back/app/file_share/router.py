"""API routes exposing file-sharing bridges and configuration parameters."""

from fastapi import APIRouter

from core.authorize import authorize, Privileges

from .bridges import FileShareBridgeInfo, available_bridges

router = APIRouter(prefix="/file-share", tags=["file-share"])


@router.get("/bridges", response_model=list[FileShareBridgeInfo])
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def list_bridges() -> list[FileShareBridgeInfo]:
    """List available file-sharing bridges and required parameters."""
    return available_bridges()
