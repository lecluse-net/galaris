"""The common selector follows operation scopes, without granting task management to teammates."""

from uuid import uuid4

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
        privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(['TASK_ACCESS', 'TASK_EDIT', 'TEAM_ACCESS', 'CHAT_ACCESS'])))).all())
        role = Role(code=f"selection-{uuid4().hex}", display_name="Local manager", privileges=privileges)
        title = Title(label="Mx", gender="M")
        team = TeamModel(name="Shared team")
        db.add_all([role, title, team])
        await db.flush()
        db.add(Assignment(user_id=user_id, role_id=role.id, is_default=True))
        own = Agent(user_id=user_id, title_id=title.id, code='selection-own', first_name='Own', last_name='Agent')
        peer = Agent(user_id=admin_id, title_id=title.id, code='selection-peer', first_name='Peer', last_name='Agent')
        outside = Agent(user_id=admin_id, title_id=title.id, code='selection-outside', first_name='Outside', last_name='Agent')
        db.add_all([own, peer, outside])
        await db.flush()
        await set_human_membership(team.id, user_id, True)
        await set_agent_membership(team.id, peer.id, True)
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
    for scope, expected in [('management', ids[:1]), ('dialogue', ids[:2]), ('teams', ids)]:
        response = await client.get('/api/agents/selection', params={'scope': scope}, headers=human)
        assert response.status_code == 200
        assert {item['id'] for item in response.json()} == set(expected)
        assert all(set(item) == {'id', 'label', 'has_avatar'} for item in response.json())
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
