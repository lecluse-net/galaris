from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize.dbadmin import datasets
from core.authorize.models import Privilege, PrivilegeList, Role, RolePrivilege
from core.authorize.privilege_service import PrivilegeService
from core.authorize.update_admin_role import ADMIN_ROLE_DISPLAY_NAME
from core.dbadmin.dataset import reconcile_dataset


def test_bundled_authorization_labels_are_frontend_translation_keys() -> None:
    privileges = PrivilegeService().get_code_privileges()

    assert privileges
    assert ADMIN_ROLE_DISPLAY_NAME == "role.admin"
    assert {
        code: label
        for code, label in privileges.items()
        if label != f"privilege.{code}"
    } == {}


@pytest.mark.asyncio
async def test_retired_privileges_cascade_grants_without_removing_roles_or_lists(db: AsyncSession) -> None:
    group = PrivilegeList(display_name="Synthetic privilege group")
    retired = Privilege(code="SYNTHETIC_RETIRED_PRIVILEGE", privilege_list=group)
    retained = Privilege(code="SYNTHETIC_RETAINED_PRIVILEGE")
    roles = [Role(code=f"synthetic-role-{index}", privileges=[retired, retained]) for index in range(2)]
    db.add_all(roles)
    await db.flush()
    retired_id, retained_id, group_id = retired.id, retained.id, group.id
    role_ids = {role.id for role in roles}
    dataset = next(dataset for dataset in datasets() if dataset.key == "core.authorize.privileges")
    assert isinstance(dataset.rows, tuple)
    next_revision = replace(dataset, rows=(*dataset.rows, {"code": retained.code, "display_name": None}))

    result = await reconcile_dataset(db, next_revision)
    await db.flush()

    assert result.removed == 1
    assert await db.scalar(select(Privilege.id).where(Privilege.id == retired_id)) is None
    assert list(await db.scalars(select(RolePrivilege.role_id).where(RolePrivilege.privilege_id == retired_id))) == []
    assert set(await db.scalars(select(RolePrivilege.role_id).where(RolePrivilege.privilege_id == retained_id))) == role_ids
    assert set(await db.scalars(select(Role.id).where(Role.id.in_(role_ids)))) == role_ids
    assert await db.scalar(select(PrivilegeList.id).where(PrivilegeList.id == group_id)) == group_id
    assert (await reconcile_dataset(db, next_revision)).removed == 0
