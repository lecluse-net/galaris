"""The common selector follows operation scopes, without granting task management to teammates."""

from uuid import uuid4
from base64 import b64decode

import pytest
from sqlalchemy import select

from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.team import TeamModel
from core.team.service import set_human_membership
from app.agent.models import Agent, Title
from app.agent.dialogue_service import set_agent_membership
from app.task.models import Task


@pytest.mark.asyncio
@pytest.mark.parametrize("privileges", [[], ["FILE_ACCESS"], ["TEAM_ACCESS"]])
async def test_selection_avatar_reads_preserve_scope_without_agent_administration(client, privileges):
    from core.authorize.tests.test_guard_policy_parameters import actor
    from core.authorize.tests.test_domain_authorization import owned_agent

    headers, user_id = await actor(privileges)
    _, outsider_id = await actor([])
    own = await owned_agent(user_id)
    outside = await owned_agent(outsider_id)
    portrait = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=")
    async with get_db_session() as db:
        for identity in [own, outside]:
            agent = await db.get(Agent, identity)
            agent.avatar = portrait
    url = f"/api/agents/{own}/avatar"
    assert (await client.get(url)).status_code == 401
    response = await client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.content == portrait and response.headers["content-type"] == "image/png"
    assert (await client.get(f"/api/agents/{outside}/avatar", headers=headers)).status_code == (200 if "TEAM_ACCESS" in privileges else 404)
    assert (await client.get("/api/agents", headers=headers)).status_code == 403
    assert (await client.post(url, headers=headers, files={"file": ("portrait.png", portrait, "image/png")})).status_code == 403
    assert (await client.delete(url, headers=headers)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("public_origin", ["http://localhost", "https://galaris.example"])
async def test_selection_scopes_and_task_management_follow_authenticated_authority(client, monkeypatch, public_origin):
    from core import settings
    monkeypatch.setattr(settings, "APP_HOST", public_origin)
    password = "Selection-test-password-123"
    email = f"admin-{uuid4()}@example.com"
    await client.post('/api/auth/register', json={'email': email, 'password': password})
    login = await client.post('/api/auth/login-json', json={'email': email, 'password': password})
    admin = {'Authorization': 'Bearer ' + login.json()['access_token'], 'X-Editorial-Profile-Version': '1'}
    admin_id = (await client.get('/api/auth/me', headers=admin)).json()['id']
    email = f"manager-{uuid4()}@example.com"
    created = await client.post('/api/auth/users', headers=admin, json={'email': email, 'password': password})
    user_id = created.json()['id']
    async with get_db_session() as db:
        # Signup also creates the administrator's default Galaris assistant.
        initial_agent_ids = list(await db.scalars(select(Agent.id)))
        privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(['TASK_ACCESS', 'TASK_EDIT', 'TEAM_ACCESS', 'CHAT_ACCESS'])))).all())
        role = Role(code=f"selection-{uuid4().hex}", display_name="Local manager", privileges=privileges)
        title = Title(label="Mx", gender="M")
        team = TeamModel(name="Shared team", order=20)
        other_team = TeamModel(name="Another team", order=10)
        private_team = TeamModel(name="Outside team", order=30)
        db.add_all([role, title, team, other_team, private_team])
        await db.flush()
        db.add(Assignment(user_id=user_id, role_id=role.id, is_default=True))
        own = Agent(user_id=user_id, title_id=title.id, code='selection-a', first_name='Zoé', last_name='Exemple')
        peer = Agent(user_id=admin_id, title_id=title.id, code='selection-b', first_name='Émile', last_name='Exemple')
        outside = Agent(user_id=admin_id, title_id=title.id, code='selection-c', first_name='alice', last_name='Exemple')
        db.add_all([own, peer, outside])
        await db.flush()
        await set_human_membership(team.id, user_id, True)
        await set_agent_membership(team.id, peer.id, True)
        await set_agent_membership(other_team.id, peer.id, True)
        await set_agent_membership(private_team.id, outside.id, True)
        peer_teams = [{'id': other_team.id, 'name': other_team.name, 'order': 10},
                      {'id': team.id, 'name': team.name, 'order': 20}]
        tasks = [Task(agent_id=agent.id, label='Managed task') for agent in (own, peer, outside)]
        db.add_all(tasks)
        await db.flush()
        from app.goal.tests.factories import make_goal
        goal = await make_goal(title='Foreign goal', description='Private', agent_id=outside.id)
        ids = [own.id, peer.id, outside.id]
        task_ids = [str(task.id) for task in tasks]
        goal_id = str(goal.id)
        team_id = team.id
    # Keep the two actors in independent browser sessions, including with HTTP cookies.
    client.cookies.clear()
    login = await client.post('/api/auth/login-json', json={'email': email, 'password': password})
    human = {'Authorization': 'Bearer ' + login.json()['access_token'], 'X-Editorial-Profile-Version': '1'}
    for scope, expected in [('management', ids[:1]), ('dialogue', ids[:2]), ('teams', initial_agent_ids + ids)]:
        response = await client.get('/api/agents/selection', params={'scope': scope}, headers=human)
        assert response.status_code == 200
        assert {item['id'] for item in response.json()} == set(expected)
        ordered_ids = [item['id'] for item in response.json() if item['id'] in ids]
        assert ordered_ids == [agent_id for agent_id in reversed(ids) if agent_id in expected]
        assert all(set(item) == {'id', 'label', 'has_avatar', 'driver', 'teams'} for item in response.json())
        by_id = {item['id']: item for item in response.json()}
        assert by_id[ids[0]]['teams'] == []
        if ids[1] in expected:
            assert by_id[ids[1]]['teams'] == peer_teams
        if scope != 'teams':
            assert all(team['name'] != 'Outside team' for item in response.json() for team in item['teams'])
    assert (await client.get('/api/agents/selection', headers=admin)).status_code == 200
    for task_id in task_ids[1:]:
        assert (await client.get(f'/api/tasks/{task_id}', headers=human)).status_code == 404
        assert (await client.get(f'/api/tasks/{task_id}/budget', headers=human)).status_code == 404
        assert (await client.get(f'/api/tasks/{task_id}/budget', headers=admin)).status_code == 200
        assert (await client.get(f'/api/tasks/{task_id}', headers=admin)).status_code == 200
        assert (await client.post(f'/api/tasks/{task_id}/cancel', headers=human, json={'expected_revision': 1})).status_code == 404
    assert (await client.get(f'/api/tasks/{task_ids[0]}', headers=human)).status_code == 200
    budget_url = f'/api/tasks/{task_ids[0]}/budget'
    assert (await client.get(budget_url)).status_code == 401
    budget = await client.get(budget_url, headers=human)
    assert budget.status_code == 200
    assert budget.json()['enabled'] is False
    assert budget.json()['max_cost'] is None
    for references in [{'parent_id': task_ids[2]}, {'source_task_id': task_ids[2]}, {'requester_agent_id': ids[2]}, {'goal_id': goal_id}]:
        response = await client.post('/api/tasks', headers=human, json={'agent_id': ids[0], 'label': 'Attempt', **references})
        assert response.status_code == 404
    response = await client.post('/api/tasks', headers=human, json={'agent_id': ids[0], 'label': 'Allowed', 'parent_id': task_ids[0]})
    assert response.status_code == 201
    assert (await client.post(f'/api/tasks/{task_ids[0]}/cancel', headers=human, json={'expected_revision': 1})).status_code == 200
    assert (await client.post(f'/api/tasks/{task_ids[2]}/cancel', headers=admin, json={'expected_revision': 1})).status_code == 200
    async with get_db_session():
        await set_human_membership(team_id, user_id, False)
    response = await client.get('/api/agents/selection', params={'scope': 'dialogue'}, headers=human)
    assert [item['id'] for item in response.json()] == ids[:1]
    assert (await client.get('/api/agents/selection')).status_code == 401
