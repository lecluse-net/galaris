"""Shared HTTP rate limiter configured once for FastAPI and route decorators."""

from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

from starlette.requests import HTTPConnection, Request

from slowapi import Limiter  # type: ignore
from slowapi.util import get_remote_address
from core.params import runtime_settings

P = ParamSpec("P")
R = TypeVar("R")


def default_rate_limit() -> str:
    """Read the validated in-memory preference for every incoming request."""
    return f"{runtime_settings.HTTP_RATE_LIMIT_PER_MINUTE}/minute"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[default_rate_limit],
)


async def enforce_rate_limit(connection: HTTPConnection) -> None:
    """Check the resolved endpoint before authorization and body validation.

    FastAPI's lazy included routers are invisible to SlowAPI's middleware route
    lookup. A global dependency sees the actual endpoint, including nested routers.
    Keep the upstream private adapter here and cover it with enabled HTTP tests.
    """
    if connection.scope["type"] != "http" or not limiter.enabled:
        return
    request = Request(connection.scope)
    endpoint = cast(Callable[..., Any], connection.scope["endpoint"])
    check = cast(
        Callable[[Request, Callable[..., Any], bool], None],
        limiter._check_request_limit,  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
    )
    check(request, endpoint, False)
    # Explicit decorators must not consume the same request a second time.
    request.state._rate_limiting_complete = True


def rate_limit(limit_value: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Expose SlowAPI's dynamically typed decorator behind a strict boundary."""

    decorator = cast(
        Callable[[Callable[P, R]], Callable[P, R]],
        limiter.limit(limit_value),  # pyright: ignore[reportUnknownMemberType]
    )
    return decorator


__all__ = ["enforce_rate_limit", "limiter", "rate_limit"]
