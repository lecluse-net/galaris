from __future__ import annotations

import pytest

from core.dbadmin import DbAdminDdlFilters, DbAdminFatalError


def test_scope_owns_exactly_public() -> None:
    scope = DbAdminDdlFilters()

    scope.validate()

    assert scope.included_schemas == ("public",)
    assert len(scope.fingerprint) == 64


@pytest.mark.parametrize(
    "schemas",
    [(), ("app",), ("public", "vectors"), ("*",)],
)
def test_scope_rejects_every_other_configuration(schemas: tuple[str, ...]) -> None:
    with pytest.raises(DbAdminFatalError):
        DbAdminDdlFilters(included_schemas=schemas).validate()
