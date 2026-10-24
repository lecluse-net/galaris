"""Preserve legacy capabilities once, without restoring later revocations."""

import pytest
from sqlalchemy import delete, select, update

from core.authorize.models import Privilege, Role, RolePrivilege
from core.authorize.domain_projection import (
    DOMAIN_PROJECTION,
    project_domain_privileges,
    domain_projection_complete,
    needs_domain_projection,
)
from core.dbadmin import SchemaTransitionSet


@pytest.mark.asyncio
async def test_projects_existing_roles_once_and_keeps_new_roles_explicit(db):
    privileges = {row.code: row for row in await db.scalars(select(Privilege))}
    roles = [
        Role(code=f"synthetic-split-{source}", privileges=[privileges[source]])
        for source in DOMAIN_PROJECTION
    ]
    new_role = Role(code="synthetic-explicit-role", privileges=[privileges["MEMORY_EDIT"]])
    db.add_all([*roles, new_role])
    await db.flush()
    role_ids = [role.id for role in roles]
    await db.execute(
        update(Role).where(Role.id.in_(role_ids)).values(domain_privileges_initialized_at=None)
    )
    transitions = SchemaTransitionSet(
        added_columns=frozenset({"roles.domain_privileges_initialized_at"})
    )
    assert needs_domain_projection(transitions)
    assert not needs_domain_projection(SchemaTransitionSet())
    assert not await domain_projection_complete(db, transitions)
    await project_domain_privileges(db, transitions)
    assert await domain_projection_complete(db, transitions)
    for role, (source, targets) in zip(roles, DOMAIN_PROJECTION.items(), strict=True):
        actual = set(
            await db.scalars(
                select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == role.id)
            )
        )
        assert actual == {source, *targets}
    assert set(
        await db.scalars(
            select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == new_role.id)
        )
    ) == {"MEMORY_EDIT"}
    removed = privileges["CONTACT_ACCESS"].id
    await db.execute(
        delete(RolePrivilege).where(
            RolePrivilege.role_id == roles[0].id, RolePrivilege.privilege_id == removed
        )
    )
    await project_domain_privileges(db, transitions)
    assert (
        await db.scalar(
            select(RolePrivilege.role_id).where(
                RolePrivilege.role_id == roles[0].id, RolePrivilege.privilege_id == removed
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_projection_grants_and_marker_roll_back_together(db):
    source = await db.scalar(select(Privilege).where(Privilege.code == "CONNECTION_EDIT"))
    role = Role(code="synthetic-rollback-role", privileges=[source])
    db.add(role)
    await db.flush()
    role_id = role.id
    await db.execute(
        update(Role).where(Role.id == role_id).values(domain_privileges_initialized_at=None)
    )
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        async with db.begin_nested():
            await project_domain_privileges(db, SchemaTransitionSet())
            raise RuntimeError("Synthetic interruption")
    assert (
        await db.scalar(select(Role.domain_privileges_initialized_at).where(Role.id == role_id))
        is None
    )
    assert set(
        await db.scalars(
            select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == role_id)
        )
    ) == {"CONNECTION_EDIT"}
