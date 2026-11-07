"""Private classifications preserve Goal access and audited, non-destructive removal."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.goal import category_service, goal_service
from app.goal.models import Goal, GoalCategory
from app.goal.tests.factories import make_goal
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user.models import User
from core.user.user_service import encrypt_password, user_identity_context


@pytest.mark.asyncio
async def test_private_categories_http_assignment_filtering_and_audit(client, monkeypatch):
    # Both managers are global: category ownership must still apply.
    password = "synthetic-category-password"
    async with get_db_session() as db:
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["GOAL_ACCESS", "GOAL_EDIT", "AGENT_MANAGE_ALL"]
        ))))
        assert len(privileges) == 3
        role = Role(code="synthetic-goal-categories", privileges=privileges)
        users = [User(email=f"goal-category-{index}@example.com", hashed_password=encrypt_password(password), is_active=True) for index in range(3)]
        title = Title(label="Synthetic category manager", gender="N")
        db.add_all([role, title, *users])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        agent = Agent(user_id=users[0].id, title_id=title.id, code="synthetic-goal-category", first_name="Synthetic", last_name="Worker")
        db.add(agent)
        await db.flush()
        goal = await make_goal(title="Synthetic classified objective", description="<p>Retain this objective.</p>", agent_id=agent.id)
        db.add(goal)
        await db.flush()
        goal_id, owner_id = str(goal.id), users[0].id

    headers = []
    for index in range(3):
        client.cookies.clear()
        response = await client.post("/api/auth/login-json", json={"email": f"goal-category-{index}@example.com", "password": password})
        assert response.status_code == 200, response.text
        headers.append({"Authorization": f"Bearer {response.json()['access_token']}", "X-Editorial-Profile-Version": "1"})
    client.cookies.clear()
    path = "/api/goals/categories"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=headers[2])).status_code == 403
    assert (await client.post(path, headers=headers[2], json={"label": "Denied"})).status_code == 403
    for label in ["", "   ", "x" * 201]:
        assert (await client.post(path, headers=headers[0], json={"label": label})).status_code == 422
    response = await client.post(path, headers=headers[0], json={"label": "  Research  "})
    assert response.status_code == 201, response.text
    category = response.json()
    category_id = category["id"]
    assert category["created_by"] == owner_id and category["label"] == "Research"
    assert (await client.get(path, headers=headers[1])).json() == []
    assert (await client.put(f"{path}/{category_id}", headers=headers[1], json={"label": "Stolen"})).status_code == 404
    assert (await client.delete(f"{path}/{category_id}", headers=headers[1])).status_code == 404
    response = await client.put(f"{path}/{category_id}", headers=headers[0], json={"label": "Research projects"})
    assert response.status_code == 200
    assert response.json()["updated_by"] == owner_id

    goal_path = f"/api/goals/{goal_id}"
    original = (await client.get(goal_path, headers=headers[0])).json()
    payload = {"expected_revision": original["revision"], "category_id": category_id}
    assert (await client.put(goal_path, headers=headers[1], json=payload)).status_code == 404
    emitted = AsyncMock()
    monkeypatch.setattr(goal_service.websocket, "emit", emitted)
    response = await client.put(goal_path, headers=headers[0], json=payload)
    assert response.status_code == 200, response.text
    classified = response.json()
    assert classified["category_id"] == category_id
    for call in emitted.await_args_list:
        if call.args[0] == "goal":
            assert "category_id" not in call.args[2]
    assert (await client.get(goal_path, headers=headers[1])).json()["category_id"] is None
    for index, expected in [(0, 1), (1, 0)]:
        result = (await client.get("/api/goals", headers=headers[index], params={"category_id": category_id})).json()
        assert result["total"] == expected
        assert result["summary"]["active"] == expected
    assert (await client.get("/api/goals", headers=headers[0], params={"uncategorized": True})).json()["total"] == 0
    assert (await client.get("/api/goals", headers=headers[1], params={"uncategorized": True})).json()["total"] == 1
    # An unrelated edit does not erase another person's hidden classification.
    response = await client.put(goal_path, headers=headers[1], json={"expected_revision": classified["revision"], "title": "Preserved objective"})
    assert response.status_code == 200, response.text
    assert (await client.get(goal_path, headers=headers[0])).json()["category_id"] == category_id
    assert (await client.delete(f"{path}/{category_id}", headers=headers[0])).status_code == 204
    restored = (await client.get(goal_path, headers=headers[0])).json()
    assert restored["category_id"] is None and restored["title"] == "Preserved objective"
    assert restored["tracking_document_id"] == original["tracking_document_id"]
    assert restored["revision"] > response.json()["revision"]
    assert (await client.get(path, headers=headers[0])).json() == []
    assert (await client.put(goal_path, headers=headers[0], json={"expected_revision": restored["revision"], "category_id": category_id})).status_code == 404
    async with get_db_session() as db:
        archived = await db.scalar(select(GoalCategory).where(GoalCategory.id == category_id).execution_options(include_historized=True))
        assert archived is not None and archived.deleted_by == owner_id and archived.deleted_at is not None


@pytest.mark.asyncio
async def test_goal_create_and_clear_category(db, monkeypatch):
    from app.goal import category_service
    from app.goal.schemas import GoalCategoryWrite, GoalCreate, GoalAgentReferrerInput, GoalUpdate

    owner = User(email="synthetic-category-create@example.com", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic", gender="N")
    db.add_all([owner, title])
    await db.flush()
    agents = [Agent(user_id=owner.id, title_id=title.id, code=f"synthetic-category-create-{index}", first_name="Synthetic", last_name=str(index)) for index in range(2)]
    db.add_all(agents)
    await db.commit()
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    with user_identity_context(owner):
        category = await category_service.create(GoalCategoryWrite(label="Operations"))
        created = await goal_service.create(GoalCreate(title="Create a classified Goal", description="<p>Synthetic objective</p>", agent_id=agents[0].id, referrer=GoalAgentReferrerInput(type="AGENT", agent_id=agents[1].id), category_id=category.id, active=False))
        assert created.category_id == category.id
        cleared = await goal_service.update(created.id, GoalUpdate(expected_revision=created.revision, category_id=None))
        assert cleared is not None and cleared.category_id is None
        persisted = await db.get(Goal, created.id)
        assert persisted is not None and persisted.category_id is None


@pytest.mark.asyncio
async def test_category_order_precedes_agent_order_and_pagination(db, monkeypatch):
    owner = User(email="synthetic-category-sort@example.com", hashed_password="unused", is_active=True)
    outsider = User(email="synthetic-category-sort-other@example.com", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic sorting", gender="N")
    db.add_all([owner, outsider, title])
    await db.flush()
    agents = [Agent(user_id=owner.id, title_id=title.id, code=f"synthetic-sort-{index}", first_name=name, last_name="Example") for index, name in enumerate(["Zora", "Alice"])]
    db.add_all(agents)
    await db.flush()
    # Reverse creation order and case distinguish alphabetical ordering from IDs.
    categories = [GoalCategory(label="Zeta", created_by=owner.id), GoalCategory(label="alpha", created_by=owner.id), GoalCategory(label="AAA private", created_by=outsider.id)]
    db.add_all(categories)
    await db.flush()
    goals = []
    for category_id in [None, categories[0].id, categories[1].id, categories[2].id]:
        for agent in agents:
            goal = await make_goal(title=f"Sorting objective {len(goals)}", description="<p>Synthetic sorting objective.</p>", agent_id=agent.id, category_id=category_id)
            db.add(goal)
            goals.append(goal)
    await db.commit()
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    with user_identity_context(owner):
        assert [category.label for category in await category_service.list_categories()] == ["alpha", "Zeta"]
        for descending in [False, True]:
            # Fetch one item per page: ordering must happen globally in SQL.
            rows = [(await goal_service.list_page(skip=skip, limit=1, sort_by="agent", descending=descending, search="Sorting")).items[0] for skip in range(8)]
            assert [row.category_id for row in rows] == [categories[1].id] * 2 + [categories[0].id] * 2 + [None] * 4
            expected = [agents[0].id, agents[1].id] if descending else [agents[1].id, agents[0].id]
            assert [row.agent_id for row in rows[:4]] == expected * 2
            assert [row.agent_id for row in rows[4:]] == [expected[0]] * 2 + [expected[1]] * 2
