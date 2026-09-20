"""Contextual authorization for mechanism-parameterized Lab routes."""

from __future__ import annotations

from typing import ClassVar

from core.authorize import AssertionContext, BaseAssertion, check_privilege

from .access import LabAccessMode, MECHANISM_PRIVILEGES, privileges_for_mechanism


class _LabMechanismPrivilegeAssertion(BaseAssertion):
    """Require the privilege pair belonging to the requested Lab mechanism."""

    access_mode: ClassVar[LabAccessMode]

    async def assert_(self, context: AssertionContext) -> bool:
        if context.user is None or context.db is None:
            return False

        raw_mechanism = context.params.get("mechanism")
        if not isinstance(raw_mechanism, str):
            return False

        if raw_mechanism not in MECHANISM_PRIVILEGES:
            return False

        return await check_privilege(
            context.user,
            privileges_for_mechanism(raw_mechanism, self.access_mode),
            context.db,
        )


class LabMechanismReadPrivilegeAssertion(_LabMechanismPrivilegeAssertion):
    access_mode = "read"


class LabMechanismEditPrivilegeAssertion(_LabMechanismPrivilegeAssertion):
    access_mode = "edit"


__all__ = [
    "LabMechanismEditPrivilegeAssertion",
    "LabMechanismReadPrivilegeAssertion",
]
