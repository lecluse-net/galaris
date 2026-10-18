"""Assignment pages preserve their public data with bounded relationship reads."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from core.authorize import router
from core.authorize.models import Assignment, Role
from core.authorize.schemas import AssignmentWithRole
from core.authorize.models import Privilege
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_assignment_pages_and_user_roles_share_one_read(db):
    users = [UserModel(email=f"assignment-{index}@example.com", hashed_password="unused",
                       display_name=f"Synthetic {index}", is_active=index % 2 == 0,
                       avatar_key=uuid4(), avatar_mime_type="image/png") for index in range(60)]
    roles = [Role(code=f"synthetic-assignment-{index}", display_name=f"Role {index}") for index in range(2)]
    db.add_all([*users, *roles])
    await db.flush()
    assignments = [Assignment(user_id=user.id, role_id=role.id, is_default=role is roles[0])
                   for user in users for role in roles]
    db.add_all(assignments)
    await db.flush()
    for assignment in assignments[-3:]:
        assignment.soft_delete()
    await db.commit()
    expected = {assignment.id: (assignment.user_id, assignment.role_id, assignment.is_default)
                for assignment in assignments[:-3]}
    user_id = users[0].id
    public_user = {"id": user_id, "email": users[0].email, "display_name": users[0].display_name,
                   "is_active": users[0].is_active, "avatar_url": users[0].avatar_url}
    reports = []
    connection = await db.connection()

    async def measure(name, operation):
        db.expunge_all()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        try:
            result = await operation()
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
        reports.append({"scenario": name, "queries": len(statements)})
        return result

    async def user_assignments(selected_user_id):
        return [AssignmentWithRole.model_validate(row)
                for row in await router.get_user_assignments(selected_user_id, db=db)]

    first = await measure("page_50", lambda: router.list_assignments(skip=0, limit=50, db=db))
    assert first.total == 117 and len(first.items) == 50
    seen = set()
    for skip in (0, 50, 100):
        page = await router.list_assignments(skip=skip, limit=50, db=db)
        for item in page.items:
            assert item.id not in seen
            seen.add(item.id)
            assert (item.user_id, item.role_id, item.is_default) == expected[item.id]
            assert item.user.id == item.user_id and item.role.id == item.role_id
    assert seen == set(expected)
    all_items = await measure("page_500", lambda: router.list_assignments(skip=0, limit=500, db=db))
    assert {item.id for item in all_items.items} == set(expected)
    empty = await router.list_assignments(skip=500, limit=50, db=db)
    assert empty.total == 117 and empty.items == []
    own = await measure("user_roles", lambda: user_assignments(user_id))
    assert len(own) == 2
    for item in own:
        assert {key: getattr(item.user, key) for key in public_user} == public_user
        assert "hashed_password" not in item.user.model_dump()
    assert await user_assignments(-1) == []

    destination = Path(__file__).resolve().parents[4] / "artifacts/assignment-read-performance.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reports, indent=2) + "\n")
    assert all(report["queries"] <= budget for report, budget in zip(reports, (2, 2, 1), strict=True)), reports


@pytest.mark.asyncio
async def test_assignment_http_preserves_self_access_and_administrative_permissions(client):
    password = "synthetic-assignment-password"
    async with get_db_session() as db:
        privileges = list((await db.scalars(select(Privilege).where(
            Privilege.code.in_(["READ_ASSIGNMENT", "MANAGE_ASSIGNMENT"]),
        ))).all())
        roles = [Role(code="synthetic-assignment-manager", privileges=privileges),
                 Role(code="synthetic-assignment-local", privileges=[])]
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"assignment-{name}@example.com", hashed_password=password_hash,
                           display_name=f"Synthetic {name}", is_active=True)
                 for name in ("manager", "local")]
        db.add_all([*roles, *users])
        await db.flush()
        for user, role in zip(users, roles, strict=True):
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        manager_id, local_id = users[0].id, users[1].id

    urls = ("/api/authorize/assignments", f"/api/authorize/users/{local_id}/assignments")
    for url in urls:
        assert (await client.get(url)).status_code == 401
    headers = {}
    for name in ("manager", "local"):
        login = await client.post("/api/auth/login-json", json={
            "email": f"assignment-{name}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers[name] = {"Authorization": f"Bearer {login.json()['access_token']}"}

    all_assignments = await client.get(urls[0], headers=headers["manager"], params={"limit": 500})
    assert all_assignments.status_code == 200
    assert all_assignments.json()["total"] == 2
    assert {item["user_id"] for item in all_assignments.json()["items"]} == {manager_id, local_id}
    assert (await client.get(urls[0], headers=headers["local"])).status_code == 403
    own = await client.get(urls[1], headers=headers["local"])
    assert own.status_code == 200
    assert len(own.json()) == 1 and own.json()[0]["user"]["display_name"] == "Synthetic local"
    managed = await client.get(urls[1], headers=headers["manager"])
    assert managed.status_code == 200 and managed.json() == own.json()
    assert (await client.get(f"/api/authorize/users/{manager_id}/assignments", headers=headers["local"])).status_code == 403
