"""
Guard Provider for RBAC.

Inspired by unicaen-framework's GuardProvider.php.
Manages guards that protect FastAPI routes with privileges and assertions.

Also provides the global_authorization_guard dependency that performs
authorization checks for all routes marked with @authorize().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast

from fastapi import FastAPI, Depends, HTTPException, Request, status
from loguru import logger

from core.database import get_db
from core.i18n import render_prompt, tr
from core.user.models import User
from core.user import user_service

from .assertions import AssertionContext, BaseAssertion
from .logic import check_privilege
from .resource_rules import ResourceRule


@dataclass
class GuardConfig:
    """
    Configuration for a route guard.

    Associates a route name with its authorization requirements.
    """
    route_name: str
    privileges: List[str] = field(default_factory=lambda: [])
    assertion: Optional[Union[Type[BaseAssertion], Callable[..., Any]]] = None
    params: Dict[str, Any] = field(default_factory=lambda: {})
    methods: Optional[List[str]] = None  # e.g. ["GET", "POST"], None = all


class GuardProvider:
    """
    Registry of route guards.

    Inspired by unicaen-framework's GuardProvider.php.
    Guards are indexed by route name for O(1) lookup.
    """

    def __init__(self) -> None:
        self._guards: Dict[str, GuardConfig] = {}

    def has(self, route_name: str) -> bool:
        """Check if a guard exists for a route."""
        return route_name in self._guards

    def add(self, guard: GuardConfig) -> None:
        """Register a guard for a route."""
        self._guards[guard.route_name] = guard

    def get(self, route_name: str) -> Optional[GuardConfig]:
        """Get the guard for a route by name."""
        return self._guards.get(route_name)

    def get_all(self) -> Dict[str, GuardConfig]:
        """Get the entire guard registry."""
        return self._guards

    def remove(self, route_name: str) -> bool:
        """Remove a guard. Returns True if removed."""
        if not self.has(route_name):
            return False
        del self._guards[route_name]
        return True

    def to_rule(self, route_name: str) -> Optional[ResourceRule]:
        """
        Convert a GuardConfig to a ResourceRule for evaluation.

        This allows the AuthorizeService to evaluate guards using
        the same isAllowedRule() logic used for resources.
        """
        guard = self.get(route_name)
        if guard is None:
            return None
        return ResourceRule(
            privileges=guard.privileges,
            params=guard.params,
            assertion=guard.assertion,
        )

    def scan_app(self, app: FastAPI) -> None:
        """
        Scan all routes and require an explicit authorization classification.

        Every HTTP endpoint must use ``@authorize`` for RBAC, ``@public`` for
        an intentionally unauthenticated route, or ``@independent_auth`` when
        the handler verifies a capability or service identity. Missing
        classifications abort application startup.
        """
        from fastapi.routing import APIRoute

        def iter_routes(routes: list[Any]) -> Iterator[APIRoute]:
            """Expand routers lazily included by FastAPI >= 0.139."""
            for candidate in routes:
                if isinstance(candidate, APIRoute):
                    yield candidate
                    continue
                original_router = getattr(candidate, "original_router", None)
                nested = getattr(original_router, "routes", None)
                if isinstance(nested, list):
                    yield from iter_routes(cast(list[Any], nested))

        count = 0
        public_count = 0
        independent_auth_count = 0
        unclassified: list[str] = []
        guarded_route_names: dict[str, tuple[str, GuardConfig]] = {}
        for route in iter_routes(cast(list[Any], app.routes)):
            endpoint = route.endpoint
            meta = getattr(endpoint, "_authorize_meta", None)
            public_reason = getattr(endpoint, "_public_route_reason", None)
            independent_auth_reason = getattr(
                endpoint,
                "_independent_auth_reason",
                None,
            )
            classification_count = sum(
                marker is not None
                for marker in (meta, public_reason, independent_auth_reason)
            )
            if classification_count > 1:
                raise RuntimeError(
                    f"Route {route.path} has conflicting authorization classifications"
                )
            if meta is None:
                if isinstance(public_reason, str) and public_reason:
                    public_count += 1
                    continue
                if (
                    isinstance(independent_auth_reason, str)
                    and independent_auth_reason
                ):
                    independent_auth_count += 1
                    continue
                methods = ",".join(sorted(route.methods or []))
                unclassified.append(f"{methods} {route.path}")
                continue

            route_name = route.name or route.path
            methods = ",".join(sorted(route.methods or []))
            route_description = f"{methods} {route.path}"
            guard = GuardConfig(
                route_name=route_name,
                privileges=meta.get("privileges", []),
                assertion=meta.get("assertion"),
                params=meta.get("params", {}),
                methods=[m.upper() for m in route.methods] if route.methods else None,
            )
            previous = guarded_route_names.get(route_name)
            if previous is not None and previous[1] != guard:
                raise RuntimeError(
                    "Routes sharing an RBAC name must have the same policy; "
                    f"{route_name!r} differs between {previous[0]} and "
                    f"{route_description}"
                )
            guarded_route_names[route_name] = (route_description, guard)
            self.add(guard)
            count += 1

        if unclassified:
            routes = ", ".join(sorted(unclassified))
            raise RuntimeError(
                "Every HTTP route must declare @authorize, @public, or "
                "@independent_auth; "
                f"unclassified routes: {routes}"
            )

        logger.info(
            "GuardProvider: scanned {} RBAC, {} public, and {} independently "
            "authenticated route(s)",
            count,
            public_count,
            independent_auth_count,
        )


# ── Global Authorization Guard ─────────────────────────────────────────

async def _get_current_user_optional(
    current_user: User = Depends(user_service.get_current_user),
) -> Optional[User]:
    """
    Returns the current user or None if not authenticated.
    Used by the global guard to allow unauthenticated requests
    to reach routes that don't require authentication.
    """
    return current_user


async def global_authorization_guard(
    request: Request = None,  # type: ignore[assignment]  # FastAPI requires Request; None is possible for WebSockets.
    current_user: Optional[User] = Depends(_get_current_user_optional),
) -> None:
    """
    Global FastAPI dependency that performs authorization checks.

    This dependency is injected at the FastAPI application level and executes
    for every request. It checks if the current route is protected by an
    @authorize() decorator and performs the necessary privilege and assertion
    checks.

    Args:
        request: The FastAPI Request object (injected by FastAPI)
        current_user: The authenticated user (injected via Depends)
    Raises:
        HTTPException: 401 if not authenticated, 403 if authorization fails
    """

    # WebSocket connections don't have a standard HTTP Request object.
    if request is None:  # pyright: ignore[reportUnnecessaryComparison]
        return

    # Get the current route
    route = request.scope.get("route")
    if not route or not hasattr(route, "name"):
        return  # Not a standard API route, allow

    route_name = route.name or route.path

    endpoint = getattr(route, "endpoint", None)
    if isinstance(getattr(endpoint, "_public_route_reason", None), str):
        return
    if isinstance(getattr(endpoint, "_independent_auth_reason", None), str):
        return

    # Check if this exact endpoint declares RBAC before consulting the registry.
    # This prevents a same-name guarded route from classifying another endpoint.
    if getattr(endpoint, "_authorize_meta", None) is None:
        logger.error(
            "Access denied: route={}, reason=authorization_not_declared",
            route_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await tr("authorize_api.errors.route_not_declared"),
        )

    guard = guard_provider.get(route_name)
    if guard is None:
        logger.error(
            "Access denied: route={}, reason=authorization_guard_missing",
            route_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=await tr("authorize_api.errors.route_not_declared"),
        )

    db = get_db()

    # ── 1. Authentication Check ────────────────────────────────────────
    if current_user is None:
        logger.warning(
            f"Access denied: route={route_name}, reason=not_authenticated"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=await tr("authorize_api.errors.not_authenticated"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not current_user.is_active:
        logger.warning(
            f"Access denied: user={current_user.id}, route={route_name}, reason=inactive_user"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await tr("authorize_api.errors.inactive_user"),
        )

    # ── 2. Privilege Check (OR logic) ────────────────────────────────────
    # Reject unauthorized requests before parsing a potentially large body.
    if guard.privileges:
        is_allowed = await check_privilege(current_user, guard.privileges, db)
        if not is_allowed:
            logger.warning(
                f"Access denied: user={current_user.id}, "
                f"route={route_name}, "
                f"reason=missing_privileges, required={guard.privileges}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=render_prompt(
                    await tr("authorize_api.errors.missing_privilege"),
                    privileges=guard.privileges,
                ),
            )

    # ── 3. Assertion Check ──────────────────────────────────────────────
    if guard.assertion:
        merged_params = dict(guard.params)
        merged_params.update(dict(request.query_params))

        # Assertions may depend on JSON or form values. Parse the body only after
        # the coarse privilege check has succeeded, and only when it is needed.
        try:
            body = await request.json()
            if isinstance(body, dict):
                merged_params.update(cast(Dict[str, Any], body))
        except Exception:
            try:
                form = await request.form()
                merged_params.update(dict(form))
            except Exception as exc:
                logger.debug(
                    "Authorization guard could not parse request body route={} error={}",
                    route_name,
                    type(exc).__name__,
                )

        # Path parameters are authoritative resource identities. Apply them last so
        # a query string or request body can never substitute a different UUID.
        merged_params.update(request.path_params)
        merged_params["__route_name__"] = route_name

        from .authorize_service import AuthorizeService

        authorize_svc = AuthorizeService(db=db)

        # Route guards always use a BaseAssertion class.
        assertion_cls = cast(Type[BaseAssertion], guard.assertion)
        assertion_instance = assertion_cls(authorize_service=authorize_svc)
        assertion_instance.set_params(merged_params)

        context = AssertionContext(
            user=current_user,
            request=request,
            db=db,
            params=merged_params,
        )

        assertion_passed = await assertion_instance.assert_(context)
        if not assertion_passed:
            logger.warning(
                f"Access denied: user={current_user.id}, "
                f"route={route_name}, "
                f"reason=assertion_failed, assertion={assertion_cls.__name__}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=await tr("authorize_api.errors.assertion_denied"),
            )


# Global GuardProvider instance
guard_provider = GuardProvider()
