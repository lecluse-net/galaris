"""Administrative availability of the optional Browser preferences."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.connection.facade import has_any_active_tool_connection
from core.authorize import Privileges, authorize

router = APIRouter(prefix="/browser", tags=["browser"])


class BrowserStatus(BaseModel):
    enabled: bool


@router.get("/status", response_model=BrowserStatus)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def status() -> BrowserStatus:
    """A configured, active agent connection makes the Tool used by the instance."""
    return BrowserStatus(enabled=await has_any_active_tool_connection("browser"))
