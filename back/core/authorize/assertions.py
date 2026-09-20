"""
Advanced Assertion System for RBAC.

Inspired by unicaen-framework's AbstractAssertion.php.
Provides a rich context for assertions with access to request parameters,
user, database session, and the ability to delegate sub-checks to AuthorizeService.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING, cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.user.models import User

if TYPE_CHECKING:
    from .authorize_service import AuthorizeService


@dataclass
class AssertionContext:
    """
    Rich context passed to assertions during evaluation.

    Contains all necessary information for the assertion to make its decision,
    including request parameters (path, query, body), the current user,
    the database session, and optional resource/privilege information.
    """
    user: Optional[User] = None
    request: Optional[Request] = None
    db: Optional[AsyncSession] = None
    resource: Any = None
    privilege: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=lambda: {})
    """
    params contains merged parameters from multiple sources:
    - Path parameters (e.g. connection_id from /{connection_id})
    - Query parameters (e.g. ?tool_name=talk)
    - Body parameters (JSON or form data, best-effort)
    - __route_name__: the FastAPI route name
    """


class BaseAssertion(ABC):
    """
    Abstract base class for authorization assertions.

    Assertions are executed AFTER the privilege check passes.
    They allow for conditional access control based on request data (e.g. ownership).

    Inspired by unicaen-framework's AbstractAssertion:
    - Supports parameter injection via set_params/get_param.
    - Supports sub-checks via is_allowed() delegation to AuthorizeService.
    - Provides specialized hooks: assert_route(), assert_entity(), assert_other().
    """

    def __init__(self, authorize_service: Optional[AuthorizeService] = None):
        self._authorize: Optional[AuthorizeService] = authorize_service
        self._params: Dict[str, Any] = {}

    # ── Parameter Management ──────────────────────────────────────────

    def set_params(self, params: Dict[str, Any]) -> None:
        """Set all parameters at once (replaces existing)."""
        self._params = params

    def get_param(self, name: str, default: Any = None) -> Any:
        """Get a single parameter by name."""
        return self._params.get(name, default)

    def get_params(self) -> Dict[str, Any]:
        """Get all parameters."""
        return self._params

    # ── Sub-verification Delegation ──────────────────────────────────

    async def is_allowed(self, resource: Any, privilege: Optional[str] = None) -> bool:
        """
        Delegate an authorization check to the parent AuthorizeService.

        Allows assertions to perform sub-checks, e.g.:
            if not await self.is_allowed("privilege/AGENT_EDIT"):
                return False

        This mirrors PHP's AbstractAssertion::isAllowed().
        """
        if self._authorize:
            return await self._authorize.is_allowed(
                resource, privilege,
                user=None,  # will use current context user
            )
        return False

    # ── Main Assert Entry Point ──────────────────────────────────────

    async def assert_(self, context: AssertionContext) -> bool:
        """
        Main entry point for assertion evaluation.

        Dispatches to specialized methods based on context content,
        mirroring PHP's AbstractAssertion::assert().

        Override this method for full control, or override the specialized
        hooks (assert_route, assert_entity, assert_other) for targeted logic.
        """
        if context.resource is not None:
            # Resource context → entity assertion
            return await self.assert_entity(context.resource, context.privilege, context)
        elif context.params.get("__route_name__"):
            # Route context → route assertion
            route_name = context.params["__route_name__"]
            return await self.assert_route(route_name, context.params, context)

        return await self.assert_other(context)

    # ── Specialized Hooks (override in subclasses) ───────────────────

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        """
        Called when the assertion is evaluated in a route/controller context.

        Override in subclasses to implement route-specific logic.
        Default: returns True (allows access).
        """
        return True

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        """
        Called when the assertion is evaluated in a resource/entity context.

        Override in subclasses to implement entity-specific logic (e.g. ownership check).
        Default: returns True (allows access).
        """
        return True

    async def assert_other(self, context: AssertionContext) -> bool:
        """
        Fallback when neither route nor entity context applies.

        Override in subclasses for custom logic.
        Default: returns True (allows access).
        """
        return True

    # ── Helper: Combine multiple boolean results ─────────────────────

    def asserts(self, *assertions: bool | Sequence[bool]) -> bool:
        """
        Combine multiple assertion results with AND logic.

        Usage:
            return self.asserts(
                user.is_active,
                entity.owner_id == user.id,
                await self.is_allowed("privilege/SOME_PRIV"),
            )

        Mirrors PHP's AbstractAssertion::asserts().
        """
        # Compatibility: if a single list is passed, unwrap it
        if len(assertions) == 1 and isinstance(assertions[0], (list, tuple)):
            return all(cast(Sequence[bool], assertions[0]))
        return all(cast(Sequence[bool], assertions))


class EntityAssertion(BaseAssertion):
    """
    Specialized assertion for entity/resource operations.

    Subclass this for assertions that primarily check entity-level access
    (e.g. ownership, team membership).
    """

    async def assert_(self, context: AssertionContext) -> bool:
        """Dispatches to assert_entity if resource is present, else assert_other."""
        if context.resource is not None:
            return await self.assert_entity(context.resource, context.privilege, context)
        return await self.assert_other(context)


class RequireAllPrivilegesAssertion(BaseAssertion):
    """Require every privilege listed in the ``required_privileges`` parameter."""

    async def assert_(self, context: AssertionContext) -> bool:
        from .logic import check_privilege

        required = self.get_param("required_privileges")
        if (
            context.user is None
            or context.db is None
            or not isinstance(required, list)
            or not required
        ):
            return False
        required_items = cast(list[object], required)
        required_codes = [
            code for code in required_items if isinstance(code, str) and code
        ]
        if len(required_codes) != len(required_items):
            return False
        return all(
            [
                await check_privilege(context.user, code, context.db)
                for code in required_codes
            ]
        )


class OwnUserOrPrivilegeAssertion(BaseAssertion):
    """Allow a user's own resource or require a configured fallback privilege."""

    async def assert_route(
        self,
        route_name: str,
        params: Dict[str, Any],
        context: AssertionContext,
    ) -> bool:
        del route_name
        from .logic import check_privilege

        owner_param = self.get_param("owner_param")
        fallback_privilege = self.get_param("fallback_privilege")
        if (
            context.user is None
            or context.db is None
            or not isinstance(owner_param, str)
            or not isinstance(fallback_privilege, str)
        ):
            return False

        raw_owner_id = params.get(owner_param)
        if isinstance(raw_owner_id, bool) or not isinstance(raw_owner_id, (int, str)):
            return False
        try:
            owner_id = int(raw_owner_id)
        except (TypeError, ValueError):
            return False
        if owner_id == context.user.id:
            return True
        return await check_privilege(
            context.user,
            fallback_privilege,
            context.db,
        )


class CompositeAssertion(BaseAssertion):
    """
    Combines multiple assertions with AND (mode='all') or OR (mode='any') logic.

    Usage:
        composite = CompositeAssertion(
            assertions=[OwnerAssertion(), TeamMemberAssertion()],
            mode="any"  # OR: at least one must pass
        )
    """

    def __init__(
        self,
        assertions: Optional[List[BaseAssertion]] = None,
        mode: str = "all",
        authorize_service: Optional[AuthorizeService] = None,
    ):
        super().__init__(authorize_service)
        self._assertions = assertions or []
        self._mode = mode  # "all" (AND) or "any" (OR)

    async def assert_(self, context: AssertionContext) -> bool:
        results = [await a.assert_(context) for a in self._assertions]
        if self._mode == "all":
            return all(results)
        return any(results)

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        return await self.assert_(context)

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        return await self.assert_(context)
