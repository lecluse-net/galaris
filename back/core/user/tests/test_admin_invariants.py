from uuid import uuid4

import pytest
from sqlalchemy import select

from core.authorize import AdministratorConflictError, Assignment, Role, preserve_administrator
from core.user import UserModel, user_service
from core.user.schemas import UserCreate, UserUpdate


@pytest.mark.asyncio
async def test_administrative_creation_keeps_language(db):
    user = await user_service.create(UserCreate(email="language@example.com", password="password-123", language="zh"))
    await db.refresh(user)
    assert user.language == "zh"


@pytest.mark.asyncio
async def test_owned_account_delete_returns_localized_conflict_over_http(client):
    from app.agent.models import Agent, Title
    from core.database import get_db_session

    credentials = {"email": "french-admin@example.com", "password": "password-123"}
    created = await client.post("/api/auth/register", json={**credentials, "language": "fr"})
    assert created.status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    account = await client.post("/api/auth/users", headers=headers, json={
        "email": "resource-owner@example.com", "password": "password-123",
    })
    assert account.status_code == 201
    owner_id = account.json()["id"]
    async with get_db_session() as db:
        title = Title(label="Owned", gender="X")
        db.add(title)
        await db.flush()
        db.add(Agent(user_id=owner_id, title_id=title.id, code="owned-http", first_name="Owned", last_name="Agent"))
    response = await client.delete(f"/api/auth/users/{owner_id}", headers=headers)
    assert response.status_code == 409, response.text
    assert "Réaffectez" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_user_with_owned_agent_has_domain_conflict(db, archived):
    from app.agent.models import Agent, Title

    owner = UserModel(email="owner@example.test", hashed_password="unused")
    title = Title(label="Owner", gender="X")
    db.add_all([owner, title])
    await db.flush()
    agent = Agent(user_id=owner.id, title_id=title.id, code="owned", first_name="Owned", last_name="Agent")
    db.add(agent)
    await db.commit()
    owner_id = owner.id
    if archived:
        agent.soft_delete()
        await db.commit()
    with pytest.raises(user_service.UserConflictError):
        await user_service.delete(owner_id)
    assert await db.get(UserModel, owner_id) is not None


@pytest.mark.asyncio
async def test_last_active_admin_guard_covers_users_and_assignments(db):
    admin_role = (await db.scalars(select(Role).where(Role.code == "admin"))).one()
    users = [UserModel(email=f"admin-{i}@example.test", hashed_password="unused", is_active=True) for i in range(2)]
    db.add_all(users)
    await db.flush()
    assignments = [Assignment(user_id=user.id, role_id=admin_role.id, is_default=True) for user in users]
    db.add_all(assignments)
    await db.commit()
    await user_service.update(users[0].id, UserUpdate(is_active=False))
    with pytest.raises(AdministratorConflictError):
        await user_service.update(users[1].id, UserUpdate(is_active=False))
    with pytest.raises(AdministratorConflictError):
        await user_service.delete(users[1].id)
    with pytest.raises(AdministratorConflictError):
        await preserve_administrator(assignment_id=assignments[1].id)
    # An inactive account does not count as the recovery administrator.
    assert users[1].is_active


@pytest.mark.asyncio
async def test_admin_conflicts_are_explained_over_http(client):
    credentials = {"email": "admin@example.com", "password": "password-123"}
    created = await client.post("/api/auth/register", json=credentials)
    assert created.status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    roles = (await client.get("/api/authorize/roles", headers=headers)).json()
    admin = next(role for role in roles if role["code"] == "admin")
    assignments = (await client.get(f"/api/authorize/users/{created.json()['id']}/assignments", headers=headers)).json()
    paths = ["/api/auth/me", f"/api/auth/users/{created.json()['id']}", f"/api/authorize/roles/{admin['id']}"]
    for path in paths:
        response = await client.delete(path, headers=headers)
        assert response.status_code == 409, response.text
    response = await client.put("/api/auth/me", headers=headers, json={"is_active": False})
    assert response.status_code == 409
    response = await client.put(f"/api/authorize/roles/{admin['id']}", headers=headers, json={"code": "renamed"})
    assert response.status_code == 409
    for assignment in assignments:
        if assignment["role_id"] == admin["id"]:
            response = await client.delete(f"/api/authorize/assignments/{assignment['id']}", headers=headers)
            assert response.status_code == 409


@pytest.mark.asyncio
async def test_user_pagination_and_search_reach_past_500(db):
    db.add_all([UserModel(email=f"person-{i:04}@example.test", hashed_password="unused") for i in range(501)])
    await db.commit()
    assert await user_service.count_users("person-") == 501
    page = await user_service.get_users(skip=500, limit=50, search="person-")
    assert len(page) == 1 and page[0].email == "person-0500@example.test"
    assert await user_service.count_users("0500") == 1
    assert [user.email for user in await user_service.get_users(search="0500")] == ["person-0500@example.test"]


@pytest.mark.asyncio
async def test_privilege_management_requires_authorization_and_preserves_unique_codes(client):
    credentials = {"email": "privilege-admin@example.com", "password": "password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    privilege = {"code": "AUDIT_TEST_PRIVILEGE", "display_name": "Audit privilege"}
    created = await client.post("/api/authorize/privileges", headers=headers, json=privilege)
    assert created.status_code == 201, created.text
    duplicate = await client.post("/api/authorize/privileges", headers=headers, json=privilege)
    assert duplicate.status_code == 400, duplicate.text
    listed = await client.get("/api/authorize/privileges", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json() if row["code"] == privilege["code"]] == [created.json()["id"]]

    ordinary = {"email": "privilege-reader@example.com", "password": "password-123"}
    assert (await client.post("/api/auth/users", headers=headers, json=ordinary)).status_code == 201
    login = await client.post("/api/auth/login-json", json=ordinary)
    limited = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/authorize/privileges", headers=limited)).status_code == 403
    refused = await client.post("/api/authorize/privileges", headers=limited,
                                json={**privilege, "code": "FORBIDDEN_PRIVILEGE"})
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_concurrent_account_and_assignment_removal_keep_one_admin(committed_database):
    import asyncio
    from sqlalchemy import delete, func
    from core.database.database import db_session_ctx

    async with committed_database() as db:
        role = (await db.scalars(select(Role).where(Role.code == "admin"))).one()
        users = [UserModel(email=f"race-{uuid4().hex}@example.com", hashed_password="unused", is_active=True) for _ in range(2)]
        db.add_all(users)
        await db.flush()
        assignments = [Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users]
        db.add_all(assignments)
        await db.commit()
        user_id, assignment_id, role_id = users[0].id, assignments[1].id, role.id

    async def deactivate():
        async with committed_database() as db:
            token = db_session_ctx.set(db)
            try:
                await user_service.update(user_id, UserUpdate(is_active=False))
            finally:
                db_session_ctx.reset(token)

    async def unassign():
        async with committed_database() as db:
            token = db_session_ctx.set(db)
            try:
                await preserve_administrator(assignment_id=assignment_id)
                await db.execute(delete(Assignment).where(Assignment.id == assignment_id))
                await db.commit()
            finally:
                db_session_ctx.reset(token)

    results = await asyncio.gather(deactivate(), unassign(), return_exceptions=True)
    assert sum(isinstance(result, AdministratorConflictError) for result in results) == 1
    assert sum(result is None for result in results) == 1
    async with committed_database() as db:
        count = await db.scalar(select(func.count(Assignment.id)).join(UserModel, UserModel.id == Assignment.user_id).where(
            Assignment.role_id == role_id, UserModel.is_active.is_(True),
        ))
        assert count == 1
