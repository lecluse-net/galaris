"""
Unified Authorization Service for RBAC.

Provides a polymorphic is_allowed() method supporting:
  - privilege/  → checks if user has a privilege
  - role/       → checks if user has a role
  - route/      → checks if route guard passes
  - resource    → checks resource rules
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional, cast

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import FastAPI

from core.user.models import User
from .assertions import AssertionContext, BaseAssertion
from .guard_provider import GuardProvider, guard_provider
from .logic import check_privilege
from .resource_rules import ResourceRule, RuleProvider


class AuthorizeService:
    """
    Unified authorization service — Python equivalent of PHP's Authorize class.

    Provides polymorphic authorization checks via is_allowed() and
    coordinates GuardProvider, RuleProvider, and assertions.
    """

    SYNTAX_PRIVILEGE = "privilege/"
    SYNTAX_ROUTE = "route/"

    def __init__(
        self,
        guard_provider_instance: Optional[GuardProvider] = None,
        rule_provider: Optional[RuleProvider] = None,
        db: Optional[AsyncSession] = None,
    ):
        # Use the global guard_provider by default to ensure consistency
        # with global_authorization_guard
        self.guard_provider = guard_provider_instance or guard_provider
        self.rule_provider = rule_provider or RuleProvider()
        self.db = db
        self._started = False

    # ── Initialization ───────────────────────────────────────────────

    def start(self, app: FastAPI) -> None:
        """
        Initialize the service at application startup.

        1. Scans all FastAPI routes for @authorize() metadata → GuardProvider
        2. Scans all SQLAlchemy models for @authorize(target="resource") → RuleProvider

        Call this in main.py after all routers are included:
            authorize = AuthorizeService()
            authorize.start(app)
        """
        from .model_scanner import scan_models

        self.guard_provider.scan_app(app)
        scan_models(self.rule_provider)
        self._started = True
        logger.info("AuthorizeService started successfully")

    # ── Polymorphic is_allowed ───────────────────────────────────────

    async def is_allowed(
        self,
        resource: Any,
        privilege: Optional[str] = None,
        *,
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Polymorphic authorization check.

        Dispatches based on resource type:
        - str starting with 'privilege/' → is_allowed_privilege()
        - str starting with 'route/'     → is_allowed_route()
        - object/other                   → is_allowed_resource()

        Mirrors PHP's Authorize::isAllowed().
        """
        if isinstance(resource, str):
            if resource.startswith(self.SYNTAX_PRIVILEGE):
                priv_code = resource[len(self.SYNTAX_PRIVILEGE):]
                return await self.is_allowed_privilege(priv_code, user, db)
            elif resource.startswith(self.SYNTAX_ROUTE):
                route_name = resource[len(self.SYNTAX_ROUTE):]
                return await self.is_allowed_route(route_name, params or {}, user, db)

        # Fallback: resource object → resource rules
        return await self.is_allowed_resource(resource, privilege, user, db)

    # ── Specific Check Methods ───────────────────────────────────────

    async def is_allowed_privilege(
        self,
        privilege: str,
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Check if the user has a specific privilege.

        Delegates to the existing check_privilege() in logic.py.
        """
        if user is None or db is None:
            logger.warning("is_allowed_privilege called without user or db")
            return False
        return await check_privilege(user, privilege, db)

    async def is_allowed_route(
        self,
        route_name: str,
        params: Optional[Dict[str, Any]] = None,
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Check if the user is allowed to access a specific route.

        Resolves the guard via GuardProvider, injects params, and
        evaluates the resulting rule.

        Mirrors PHP's Authorize::isAllowedRoute().
        """
        guard = self.guard_provider.get(route_name)
        if guard is None:
            # No guard for this route → deny by default (like PHP)
            return False

        # Convert guard to rule and inject params
        rule = self.guard_provider.to_rule(route_name)
        if rule is None:
            return False

        # Clone rule and merge in passed params
        rule = copy.copy(rule)
        if params:
            rule.params = {**rule.params, **(params or {})}

        context = {"route_name": route_name}
        return await self.is_allowed_rule(rule, context, user, db)

    async def is_allowed_resource(
        self,
        resource: Any,
        privilege: Optional[str] = None,
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Check if the user is allowed to access a specific resource.

        Resolves rules via RuleProvider based on resource type and privilege.

        Mirrors PHP's Authorize::isAllowedResource().
        """
        if resource is None:
            return False

        # Determine resource type key
        if hasattr(resource, "get_resource_id"):
            resource_key = resource.get_resource_id()
        elif hasattr(resource, "__class__"):
            resource_key = resource.__class__.__name__
        elif isinstance(resource, str):
            resource_key = resource
        else:
            return False

        context: Dict[str, Any] = {"resource": resource}
        if privilege:
            context["privilege"] = privilege
            # If the privilege exists and user doesn't have it, deny early
            if user and db:
                has_priv = await check_privilege(user, privilege, db)
                if not has_priv:
                    return False

        # Get rules for this resource type
        # Try both the resource_key (e.g. "agent/1") and the class name
        rules = self.rule_provider.get(resource_key)
        if not rules and hasattr(resource, "__class__"):
            rules = self.rule_provider.get(resource.__class__.__name__)

        for rule in rules:
            if self._rule_match(rule, privilege):
                if await self.is_allowed_rule(rule, context, user, db):
                    return True

        return False

    # ── Rule Evaluation ──────────────────────────────────────────────

    async def is_allowed_rule(
        self,
        rule: ResourceRule,
        context: Optional[Dict[str, Any]] = None,
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Evaluate a single Rule against the current user.

        Checks in order:
        1. Privileges (if any defined, user must have at least one)
        2. Assertion (if defined, must return True)

        Mirrors PHP's Authorize::isAllowedRule().
        """
        context = context or {}

        # 1. Check privileges
        context_privilege = context.get("privilege")
        known_privilege = True
        if context_privilege and user and db:
            known_privilege = await check_privilege(user, context_privilege, db)

        if known_privilege and rule.privileges:
            privilege_found = False
            for priv_code in rule.privileges:
                if user and db and await self.is_allowed_privilege(priv_code, user, db):
                    privilege_found = True
                    break
            if not privilege_found:
                return False

        # 2. Check assertion
        if rule.assertion:
            assertion = rule.assertion
            assertion_instance: Optional[BaseAssertion] = None

            if isinstance(assertion, type) and issubclass(assertion, BaseAssertion):
                assertion_instance = assertion(authorize_service=self)
            else:
                # Simple callable assertion
                return cast(bool, cast(Callable[..., Any], assertion)(context))

            if assertion_instance:
                # Inject params
                merged_params = {**rule.params}
                assertion_instance.set_params(merged_params)

                # Build AssertionContext
                assertion_context = AssertionContext(
                    user=user,
                    db=db,
                    resource=context.get("resource"),
                    privilege=context.get("privilege"),
                    params=merged_params,
                )
                return await assertion_instance.assert_(assertion_context)

        # If we got through all checks, allow
        return known_privilege

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _rule_match(rule: ResourceRule, privilege: Optional[str]) -> bool:
        """Check if a rule matches the requested privilege."""
        if not privilege:
            return not rule.privileges  # Match rules with no privileges
        return privilege in rule.privileges

    # ── Static Resource Builders (like PHP's static methods) ─────────

    @staticmethod
    def privilege_resource(privilege: str) -> str:
        """Build a privilege resource string."""
        return AuthorizeService.SYNTAX_PRIVILEGE + privilege

    @staticmethod
    def route_resource(route: str) -> str:
        """Build a route resource string."""
        return AuthorizeService.SYNTAX_ROUTE + route


