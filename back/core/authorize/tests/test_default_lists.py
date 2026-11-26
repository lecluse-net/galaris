"""Default categories initialize once; subsequent organization belongs to admins."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from core.authorize.dbadmin import datasets
from core.authorize.default_lists import DEFAULT_PRIVILEGE_LISTS
from core.authorize.models import Assignment, Privilege, PrivilegeList, PrivilegeListDefault, Role, RolePrivilege
from core.database import get_db_session
from core.dbadmin import DbAdminDatasetResult, reconcile_dataset

from core.user import UserModel
from core.user.auth_service import create_access_token


async def actor(codes):
    async with get_db_session() as db:
        user = UserModel(email=f"category-{uuid4()}@example.test", hashed_password="unused", is_active=True)
        grants = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        role = Role(code=f"category-role-{uuid4()}", privileges=grants)
        db.add_all([user, role])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
        token = create_access_token({"sub": user.email, "user_id": user.id, "role_id": role.id})
        return {"Authorization": f"Bearer {token}"}, user.id


def default_dataset():
    return next(item for item in datasets() if item.key == "core.authorize.default_privilege_lists")


async def reset_defaults(db):
    await db.execute(update(Privilege).values(privilege_list_id=None))
    await db.execute(delete(PrivilegeList))
    await db.execute(delete(PrivilegeListDefault))


def test_default_organization_assigns_each_privilege_to_one_category():
    codes = [code for item in DEFAULT_PRIVILEGE_LISTS for code in item.privilege_codes]
    assert len(codes) == len(set(codes))


@pytest.mark.asyncio
async def test_installation_assigns_defaults_and_repeated_sync_preserves_admin_changes(db):
    await reset_defaults(db)
    dataset = default_dataset()
    assert (await reconcile_dataset(db, dataset)).inserted == len(DEFAULT_PRIVILEGE_LISTS)
    categories = {item.display_name: item for item in await db.scalars(select(PrivilegeList))}
    assignments = dict((await db.execute(select(Privilege.code, Privilege.privilege_list_id))).all())
    unassigned = sorted(code for code, category_id in assignments.items() if category_id is None)
    assert unassigned == []
    for default in DEFAULT_PRIVILEGE_LISTS:
        category = categories[default.display_name]
        assert category.translation_key == default.display_name
        assert all(assignments[code] == category.id for code in default.privilege_codes if code in assignments)
    receipts = {item.code: item.initialized_at for item in await db.scalars(select(PrivilegeListDefault))}
    assert all(receipts.values())

    category = categories[DEFAULT_PRIVILEGE_LISTS[0].display_name]
    category.display_name = "Synthetic customized category"
    await db.execute(update(Privilege).where(Privilege.code == "TASK_ACCESS").values(privilege_list_id=category.id))
    await db.execute(update(Privilege).where(Privilege.code == "GOAL_ACCESS").values(privilege_list_id=None))
    await db.flush()
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    assert category.display_name == "Synthetic customized category"
    assert await db.scalar(select(Privilege.privilege_list_id).where(Privilege.code == "TASK_ACCESS")) == category.id
    assert await db.scalar(select(Privilege.privilege_list_id).where(Privilege.code == "GOAL_ACCESS")) is None
    assert {item.code: item.initialized_at for item in await db.scalars(select(PrivilegeListDefault))} == receipts


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_plugins_category", [False, True])
async def test_upgrade_groups_only_plugin_privileges_once(db, existing_plugins_category):
    plugins_key = "authorize.privilegeLists.defaults.plugins"
    await db.execute(delete(PrivilegeList).where(PrivilegeList.display_name == plugins_key))
    await db.execute(delete(PrivilegeListDefault).where(PrivilegeListDefault.code == "plugins"))
    administration_id = await db.scalar(
        select(PrivilegeList.id).where(PrivilegeList.display_name == "authorize.privilegeLists.defaults.administration")
    )
    assert administration_id is not None
    custom = PrivilegeList(display_name="Synthetic custom category")
    existing = PrivilegeList(display_name="Plugins") if existing_plugins_category else None
    db.add(custom)
    if existing is not None:
        db.add(existing)
    await db.flush()
    await db.execute(update(Privilege).where(Privilege.code == "PLUGIN_ACCESS").values(privilege_list_id=administration_id))
    await db.execute(update(Privilege).where(Privilege.code == "PLUGIN_EDIT").values(privilege_list_id=custom.id))
    if existing is not None:
        await db.execute(update(Privilege).where(Privilege.code == "TASK_ACCESS").values(privilege_list_id=existing.id))
    assignments_query = select(Privilege.code, Privilege.privilege_list_id)
    grants_query = select(RolePrivilege.role_id, RolePrivilege.privilege_id)
    before = dict((await db.execute(assignments_query)).all())
    grants_before = set((await db.execute(grants_query)).all())

    dataset = default_dataset()
    assert (await reconcile_dataset(db, dataset)).inserted == 1
    plugins = await db.scalar(select(PrivilegeList).where(PrivilegeList.translation_key == plugins_key))
    assert plugins is not None
    if existing is not None:
        assert plugins.id == existing.id
    assert dict((await db.execute(assignments_query)).all()) == {
        **before,
        "PLUGIN_ACCESS": plugins.id,
        "PLUGIN_EDIT": plugins.id,
    }
    assert set((await db.execute(grants_query)).all()) == grants_before

    await db.execute(update(Privilege).where(Privilege.code == "PLUGIN_ACCESS").values(privilege_list_id=custom.id))
    await db.execute(delete(PrivilegeList).where(PrivilegeList.id == plugins.id))
    assert await reconcile_dataset(db, dataset) == DbAdminDatasetResult()
    assert await db.scalar(select(PrivilegeList.id).where(PrivilegeList.translation_key == plugins_key)) is None
    assignments = dict((await db.execute(assignments_query)).all())
    assert assignments["PLUGIN_ACCESS"] == custom.id
    assert assignments["PLUGIN_EDIT"] is None


@pytest.mark.asyncio
async def test_existing_categories_are_adopted_without_moving_custom_assignments(db):
    await reset_defaults(db)
    default = DEFAULT_PRIVILEGE_LISTS[0]
    existing = PrivilegeList(display_name=default.legacy_name)
    custom = PrivilegeList(display_name="Synthetic custom organization")
    db.add_all([existing, custom])
    await db.flush()
    existing_id = existing.id
    await db.execute(update(Privilege).where(Privilege.code == "PARAMS_ACCESS").values(privilege_list_id=custom.id))
    await db.execute(update(Privilege).where(Privilege.code == "GOAL_ACCESS").values(privilege_list_id=existing_id))
    await reconcile_dataset(db, default_dataset())
    assert existing.id == existing_id
    assert existing.display_name == default.display_name
    assert await db.scalar(select(Privilege.privilege_list_id).where(Privilege.code == "PARAMS_ACCESS")) == custom.id
    assert await db.scalar(select(Privilege.privilege_list_id).where(Privilege.code == "GOAL_ACCESS")) == existing_id
    assert await db.scalar(select(PrivilegeList.display_name).where(PrivilegeList.id == custom.id)) == custom.display_name


@pytest.mark.asyncio
async def test_initialization_failure_rolls_back_categories_assignments_and_receipts(db):
    await reset_defaults(db)
    dataset = default_dataset()

    async def fail_after_initialization(session, result):
        await dataset.after_merge(session, result)
        raise RuntimeError("Synthetic initialization failure")

    with pytest.raises(RuntimeError, match="Synthetic initialization failure"):
        async with db.begin_nested():
            await reconcile_dataset(db, replace(dataset, after_merge=fail_after_initialization))
    assert list(await db.scalars(select(PrivilegeList.id))) == []
    assert list(await db.scalars(select(PrivilegeListDefault.id))) == []
    assert set(await db.scalars(select(Privilege.privilege_list_id))) == {None}
    assert (await reconcile_dataset(db, dataset)).inserted == len(DEFAULT_PRIVILEGE_LISTS)


@pytest.mark.asyncio
async def test_admin_can_delete_a_default_without_recreation_or_reassignment(client):
    reader, _ = await actor(["READ_PRIVILEGE"])
    admin, _ = await actor(["MANAGE_PRIVILEGE"])
    listed = await client.get("/api/authorize/privilege-lists", headers=reader)
    assert listed.status_code == 200
    default = DEFAULT_PRIVILEGE_LISTS[0]
    category = next(item for item in listed.json() if item["display_name"] == default.display_name)
    endpoint = f"/api/authorize/privilege-lists/{category['id']}"
    assert (await client.delete(endpoint, headers=reader)).status_code == 403
    assert (await client.delete(endpoint, headers=admin)).status_code == 204

    async with get_db_session() as db:
        assert await reconcile_dataset(db, default_dataset()) == DbAdminDatasetResult()
        assert await db.scalar(select(PrivilegeList.id).where(PrivilegeList.display_name == default.display_name)) is None
        assert set(await db.scalars(select(Privilege.privilege_list_id).where(Privilege.code.in_(default.privilege_codes)))) == {None}
    assert (await client.delete(endpoint, headers=admin)).status_code == 404

    # Reusing the software's literal key is still a user-created label.
    recreated = await client.post("/api/authorize/privilege-lists", headers=admin, json={"display_name": default.display_name})
    assert recreated.status_code == 201
    assert recreated.json()["translation_key"] is None


@pytest.mark.asyncio
async def test_renaming_a_default_turns_its_label_into_user_text(client):
    admin, _ = await actor(["MANAGE_PRIVILEGE"])
    listed = (await client.get("/api/authorize/privilege-lists", headers=admin)).json()
    category = next(item for item in listed if item["display_name"] == DEFAULT_PRIVILEGE_LISTS[0].display_name)
    endpoint = f"/api/authorize/privilege-lists/{category['id']}"
    unchanged = await client.put(endpoint, headers=admin, json={"display_name": category["display_name"]})
    assert unchanged.status_code == 200
    assert unchanged.json()["translation_key"] == category["display_name"]
    renamed = await client.put(endpoint, headers=admin, json={"display_name": "Synthetic renamed default"})
    assert renamed.status_code == 200
    assert renamed.json()["translation_key"] is None
    async with get_db_session() as db:
        await reconcile_dataset(db, default_dataset())
    updated = (await client.get("/api/authorize/privilege-lists", headers=admin)).json()
    assert next(item for item in updated if item["id"] == category["id"])["display_name"] == "Synthetic renamed default"
