"""
Authorization Decorator for FastAPI routes and SQLAlchemy models.

Provides the unified @authorize() decorator that works for both:
- Routes (target="route"): stores metadata for GuardProvider scanning
- Resources (target="resource"): stores rules on model classes for auto-discovery

IMPORTANT: The actual authorization check is performed by the global
authorization_guard dependency, not by this decorator directly.

Inspired by unicaen-framework's guard and rule configuration system.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type, Union, TypeVar, overload, Literal
from typing_extensions import ParamSpec

from .assertions import BaseAssertion

P = ParamSpec("P")
T = TypeVar("T")
C = TypeVar("C", bound=Type[Any])


def _ensure_http_classification_available(endpoint: Callable[P, T]) -> None:
    if any(
        hasattr(endpoint, attribute)
        for attribute in (
            "_authorize_meta",
            "_public_route_reason",
            "_independent_auth_reason",
        )
    ):
        raise ValueError("An HTTP route can have only one authorization classification")


def public(reason: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Mark an HTTP route as intentionally unauthenticated.

    The reason is mandatory so the small unauthenticated surface remains
    auditable. Routes authenticating a cookie, signature, callback token, or
    machine bearer must use ``@independent_auth`` instead.
    """
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("A public route must document why it bypasses RBAC")

    def decorator(endpoint: Callable[P, T]) -> Callable[P, T]:
        _ensure_http_classification_available(endpoint)
        setattr(endpoint, "_public_route_reason", normalized_reason)
        return endpoint

    return decorator


def independent_auth(reason: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Mark a route whose handler enforces non-RBAC authentication.

    This classification is reserved for capability tokens, signed webhooks,
    rotating cookies, and other service identities that cannot pass through
    the user RBAC guard.
    """
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError(
            "An independently authenticated route must document its mechanism"
        )

    def decorator(endpoint: Callable[P, T]) -> Callable[P, T]:
        _ensure_http_classification_available(endpoint)
        setattr(endpoint, "_independent_auth_reason", normalized_reason)
        return endpoint

    return decorator


@overload
def authorize(
    privileges: Union[str, List[str], None] = None,
    assertion: Optional[Type[BaseAssertion]] = None,
    *,
    target: Literal["route"] = "route",
    params: Optional[Dict[str, Any]] = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


@overload
def authorize(
    privileges: Union[str, List[str], None] = None,
    assertion: Optional[Type[BaseAssertion]] = None,
    *,
    target: Literal["resource"],
    params: Optional[Dict[str, Any]] = None,
) -> Callable[[C], C]: ...


def authorize(
    privileges: Union[str, List[str], None] = None,
    assertion: Optional[Type[BaseAssertion]] = None,
    target: str = "route",
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Unified authorization decorator for FastAPI routes and SQLAlchemy models.

    This decorator is a PURE MARKER - it only attaches metadata to the endpoint
    or class. The actual authorization check is performed by the global
    authorization_guard dependency injected at the FastAPI application level.

    Args:
        privileges: Single privilege code or list of codes (OR logic).
        assertion: Optional BaseAssertion class for contextual checks.
        target: "route" (default) for endpoint protection,
                "resource" for model rule definition.
        params: Optional extra parameters to inject into assertions.

    Usage on routes:
        @router.get("/titles/{id}")
        @authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
        async def read_title(id: int): ...

    Usage on models:
        @authorize(
            privileges=[Privileges.AGENT_EDIT],
            assertion=AgentOwnerAssertion,
            target="resource"
        )
        class Agent(Base): ...

    IMPORTANT: For routes, @authorize() must be placed BELOW @router.get/post/etc:
        @router.get("/path")       # ← First
        @authorize(privileges=...) # ← Second
        async def endpoint(): ...
    """
    # Normalize privileges to list
    if isinstance(privileges, str):
        privileges = [privileges]
    elif privileges is None:
        privileges = []

    if target == "resource":
        return _authorize_resource(privileges, assertion, params)
    else:
        return _authorize_route(privileges, assertion, params)


def _authorize_route(
    privileges: List[str],
    assertion: Optional[Type[BaseAssertion]],
    params: Optional[Dict[str, Any]],
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator implementation for route protection.

    This is a PURE MARKER - it only attaches metadata to the endpoint.
    The actual authorization check is performed by global_authorization_guard.
    """

    def decorator(endpoint: Callable[P, T]) -> Callable[P, T]:
        _ensure_http_classification_available(endpoint)
        # Store metadata for GuardProvider scanning
        # The global_authorization_guard will read this via GuardProvider
        setattr(endpoint, "_authorize_meta", {
            "privileges": privileges,
            "assertion": assertion,
            "params": params or {},
        })
        # Return the original endpoint unchanged - no wrapper!
        return endpoint

    return decorator


def _authorize_resource(
    privileges: List[str],
    assertion: Optional[Type[BaseAssertion]],
    params: Optional[Dict[str, Any]],
) -> Callable[[C], C]:
    """
    Decorator implementation for model/resource rule definition.

    Stores ResourceRule metadata on the class for auto-discovery
    by the model scanner at startup.
    """
    from .resource_rules import ResourceRule

    def decorator(cls: C) -> C:
        # Initialize the rules list if not present
        if not hasattr(cls, "_authorize_rules"):
            cls._authorize_rules = []

        rule = ResourceRule(
            privileges=privileges,
            params=params or {},
            assertion=assertion,
        )
        cls._authorize_rules.append(rule)  # type: ignore[union-attr]

        return cls

    return decorator
