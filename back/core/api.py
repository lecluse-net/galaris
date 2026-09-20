"""
Public FastAPI configuration.

This module configures middleware, rate limiting, and public documentation.
"""

from contextlib import AbstractAsyncContextManager
from collections.abc import Mapping, Sequence
from typing import cast, Callable, Awaitable, Any

from fastapi import Depends, FastAPI, Request, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from core.params import RuntimeTrustedHostMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.responses import JSONResponse, Response, HTMLResponse
from slowapi import _rate_limit_exceeded_handler  # type: ignore
from slowapi.errors import RateLimitExceeded
from starlette.types import ASGIApp, Message, Scope, Receive, Send

from core.util import include_routers
from core.util import generate_filtered_openapi, is_not_internal_path, is_not_internal_tag
from core.user import AuthContextMiddleware
from core.database.middleware import DBSessionMiddleware
from core import settings
from core import runtime
from core.logging import setup_logging
from core.observability import configure_observability, instrument_fastapi
from core.rate_limit import enforce_rate_limit, limiter
from loguru import logger


# Configure telemetry before routing standard and Loguru logs.
configure_observability()
setup_logging()


def _submitted_strings(value: object) -> set[str]:
    """Collect submitted strings solely to redact them from validation messages."""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, Mapping):
        strings: set[str] = set()
        mapping = cast(Mapping[object, object], value)
        for nested in mapping.values():
            strings.update(_submitted_strings(nested))
        return strings
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        strings = set()
        sequence = cast(Sequence[object], value)
        for nested in sequence:
            strings.update(_submitted_strings(nested))
        return strings
    return set()


def sanitize_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep useful validation metadata without echoing submitted values."""
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        message = str(error.get("msg") or "Invalid value")
        for submitted in sorted(
            _submitted_strings(error.get("input")),
            key=len,
            reverse=True,
        ):
            message = message.replace(submitted, "<redacted>")
        sanitized.append({
            "loc": list(cast(Sequence[object], error.get("loc", ()))),
            "msg": message,
            "type": error.get("type"),
        })
    return sanitized


class WSDebugMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # Never emit credentials while diagnosing WebSocket handshakes.
            headers_list = cast(list[tuple[bytes, bytes]], scope.get('headers', []))
            sensitive = {"authorization", "cookie", "x-api-key"}
            headers = {
                key.decode("utf-8"): (
                    "<redacted>" if key.decode("utf-8").lower() in sensitive else value.decode("utf-8")
                )
                for key, value in headers_list
            }
            logger.debug("WebSocket connection path={} headers={}", scope.get("path"), headers)

            async def spy_send(message: Message) -> None:
                if message.get("type") == "websocket.close":
                    logger.debug(
                        "WebSocket closed path={} code={} reason={!r}",
                        scope.get("path"),
                        message.get("code"),
                        message.get("reason"),
                    )
                await send(message)

            try:
                await self.app(scope, receive, spy_send)
            except Exception:
                logger.exception("WebSocket application failure path={}", scope.get("path"))
                raise
        else:
            await self.app(scope, receive, send)


def create_app(lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]]) -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        The configured application with all middleware and routers.
    """
    # Import the global guard lazily to avoid an import cycle.
    from core.authorize import global_authorization_guard

    app = FastAPI(
        title=settings.APP_NAME,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # Schemas are exposed explicitly below.
        dependencies=[Depends(enforce_rate_limit), Depends(global_authorization_guard)],
        lifespan=lifespan
    )
    instrument_fastapi(app)

    if settings.LOG_LEVEL in {"TRACE", "DEBUG"}:
        app.add_middleware(WSDebugMiddleware)

    # Default per-IP rate limit follows the administrable runtime preference.
    app.state.limiter = limiter

    # Adapt the SlowAPI handler to FastAPI's ExceptionHandler type.
    def rate_limit_handler(request: Request, exc: Exception) -> Response:
        return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))

    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    async def validation_error_handler(request: Request, exc: Exception) -> Response:
        validation_error = cast(RequestValidationError, exc)
        errors = sanitize_validation_errors(validation_error.errors())
        logger.warning(
            "Invalid request: {} {} - {}",
            request.method,
            request.url.path,
            errors,
        )
        # FastAPI's default handler serializes Pydantic's ``input`` field. That can echo
        # passwords, tokens, private keys, or complete nested request objects back to clients.
        # Preserve the standard detail/loc/msg/type shape while deliberately omitting input
        # values and validator context.
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    app.add_exception_handler(RequestValidationError, validation_error_handler)

    # Restrict trusted hosts.
    app.add_middleware(RuntimeTrustedHostMiddleware)

    # Add security headers.
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:  # type: ignore[unused-function]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Use a restrictive referrer policy.
        response.headers["Referrer-Policy"] = "same-origin"
        # Content Security Policy (Basic)
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;")
        # Disable sensitive browser sensors.
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), browsing-topics=()"
        return response

    # Authentication context.
    app.add_middleware(AuthContextMiddleware)

    # Middleware for database
    app.add_middleware(DBSessionMiddleware)

    # Frontend CORS configuration.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.APP_HOST],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "Authorization", "Content-Type"],
    )

    

    return app


def generate_public_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate the public OpenAPI schema without internal routes."""
    return generate_filtered_openapi(
        app=app,
        title=f"{settings.APP_NAME} - Public API",
        version="1.0.0",
        description="Public API documentation for frontend developers.",
        path_predicate=is_not_internal_path,
        tag_predicate=is_not_internal_tag,
    )


def setup_public_docs(app: FastAPI):
    """
    Configure public documentation endpoints.
    
    Args:
        app: FastAPI application on which to mount endpoints.
    """
    from core.authorize import public

    # Public schema without internal routes.
    @app.get("/api/openapi.json", include_in_schema=False)
    @public(reason="Public API schema")
    async def get_public_openapi_endpoint() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(content=generate_public_openapi(app))

    # Public Swagger UI without internal routes.
    @app.get("/api/docs", include_in_schema=False)
    @public(reason="Public API documentation")
    async def public_swagger_ui_html() -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title=f"{app.title} - Public API",
            swagger_js_url="/swagger-ui-bundle.js",
            swagger_css_url="/swagger-ui.css",
            swagger_favicon_url="/favicon.png"
        )


def setup_api_routers(app: FastAPI):
    """
    Configure and include public API routers.
    
    Args:
        app: FastAPI application on which to mount routers.
    """
    from core.authorize import public

    # Main API router.
    api_router = APIRouter(prefix="/api")

    # Discover module routers automatically.
    include_routers(api_router)

    # Mount the main router.
    app.include_router(api_router)

    # Health check
    @app.get("/api/health")
    @public(reason="Unauthenticated liveness endpoint")
    async def health_check() -> dict[str, str]:  # type: ignore[unused-function]
        return {"status": "ok"}

    @app.get("/api/health/live")
    @public(reason="Unauthenticated liveness endpoint")
    async def liveness_check() -> dict[str, str]:  # type: ignore[unused-function]
        """Confirm that the ASGI process and event loop can answer requests."""
        return {"status": "ok"}

    @app.get("/api/health/ready")
    @public(reason="Unauthenticated readiness endpoint")
    async def readiness_check() -> JSONResponse:  # type: ignore[unused-function]
        """Report critical runtime and dependency readiness."""
        report = await runtime.runtime_supervisor.readiness_report()
        status_code = 503 if report["status"] == "not_ready" else 200
        return JSONResponse(status_code=status_code, content=report)
