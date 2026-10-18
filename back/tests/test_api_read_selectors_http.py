"""Selectors keep their HTTP contracts, scopes and live authorization checks."""

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.agent.models import Title
from app.lab.models import LabEvaluationDataset, LabEvaluationRun
from app.task import Task, TaskStatus
from app.topic import Topic
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.team.models import Team, TeamUser
from core.user import UserModel
from core.user.user_service import encrypt_password
from tests.test_api_read_selectors import contact


@pytest.mark.asyncio
async def test_selector_routes_keep_read_permissions_scopes_pagination_and_reopening(client):
    password = "synthetic-selectors-password"
    async with get_db_session() as db:
        codes = ["TEAM_ACCESS", "DISPATCHER_EVALUATION_ACCESS", "EVALUATION_ACCESS",
                 "MEMORY_EXTRACTION_EVALUATION_ACCESS", "TOPIC_ACCESS"]
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        assert len(privileges) == len(codes)
        role = Role(code="synthetic-selectors-reader", privileges=privileges)
        hashed_password = encrypt_password(password)
        users = [UserModel(email=f"synthetic-selector-http-{index}@example.com", hashed_password=hashed_password,
                           is_active=True) for index in range(3)]
        title, team = Title(label="Synthetic selector HTTP", gender="N"), Team(name="Synthetic selector team")
        db.add_all([role, title, team, *users])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-selector-http-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users[:2])]
        db.add_all(agents)
        await db.flush()
        topic, item = Topic(title="Synthetic HTTP participants"), contact(70)
        db.add_all([topic, item, TeamUser(team_id=team.id, user_id=users[0].id)])
        await db.flush()
        tasks = [Task(agent_id=agent.id, label=f"Synthetic HTTP source {index}", objective="<p>Source objective</p>",
                      status=TaskStatus.SUCCESS, dispatch_result={"route": "DIRECT"}, topic_id=topic.id,
                      contact_memory_item_id=item.id if index == 0 else None) for index, agent in enumerate(agents)]
        db.add_all(tasks)
        run_paths = []
        for mechanism in ("dispatcher", "task_analysis"):
            dataset = LabEvaluationDataset(mechanism=mechanism, name=f"Synthetic HTTP {mechanism} runs")
            db.add(dataset)
            await db.flush()
            db.add(LabEvaluationRun(dataset_id=dataset.id, status="completed", phase="finished",
                                     case_snapshots=[{"input": "Synthetic full execution case"}]))
            run_paths.append(f"/api/evaluation/{mechanism}/datasets/{dataset.id}/runs")
        await db.flush()
        team_id, owner_id, topic_id = team.id, users[0].id, str(topic.id)
        task_ids = [str(task.id) for task in tasks]
    paths = ["/api/teams", "/api/teams/humans", f"/api/teams/{team_id}/humans",
             "/api/evaluation/dispatcher/candidates", "/api/evaluation/memory_extraction/candidates",
             "/api/topics", *run_paths]
    for path in paths:
        assert (await client.get(path)).status_code == 401, path
    headers = []
    for index in range(3):
        login = await client.post("/api/auth/login-json", json={
            "email": f"synthetic-selector-http-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    responses = {}
    for path in paths:
        assert (await client.get(path, headers=headers[2])).status_code == 403, path
        response = await client.get(path, headers=headers[0])
        assert response.status_code == 200, (path, response.text)
        responses[path] = response.json()
        assert (await client.get(path, headers=headers[0])).json() == response.json(), path
    listed_team = next(item for item in responses["/api/teams"] if item["id"] == team_id)
    assert listed_team["human_count"] == 1 and listed_team["human_members"][0]["id"] == owner_id
    assert responses[f"/api/teams/{team_id}/humans"][0]["id"] == owner_id
    for mechanism in ("dispatcher", "memory_extraction"):
        path = f"/api/evaluation/{mechanism}/candidates"
        assert [item["task_id"] for item in responses[path]] == task_ids[:1]
        assert [item["task_id"] for item in (await client.get(path, headers=headers[1])).json()] == task_ids[1:]
        assert (await client.get(path, params={"search": "missing-source", "limit": 500}, headers=headers[0])).json() == []
    topic = next(item for item in responses["/api/topics"]["items"] if item["id"] == topic_id)
    assert topic["users"][0]["display_name"] == "Person 70"
    peer_topics = (await client.get("/api/topics", headers=headers[1])).json()["items"]
    assert next(item for item in peer_topics if item["id"] == topic_id)["users"] == []
    for path in run_paths:
        assert len(responses[path]) == 1 and "case_snapshots" not in responses[path][0]
        assert (await client.get(path, params={"limit": 500}, headers=headers[0])).json() == responses[path]
    assert (await client.get("/api/teams/humans", params={"search": "SYNTHETIC-selector-http-0", "limit": 10}, headers=headers[0])).json()[0]["id"] == owner_id
    assert (await client.get("/api/teams/-1/humans", headers=headers[0])).status_code == 404
    assert (await client.post("/api/teams", json={"name": "Denied"}, headers=headers[0])).status_code == 403
    async with get_db_session() as db:
        team = await db.get(Team, team_id)
        team.soft_delete()
    assert (await client.get(f"/api/teams/{team_id}/humans", headers=headers[0])).status_code == 404
