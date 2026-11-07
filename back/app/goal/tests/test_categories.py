"""Private classifications preserve Goal access and audited, non-destructive removal."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.goal import category_service, goal_service
from app.goal.models import Goal, GoalCategory, GoalReferrerType, GoalStatus
from app.goal.tests.factories import make_goal
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user.models import User
from core.user.user_service import encrypt_password, user_identity_context


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(GoalStatus))
async def test_classification_with_unchanged_inactive_messenger_referrer(client, status):
    from app.connection import Connection
    from app.tools import ToolModel

    password = "synthetic-offline-classification-password"
    async with get_db_session() as db:
        rights = list(await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["GOAL_ACCESS", "GOAL_EDIT", "AGENT_MANAGE_ALL"]
        ))))
        role = Role(code="synthetic-offline-goal-editor", privileges=rights)
        owner = User(email="synthetic-offline-goal@example.com",
                     hashed_password=encrypt_password(password), is_active=True)
        title = Title(label="Synthetic offline classification", gender="N")
        tool = ToolModel(code="synthetic-offline-goal-messenger", label="Synthetic messenger")
        db.add_all([role, owner, title, tool])
        await db.flush()
        db.add(Assignment(user_id=owner.id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=owner.id, title_id=title.id, code=f"synthetic-offline-goal-{i}",
                        first_name="Synthetic", last_name=str(i)) for i in range(2)]
        db.add_all(agents)
        await db.flush()
        connections = [Connection(tool_id=tool.id, agent_id=agent.id, active=False) for agent in agents]
        db.add_all(connections)
        await db.flush()
        goal = await make_goal(
            title="Classify an offline Goal", description="<p>Synthetic objective.</p>",
            agent_id=agents[0].id, status=status, cycle_delay_seconds=3600,
            referrer_type=GoalReferrerType.MESSENGER, referrer_connection_id=connections[0].id,
            referrer_user_id="synthetic-human", referrer_display_name="Synthetic human",
            referrer_platform="synthetic-messenger", requester_user_id=owner.id,
        )
        db.add(goal)
        await db.flush()
        goal_id, owner_id = str(goal.id), owner.id
        agent_ids = [agent.id for agent in agents]
        connection_ids = [connection.id for connection in connections]

    login = await client.post("/api/auth/login-json", json={
        "email": "synthetic-offline-goal@example.com", "password": password,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}", "X-Editorial-Profile-Version": "1"}
    created = await client.post("/api/goals/categories", headers=headers, json={"label": "Offline projects"})
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]
    path = f"/api/goals/{goal_id}"
    original = (await client.get(path, headers=headers)).json()
    # The editor sends the existing referrer and execution settings on every save.
    payload = {
        "expected_revision": original["revision"], "category_id": category_id,
        "title": original["title"], "description": original["description"], "agent_id": agent_ids[0],
        "referrer": {"type": "MESSENGER", "connection_id": connection_ids[0],
                     "user_id": "synthetic-human", "display_name": "Synthetic human"},
        "cycle_delay_seconds": 3600, "parent_goal_id": None,
        "schedule_enabled": False, "schedule": [], "referrer_max_reminders": 1,
    }
    response = await client.put(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    classified = (await client.get(path, headers=headers)).json()
    assert classified["category_id"] == category_id
    assert classified["status"] == status.value
    assert classified["requester_user_id"] == owner_id
    assert classified["referrer"] == original["referrer"]
    # Clearing classification works with the same complete editor payload too.
    payload.update(expected_revision=classified["revision"], category_id=None)
    cleared = await client.put(path, headers=headers, json=payload)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["category_id"] is None
    payload["expected_revision"] = cleared.json()["revision"]
    # Identity or owner changes must still validate the selected messaging route.
    for changes in [
        {"referrer": {**payload["referrer"], "user_id": "another-synthetic-human"}},
        {"referrer": {**payload["referrer"], "connection_id": connection_ids[1]}},
        {"agent_id": agent_ids[1]},
    ]:
        rejected = await client.put(path, headers=headers, json={**payload, **changes})
        assert rejected.status_code == 409, rejected.text
    if status == GoalStatus.PAUSED:
        resumed = await client.post(f"{path}/resume", headers=headers, json={"expected_revision": payload["expected_revision"]})
        assert resumed.status_code == 409, resumed.text
        assert "inactive" in resumed.json()["detail"]


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


@pytest.mark.asyncio
async def test_descendants_inherit_root_category_and_stay_in_tree_order(db, monkeypatch):
    owner = User(email="synthetic-goal-branch@example.com", hashed_password="unused", is_active=True)
    outsider = User(email="synthetic-goal-branch-other@example.com", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic branch", gender="N")
    db.add_all([owner, outsider, title])
    await db.flush()
    agents = [Agent(user_id=owner.id, title_id=title.id, code=f"synthetic-branch-{index}", first_name=name, last_name="Example") for index, name in enumerate(["Zora", "Alice", "Aaron"])]
    db.add_all(agents)
    await db.flush()
    alpha = GoalCategory(label="Alpha", created_by=owner.id)
    zeta = GoalCategory(label="Zeta", created_by=owner.id)
    private = GoalCategory(label="Private", created_by=outsider.id)
    db.add_all([alpha, zeta, private])
    await db.flush()

    async def add(label, agent, category, parent=None):
        goal = await make_goal(title=label, description="<p>Synthetic hierarchy.</p>", agent_id=agent.id,
            category_id=category.id if category else None,
            parent_goal_id=parent.id if parent else None,
            cycle_delay_seconds=None if parent else 3600)
        db.add(goal)
        await db.flush()
        return goal

    root = await add("Zeta parent", agents[0], zeta)
    child = await add("Child with own Alpha category", agents[1], alpha, root)
    leaf = await add("Leaf with own private category", agents[2], private, child)
    other_root = await add("Other Zeta parent", agents[2], zeta)
    alpha_root = await add("Alpha parent", agents[1], alpha)
    uncategorized = await add("Uncategorized parent", agents[0], None)
    unclassified_child = await add("Child of uncategorized parent", agents[1], alpha, uncategorized)
    await db.commit()
    monkeypatch.setattr(goal_service, "get_tracking_llm", AsyncMock(return_value=None))
    effective = lambda item: getattr(item, "effective_category_id", item.category_id)
    with user_identity_context(owner):
        page = await goal_service.list_page(category_id=zeta.id, sort_by="agent")
        assert {item.id for item in page.items} == {root.id, child.id, leaf.id, other_root.id}
        assert all(effective(item) == zeta.id for item in page.items)
        assert page.total == page.summary.active == 4
        assert [item.id for item in (await goal_service.list_page(category_id=alpha.id)).items] == [alpha_root.id]
        assert [item.id for item in (await goal_service.list_page(uncategorized=True)).items] == [uncategorized.id, unclassified_child.id]
        assert effective((await goal_service.list_page(search="Leaf")).items[0]) == zeta.id
        for descending in [False, True]:
            rows = [(await goal_service.list_page(skip=skip, limit=1, sort_by="agent", descending=descending)).items[0] for skip in range(7)]
            zeta_order = [root.id, child.id, leaf.id, other_root.id] if descending else [other_root.id, root.id, child.id, leaf.id]
            assert [item.id for item in rows] == [alpha_root.id, *zeta_order, uncategorized.id, unclassified_child.id]
        # Hiding a parent must not reveal its category or use the child's own one.
        restricted = await goal_service.list_page(agent_ids={agents[1].id})
        assert effective(next(item for item in restricted.items if item.id == child.id)) is None
        # A root category edit reclassifies the whole branch without overwriting child data.
        from app.goal.schemas import GoalUpdate
        await goal_service.update(root.id, GoalUpdate(expected_revision=root.revision, category_id=alpha.id))
        assert {item.id for item in (await goal_service.list_page(category_id=alpha.id)).items} == {alpha_root.id, root.id, child.id, leaf.id}
        assert child.category_id == alpha.id and leaf.category_id == private.id
        await goal_service.update(root.id, GoalUpdate(expected_revision=root.revision, category_id=None))
        assert {item.id for item in (await goal_service.list_page(uncategorized=True)).items} == {root.id, child.id, leaf.id, uncategorized.id, unclassified_child.id}
        await goal_service.update(child.id, GoalUpdate(expected_revision=child.revision, parent_goal_id=None, cycle_delay_seconds=3600))
        assert effective(next(item for item in (await goal_service.list_page()).items if item.id == leaf.id)) == alpha.id
    with user_identity_context(outsider):
        assert all(effective(item) is None for item in (await goal_service.list_page()).items)
    # Broken legacy parent links must not make otherwise readable Goals disappear.
    root.parent_goal_id = child.id
    child.parent_goal_id = root.id
    await db.commit()
    with user_identity_context(owner):
        page = await goal_service.list_page()
        assert page.total == 7
        cyclic = [item for item in page.items if item.id in {root.id, child.id, leaf.id}]
        assert len(cyclic) == 3 and all(effective(item) is None for item in cyclic)
