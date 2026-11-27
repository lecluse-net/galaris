from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select

from core.authorize import AdministratorConflictError, Assignment, Role, preserve_administrator
from core.user import UserModel, user_service
from core.user.schemas import UserCreate, UserUpdate


@pytest.mark.asyncio
async def test_administrative_creation_keeps_language(db):
    user = await user_service.create(UserCreate(email="language@example.com", password="Northern-maple-37", language="zh"))
    await db.refresh(user)
    assert user.language == "zh"


@pytest.mark.asyncio
async def test_admin_creates_account_with_roles_and_teams_and_shares_the_profile_default(client):
    from core.authorize import Privilege
    from core.database import get_db_session
    from core.team import TeamModel

    async def login(credentials):
        client.cookies.clear()
        response = await client.post("/api/auth/login-json", json=credentials)
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}, jwt.decode(token, options={"verify_signature": False})

    password = "synthetic-user-password"
    admin_credentials = {"email": "membership-admin@example.com", "password": password}
    assert (await client.post("/api/auth/register", json=admin_credentials)).status_code == 201
    admin, _ = await login(admin_credentials)
    async with get_db_session() as db:
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(["CREATE_USER", "TEAM_ACCESS"]))))
        reader_privileges = list(await db.scalars(select(Privilege).where(
            Privilege.code.in_(["READ_USER", "READ_ASSIGNMENT"]),
        )))
        creator_role = Role(code="synthetic-account-creator", privileges=privileges)
        first_role = Role(code="synthetic-reader", privileges=reader_privileges)
        second_role = Role(code="synthetic-editor")
        first_team, second_team = TeamModel(name="Research"), TeamModel(name="Support")
        db.add_all([creator_role, first_role, second_role, first_team, second_team])
        await db.flush()
        creator_role_id = creator_role.id
        role_ids = [first_role.id, second_role.id]
        team_ids = [first_team.id, second_team.id]

    users = "/api/auth/users"
    creator_credentials = {"email": "membership-creator@example.com", "password": password}
    assert (await client.post(users, headers=admin, json={
        **creator_credentials, "role_ids": [creator_role_id],
    })).status_code == 201
    creator, _ = await login(creator_credentials)
    credentials = {"email": "membership-user@example.com", "password": password}
    role_data = {"role_ids": role_ids, "default_role_id": role_ids[1]}
    assert (await client.post(users, headers=creator, json={**credentials, **role_data})).status_code == 403
    assert (await client.post(users, headers=creator, json={**credentials, "team_ids": team_ids})).status_code == 403

    # A missing team after a valid one must roll back the account and earlier memberships.
    invalid = await client.post(users, headers=admin, json={**credentials, **role_data, "team_ids": [team_ids[0], 999999]})
    assert invalid.status_code == 404, invalid.text
    created = await client.post(users, headers=admin, json={
        **credentials, **role_data, "team_ids": team_ids, "managed_team_ids": [team_ids[0]],
    })
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    teams = await client.get("/api/teams", headers=admin, params={"user_id": user_id})
    assert teams.status_code == 200, teams.text
    assert {team["id"] for team in teams.json()} == set(team_ids)
    assert [team["id"] for team in teams.json() if team["manager_user_id"] == user_id] == [team_ids[0]]
    assignments_url = f"/api/authorize/users/{user_id}/assignments"
    assignments = {entry["role_id"]: entry for entry in (await client.get(assignments_url, headers=admin)).json()}
    assert set(assignments) == set(role_ids)
    assert [role for role, item in assignments.items() if item["is_default"]] == [role_ids[1]]

    async def listed_user(headers, *, include_access=True, email=credentials["email"]):
        response = await client.get(users, headers=headers, params={
            "search": email, "limit": 1, "include_access": include_access,
        })
        assert response.status_code == 200, response.text
        assert response.headers["X-Total-Count"] == "1"
        entry, = response.json()
        assert entry["email"] == email
        return entry

    listed = await listed_user(admin)
    assert {role["id"] for role in listed["assignments"]} == set(role_ids)
    assert {team["id"] for team in listed["teams"]} == set(team_ids)
    basic = await listed_user(admin, include_access=False)
    assert basic == {key: value for key, value in listed.items() if key not in {"teams", "assignments"}}
    team_reader = await listed_user(creator)
    assert team_reader["teams"] == listed["teams"]
    assert "assignments" not in team_reader
    assert (await listed_user(creator, email=creator_credentials["email"]))["teams"] == []

    second_account = await client.post(users, headers=admin, json={
        "email": "membership-inactive@example.com", "password": password,
        "role_ids": [role_ids[0]], "team_ids": [team_ids[0]], "is_active": False,
    })
    assert second_account.status_code == 201, second_account.text
    inactive_id = second_account.json()["id"]
    filters = {"search": "membership-", "role_id": role_ids[0], "team_id": team_ids[0], "limit": 1}
    paginated = await client.get(users, headers=admin, params={**filters, "skip": 1})
    assert paginated.status_code == 200, paginated.text
    assert paginated.headers["X-Total-Count"] == "2"
    assert [item["id"] for item in paginated.json()] == [inactive_id]
    for is_active, expected_id in [(True, user_id), (False, inactive_id)]:
        filtered = await client.get(users, headers=admin, params={**filters, "is_active": str(is_active).lower()})
        assert filtered.status_code == 200, filtered.text
        assert filtered.headers["X-Total-Count"] == "1"
        assert [item["id"] for item in filtered.json()] == [expected_id]
    assert (await client.get(users, headers=creator, params={"role_id": role_ids[0]})).status_code == 403

    def default_url(role_id):
        return f"/api/authorize/assignments/{assignments[role_id]['id']}/default"

    assert (await client.put(default_url(role_ids[0]), headers=creator)).status_code == 403
    changed = await client.put(default_url(role_ids[0]), headers=admin)
    assert changed.status_code == 200, changed.text
    owner, claims = await login(credentials)
    assert claims["role_id"] == role_ids[0]
    assignment_reader = await listed_user(owner)
    assert assignment_reader["assignments"] == listed["assignments"]
    assert "teams" not in assignment_reader
    assert (await client.get(users, headers=owner, params={"team_id": team_ids[0]})).status_code == 403
    profile = await client.get(assignments_url, headers=owner)
    assert [entry["role_id"] for entry in profile.json() if entry["is_default"]] == [role_ids[0]]
    assert (await client.put(default_url(role_ids[1]), headers=owner)).status_code == 200
    profile = await client.get(assignments_url, headers=owner)
    assert [entry["role_id"] for entry in profile.json() if entry["is_default"]] == [role_ids[1]]


@pytest.mark.asyncio
async def test_owned_account_delete_returns_localized_conflict_over_http(client):
    from app.agent.models import Agent, Title
    from core.database import get_db_session

    credentials = {"email": "french-admin@example.com", "password": "Northern-maple-37"}
    created = await client.post("/api/auth/register", json={**credentials, "language": "fr"})
    assert created.status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    account = await client.post("/api/auth/users", headers=headers, json={
        "email": "resource-owner@example.com", "password": "Northern-maple-37",
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
    credentials = {"email": "admin@example.com", "password": "Northern-maple-37"}
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
    credentials = {"email": "privilege-admin@example.com", "password": "Northern-maple-37"}
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

    ordinary = {"email": "privilege-reader@example.com", "password": "Northern-maple-37"}
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
