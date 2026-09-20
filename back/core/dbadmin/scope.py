"""Schema-level intervention scope owned by DbAdmin."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .contracts import DbAdminFatalError


@dataclass(frozen=True, slots=True)
class DbAdminDdlFilters:
    """The exact PostgreSQL schemas DbAdmin may modify.

    Galaris deliberately owns the complete ``public`` schema. Keeping this contract
    at schema level is both safer and easier to audit than maintaining a second list
    of model tables. Every other schema is outside the Atlas target.
    """

    included_schemas: tuple[str, ...] = ("public",)

    def validate(self) -> None:
        if self.included_schemas != ("public",):
            raise DbAdminFatalError(
                "DbAdmin must own exactly the public schema; all other schemas are forbidden"
            )

    @property
    def fingerprint(self) -> str:
        self.validate()
        payload = "\n".join(self.included_schemas).encode()
        return sha256(payload).hexdigest()
