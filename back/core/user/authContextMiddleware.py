from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from jose import jwt, JWTError
from loguru import logger
from core import settings
from core.secrets import auth_secret_key

from contextvars import Token
from typing import Optional
from .models import User
from core.authorize import role_id_ctx, assignment_id_ctx


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token: Optional[str] = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        user_id: Optional[int] = None
        role_id: Optional[int] = None
        assignment_id: Optional[int] = None
        raw_token: Optional[str] = None
        session_family: str | None = None

        # Agent MCP endpoints own their bearer-capability authentication and
        # deliberately run without the request-scoped database middleware.
        # Treating their ``mcp_`` token as a user token would therefore perform
        # an impossible contextual lookup before the endpoint can authenticate it.
        if token and not request.url.path.startswith("/api/mcp/"):
            try:
                payload = jwt.decode(token, auth_secret_key(), algorithms=[settings.ALGORITHM])
                user_id = payload.get("user_id")
                role_id = payload.get("role_id")
                assignment_id = payload.get("assignment_id")
                from .auth_service import AuthenticationError, validate_access_claims
                from .user_service import get_user_by_id

                user = await get_user_by_id(user_id) if isinstance(user_id, int) else None
                if user is None or not user.is_active:
                    user_id = None
                else:
                    try:
                        await validate_access_claims(payload, user)
                        session_family = payload.get("session_family")
                    except AuthenticationError:
                        user_id = None
            except JWTError:
                # A non-JWT token may still be a database-backed UserToken.
                user_id = await self._resolve_user_token(token)
                if user_id:
                    raw_token = token

        # Use the shared user_service ContextVar directly. The underscore remains
        # conventional even though middleware and service intentionally share it.
        from .user_service import _user_id_ctx as uid_ctx, _cached_user as cached_ctx, _raw_token_ctx as rawtok_ctx  # pyright: ignore[reportPrivateUsage]
        user_token: Token[Optional[int]] = uid_ctx.set(user_id)
        # Reset the user cache for every request.
        cached_token: Token[Optional[User]] = cached_ctx.set(None)
        role_ctx: Token[Optional[int]] = role_id_ctx.set(role_id)
        assignment_ctx: Token[Optional[int]] = assignment_id_ctx.set(assignment_id)
        raw_token_ctx: Token[Optional[str]] = rawtok_ctx.set(raw_token)
        from .user_service import session_family_ctx
        family_ctx = session_family_ctx.set(session_family)

        try:
            response = await call_next(request)
            return response
        finally:
            uid_ctx.reset(user_token)
            cached_ctx.reset(cached_token)
            role_id_ctx.reset(role_ctx)
            assignment_id_ctx.reset(assignment_ctx)
            rawtok_ctx.reset(raw_token_ctx)
            session_family_ctx.reset(family_ctx)

    async def _resolve_user_token(self, token_value: str) -> Optional[int]:
        """
        Resolve a valid, enabled UserToken to its user ID.
        """
        try:
            from .token_service import get_token_by_value
            from .user_service import get_user_by_id
            user_token = await get_token_by_value(token_value)
            if user_token and user_token.enabled:
                # Verify that the user exists and is active.
                user = await get_user_by_id(user_token.user_id)
                if user and user.is_active:
                    return user.id
        except Exception:
            logger.exception("User-token resolution failed")
        return None
