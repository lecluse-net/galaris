"""Programmatic DbAdmin data source for RBAC reference data."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.dbadmin import (
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminDatasetResult,
    DbAdminRegistry,
    DbAdminAction,
    DbAdminPhase,
)

from .models import Privilege, PrivilegeListDefault, Role, RolePrivilege
from .default_lists import DEFAULT_PRIVILEGE_LISTS, initialize_default_lists
from .privilege_service import PrivilegeService
from .update_admin_role import ADMIN_ROLE_CODE, ADMIN_ROLE_DISPLAY_NAME
from .domain_projection import (
    needs_domain_projection, project_domain_privileges, domain_projection_complete,
)
from .functional_projection import needs_functional_projection, project_functional_privileges, functional_projection_complete


async def _generate_accessors(
    _session: AsyncSession,
    _result: DbAdminDatasetResult,
) -> None:
    if settings.is_dev:
        service = PrivilegeService()
        service.generate_definitions_files(service.get_code_privileges())


async def _admin_grant_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    role_id = await session.scalar(select(Role.id).where(Role.code == ADMIN_ROLE_CODE))
    if role_id is None:
        raise RuntimeError("DbAdmin could not resolve the administrator role")
    privilege_ids = tuple((await session.scalars(select(Privilege.id))).all())
    return tuple(
        {"role_id": int(role_id), "privilege_id": int(privilege_id)}
        for privilege_id in privilege_ids
    )


def datasets() -> tuple[DbAdminDataset, ...]:
    privileges = PrivilegeService().get_code_privileges()
    return (
        DbAdminDataset(
            key="core.authorize.privileges",
            table=cast(Table, Privilege.__table__),
            natural_key=("code",),
            rows=tuple(
                {"code": code, "display_name": display_name}
                for code, display_name in sorted(privileges.items())
            ),
            update_columns=("display_name",),
            delete_missing=True,
            after_merge=_generate_accessors,
        ),
        DbAdminDataset(
            key="core.authorize.default_privilege_lists",
            table=cast(Table, PrivilegeListDefault.__table__),
            natural_key=("code",),
            rows=tuple({"code": item.code} for item in DEFAULT_PRIVILEGE_LISTS),
            update_columns=(),
            after_merge=initialize_default_lists,
            depends_on=("core.authorize.privileges",),
        ),
        DbAdminDataset(
            key="core.authorize.admin_role",
            table=cast(Table, Role.__table__),
            natural_key=("code",),
            rows=(
                {
                    "code": ADMIN_ROLE_CODE,
                    "display_name": ADMIN_ROLE_DISPLAY_NAME,
                },
            ),
            update_columns=("display_name",),
        ),
        DbAdminDataset(
            key="core.authorize.admin_grants",
            table=cast(Table, RolePrivilege.__table__),
            natural_key=("role_id", "privilege_id"),
            rows=_admin_grant_rows,
            update_columns=(),
            depends_on=(
                "core.authorize.admin_role",
                "core.authorize.privileges",
            ),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="core.authorize", factory=datasets)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
    registry.register_action(DbAdminAction(
        key="core.authorize.split_domain_privileges",
        phase=DbAdminPhase.AFTER_DATASET,
        checksum="explicit-capability-projection",
        predicate=needs_domain_projection,
        handler=project_domain_privileges,
        postcondition=domain_projection_complete,
    ))
    registry.register_action(DbAdminAction(
        key="core.authorize.functional_isolation",
        phase=DbAdminPhase.AFTER_DATASET,
        checksum="functional-read-write-domains",
        predicate=needs_functional_projection,
        handler=project_functional_privileges,
        postcondition=functional_projection_complete,
    ))
