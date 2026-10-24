"""The functional split preserves existing delegation exactly once."""

import pytest
from sqlalchemy import delete, select, update

from core.authorize.models import Privilege, Role, RolePrivilege
from core.authorize.functional_projection import (
    FUNCTIONAL_PROJECTION, project_functional_privileges,
    functional_projection_complete, needs_functional_projection,
)
from core.dbadmin import SchemaTransitionSet


@pytest.mark.asyncio
async def test_functional_projection_is_transactional_once_and_new_roles_are_explicit(db):
    catalogue = {p.code: p for p in await db.scalars(select(Privilege))}
    legacy = [Role(code=f"functional-{source}", privileges=[catalogue[source]]) for source in FUNCTIONAL_PROJECTION]
    explicit = Role(code="functional-explicit", privileges=[catalogue["PARAMS_EDIT"]])
    db.add_all([*legacy, explicit])
    await db.flush()
    ids = [role.id for role in legacy]
    await db.execute(update(Role).where(Role.id.in_(ids)).values(functional_isolation_initialized_at=None))
    transition = SchemaTransitionSet(added_columns=frozenset({"roles.functional_isolation_initialized_at"}))
    assert needs_functional_projection(transition)
    assert not needs_functional_projection(SchemaTransitionSet())
    assert not await functional_projection_complete(db, transition)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        async with db.begin_nested():
            await project_functional_privileges(db, transition)
            raise RuntimeError("synthetic interruption")
    assert not await functional_projection_complete(db, transition)
    await project_functional_privileges(db, transition)
    assert await functional_projection_complete(db, transition)
    for role, (source, targets) in zip(legacy, FUNCTIONAL_PROJECTION.items(), strict=True):
        actual = set(await db.scalars(select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == role.id)))
        assert actual == {source, *targets}
    actual = set(await db.scalars(select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == explicit.id)))
    assert actual == {"PARAMS_EDIT"}
    removed = catalogue["LANGUAGE_CONFIG_EDIT"].id
    await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id.in_(ids), RolePrivilege.privilege_id == removed))
    await project_functional_privileges(db, transition)
    assert not list(await db.scalars(select(RolePrivilege.role_id).where(RolePrivilege.role_id.in_(ids), RolePrivilege.privilege_id == removed)))


@pytest.mark.asyncio
async def test_both_split_generations_compose_on_a_direct_upgrade(db):
    source = await db.scalar(select(Privilege).where(Privilege.code == "PARAMS_EDIT"))
    role = Role(code="functional-direct-upgrade", privileges=[source])
    db.add(role)
    await db.flush()
    await db.execute(update(Role).where(Role.id == role.id).values(
        domain_privileges_initialized_at=None, functional_isolation_initialized_at=None))
    await project_functional_privileges(db, SchemaTransitionSet())
    codes = set(await db.scalars(select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == role.id)))
    assert {"DREAM_EDIT", "HARNESS_CONFIG_EDIT", "LANGUAGE_CONFIG_EDIT", "LLM_PROFILE_EDIT"} <= codes
    assert not {"DREAM_ACCESS", "MAIL_EDIT", "CALENDAR_EDIT", "AGENT_MANAGE_ALL"} & codes


@pytest.mark.asyncio
async def test_new_split_preserves_revocations_from_the_previous_split(db):
    catalogue = {p.code: p for p in await db.scalars(select(Privilege))}
    role = Role(code="functional-between-upgrades", privileges=[catalogue["PARAMS_ACCESS"], catalogue["PARAMS_EDIT"]])
    db.add(role)
    await db.flush()
    # This role already completed the earlier split, then removed those grants.
    await db.execute(update(Role).where(Role.id == role.id).values(functional_isolation_initialized_at=None))
    await project_functional_privileges(db, SchemaTransitionSet())
    codes = set(await db.scalars(select(Privilege.code).join(RolePrivilege).where(RolePrivilege.role_id == role.id)))
    assert {"LANGUAGE_CONFIG_ACCESS", "LANGUAGE_CONFIG_EDIT", "DREAM_CONFIG_ACCESS"} <= codes
    assert not {"HARNESS_CONFIG_ACCESS", "HARNESS_CONFIG_EDIT", "LLM_PROFILE_ACCESS", "LLM_PROFILE_EDIT", "DREAM_EDIT"} & codes
