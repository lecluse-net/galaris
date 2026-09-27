"""Administrative availability of the optional Browser preferences."""

import hmac
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.connection.facade import has_any_active_tool_connection
from core.authorize import Privileges, authorize, independent_auth
from core.secrets import browser_executor_token
from .network import NetworkRequest, NetworkDecision, authorize_network

router = APIRouter(prefix="/browser", tags=["browser"])


@router.post("/network/authorize", response_model=NetworkDecision)
@independent_auth(reason="Browser sidecar shared credential; never accepts a user or agent bearer")
async def network_authorization(
    body: NetworkRequest, x_galaris_browser_token: str = Header(default=""),
) -> NetworkDecision:
    if not hmac.compare_digest(x_galaris_browser_token, browser_executor_token()):
        raise HTTPException(401, "Unauthorized")
    try:
        return await authorize_network(body)
    except (ValueError, PermissionError):
        return NetworkDecision(allowed=False, code="invalid_network_policy")


class BrowserStatus(BaseModel):
    enabled: bool


@router.get("/status", response_model=BrowserStatus)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def status() -> BrowserStatus:
    """A configured, active agent connection makes the Tool used by the instance."""
    return BrowserStatus(enabled=await has_any_active_tool_connection("browser"))
