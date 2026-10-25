from uuid import uuid4

import pytest

from app.task.models import Task, TaskStatus
from app.task.cost_report import cost_report
from app.task.tests.test_resource_facade import _agents
from app.llm.models import LLMCall


@pytest.mark.asyncio
async def test_costs_follow_both_lineage_edges_once_and_exclude_foreign_agents(db):
    owner, peer, _ = await _agents(db)
    root = Task(agent_id=owner.id, label="Synthetic root", cost=999, status=TaskStatus.SUCCESS)
    db.add(root)
    await db.flush()
    child = Task(agent_id=owner.id, label="Synthetic child", parent_id=root.id,
                 source_task_id=root.id, cost=500, status=TaskStatus.ERROR)
    foreign = Task(agent_id=peer.id, label="Synthetic peer", source_task_id=root.id, cost=400)
    db.add_all([child, foreign])
    await db.flush()
    db.add_all([LLMCall(task_id=root.id, cost=.1, inference_cost=.1, cost_estimated=False,
                       status="completed", purpose="agent.planning"),
                LLMCall(task_id=child.id, cost=.2, inference_cost=.2, cost_estimated=False,
                       status="error", purpose="agent.exec"),
                LLMCall(task_id=foreign.id, cost=400, inference_cost=400, cost_estimated=False, status="completed")])
    await db.flush()
    report = await cost_report(root.id, frozenset({owner.id}))
    assert report.summary.recorded_cost == pytest.approx(.3)
    assert report.summary.calls == 2 and report.summary.failed_calls == 1
    assert report.restricted and report.tasks == 2
    assert report.by_purpose["agent.exec"].recorded_cost == .2
    assert report.verified_success is report.cost_per_success is None
    assert (await cost_report(root.id, None)).summary.recorded_cost == pytest.approx(400.3)


@pytest.mark.asyncio
async def test_cost_endpoint_requires_task_privileges_and_current_management_scope(client, monkeypatch):
    from sqlalchemy import select
    from core.database import get_db_session
    from app.agent.models import Agent
    from app.agent import AgentManagementScope
    from app.task import router

    assert (await client.get(f"/api/tasks/{uuid4()}/costs")).status_code in {401, 403}
    credentials = {"email": f"cost-{uuid4().hex}@example.com", "password": "synthetic-cost-password"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    async with get_db_session() as setup:
        owner_id = await setup.scalar(select(Agent.id).limit(1))
        root = Task(agent_id=owner_id, label="Synthetic private costs")
        setup.add(root)
        await setup.flush()
        url = f"/api/tasks/{root.id}/costs"

    async def denied():
        return AgentManagementScope(user_id=0, agent_ids=frozenset())

    async def allowed():
        return AgentManagementScope(user_id=0, agent_ids=frozenset({owner_id}))

    monkeypatch.setattr(router, "current_management_scope", denied)
    assert (await client.get(url)).status_code == 404
    monkeypatch.setattr(router, "current_management_scope", allowed)
    response = await client.get(url)
    assert response.status_code == 200
    assert response.json()["summary"]["total_cost"] is None
