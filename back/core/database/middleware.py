"""
FastAPI middleware for database context management.

The middleware injects a database session into the asyncio context for the
duration of an HTTP request, allowing ``get_db()`` without plumbing a session
through every call.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import Scope, Receive, Send
from .database import AsyncSessionLocal
from .database import db_session_ctx


def _skip_db_session(scope: Scope) -> bool:
    """Avoid implicit database sessions on long-lived channels."""
    path = str(scope.get("path") or "")
    return path.startswith(("/socket.io/", "/api/mcp/"))


class DBSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Intercept each inbound HTTP request.
        """
        # Create one session for the request lifecycle.
        async with AsyncSessionLocal() as session:
            # 2. Attach the session to the current context.
            token = db_session_ctx.set(session)
            try:
                # Delegate route execution to FastAPI.
                response = await call_next(request)
                return response
            except Exception as e:
                # Roll back any uncommitted transaction after a failure.
                await session.rollback()
                raise e
            finally:
                # 5. Always clear the ContextVar.
                db_session_ctx.reset(token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Override ``__call__`` to intercept WebSockets as well (``scope['type'] == 'websocket'``).
        BaseHTTPMiddleware handles only HTTP by default.
        """
        if _skip_db_session(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # Keep one database session for the WebSocket connection lifetime.
            async with AsyncSessionLocal() as session:
                token = db_session_ctx.set(session)
                try:
                    await self.app(scope, receive, send)
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    db_session_ctx.reset(token)
        else:
            # HTTP requests use BaseHTTPMiddleware's default behavior.
            await super().__call__(scope, receive, send)
