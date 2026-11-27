"""HTTP authentication requirements shared by credential-management routes."""

from fastapi import HTTPException, Request, status

from core.i18n import tr
from .user_service import get_current_user_id, session_family_ctx


async def require_web_session(request: Request) -> None:
    """Require a validated frontend JWT in addition to the route's normal RBAC."""
    user_id = get_current_user_id()
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("user_api.errors.not_authenticated"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if getattr(request.state, "web_session_user_id", None) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await tr("user_api.errors.web_session_required"),
        )


async def require_active_web_session(request: Request) -> None:
    """Require a JWT bound to a browser session already validated by the middleware."""
    await require_web_session(request)
    if session_family_ctx.get() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await tr("user_api.errors.web_session_required"),
        )
