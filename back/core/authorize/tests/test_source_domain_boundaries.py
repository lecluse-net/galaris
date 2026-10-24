"""Cross-domain HTTP regressions with persisted, entirely synthetic data."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.database import get_db_session
from core.authorize.tests.test_guard_policy_parameters import actor
from core.authorize.tests.test_domain_authorization import owned_agent
from app.process.bpmn import Workflow, Node, Flow
from app.process.native_definitions import create
from app.process.models import ProcessRun
from app.topic.models import Topic
from app.task.models import Task, TaskStatus
from app.connection.models import Connection
from app.tools.models import Tool
from bridge.mail.models import MailOutboundDelivery


@pytest.mark.asyncio
async def test_memory_reader_does_not_gain_process_payloads(client):
    headers, user_id = await actor(["MEMORY_ACCESS"])
    agent_id = await owned_agent(user_id)
    graph = Workflow(nodes=[Node(id="begin", kind="start"), Node(id="end", kind="end")],
        flows=[Flow(id="one", source="begin", target="end")])
    async with get_db_session() as db:
        definition = await create(actor_agent_id=agent_id, title="Synthetic private process", graph=graph)
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent_id, engine_code="galaris",
            correlation_id=str(uuid4()), callback_token=uuid4().hex, status="success",
            data={"synthetic_private_process_value": "independent-domain"},
            launch_snapshot={"definition": {"graph": graph.model_dump(mode="json"), "revision": 1}})
        db.add(run)
        await db.flush()
        run_id = run.id
    response = await client.get(f"/api/processes/internal/runs/{run_id}", headers=headers)
    assert response.status_code == 403, (response.status_code, response.json().get("data"))


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    "TASK_ACCESS", "TASK_EDIT", "CONVERSATION_ACCESS", "CONVERSATION_CONTROL",
    "VOICE_HISTORY_ACCESS", "VOICE_HISTORY_CONTROL", "CHAT_ACCESS",
    "DOCUMENT_ACCESS", "DOCUMENT_EDIT", "DOCUMENT_ADMIN",
    "MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN",
    "DATASET_READ", "DATASET_EDIT", "DATASET_ADMIN",
])
async def test_source_reader_can_resolve_only_topic_labels(client, code):
    headers, _ = await actor([code])
    async with get_db_session() as db:
        topic = Topic(title="Synthetic monitoring label")
        db.add(topic)
        await db.flush()
        topic_id = topic.id
    response = await client.get("/api/topics/refs", headers=headers, params={"ids": str(topic_id)})
    assert response.status_code == 200, response.text
    assert response.json() == [{"id": str(topic_id), "title": "Synthetic monitoring label"}]
    assert (await client.get(f"/api/topics/{topic_id}/content", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_topic_access_does_not_imply_task_content_access(client):
    headers, user_id = await actor(["TOPIC_ACCESS"])
    agent_id = await owned_agent(user_id)
    async with get_db_session() as db:
        topic = Topic(title="Synthetic dossier boundary")
        db.add(topic)
        await db.flush()
        task = Task(label="Synthetic protected task", objective="<p>Synthetic private Task objective</p>",
            agent_id=agent_id, topic_id=topic.id, status=TaskStatus.SUCCESS,
            ai=False, paused=False, cost=0.0, effort="standard", auto_approve=False)
        db.add(task)
        await db.flush()
        topic_id, task_id = topic.id, task.id
    assert (await client.get(f"/api/tasks/{task_id}", headers=headers)).status_code == 403
    content = await client.get(f"/api/topics/{topic_id}/content", headers=headers)
    assert content.status_code == 200, content.text
    assert content.json()["tasks"] == [], content.json()["tasks"]


@pytest.mark.asyncio
async def test_mail_decision_does_not_use_connection_read_only(client):
    headers, user_id = await actor(["CONNECTION_ACCESS"])
    agent_id = await owned_agent(user_id)
    async with get_db_session() as db:
        tool = await db.scalar(select(Tool).where(Tool.code == "mail"))
        assert tool is not None
        connection = Connection(agent_id=agent_id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        delivery = MailOutboundDelivery(connection_id=connection.id, agent_id=agent_id,
            approver_user_id=user_id, approval_required=True, status="pending_approval",
            idempotency_key=uuid4().hex, payload_fingerprint="0" * 64,
            rfc_message_id=f"<{uuid4()}@example.invalid>", ai_disclosure_version="synthetic",
            subject="Synthetic pending approval", body="Synthetic content", to_addresses=["test@example.invalid"])
        db.add(delivery)
        await db.flush()
        delivery_id = delivery.id
    response = await client.post(f"/api/mail/outbound/{delivery_id}/reject", headers=headers,
        json={"reason": "Synthetic audit rejection"})
    assert response.status_code == 403, (response.status_code, response.text)


@pytest.mark.asyncio
async def test_topic_content_requires_each_source_right_and_keeps_agent_scope(client):
    for source, own_visible in [(False, False), (True, True)]:
        headers, user_id = await actor(["TOPIC_ACCESS", *(["TASK_ACCESS"] if source else [])])
        own = await owned_agent(user_id)
        _, other_user = await actor([])
        foreign = await owned_agent(other_user)
        async with get_db_session() as db:
            topic = Topic(title="Synthetic mixed dossier")
            db.add(topic)
            await db.flush()
            tasks = [Task(label=f"Synthetic {label}", objective=f"<p>{label}</p>", agent_id=identity,
                topic_id=topic.id, status=TaskStatus.SUCCESS, ai=False, cost=0, effort="standard", auto_approve=False)
                for label, identity in [("visible-source", own), ("foreign-source", foreign)]]
            db.add_all(tasks)
            await db.flush()
            topic_id = topic.id
        response = await client.get(f"/api/topics/{topic_id}/content", headers=headers)
        assert response.status_code == 200
        content = response.json()
        assert len(content["tasks"]) == int(own_visible)
        assert content["summary"]["tasks"] == int(own_visible)
        assert "foreign-source" not in response.text


@pytest.mark.asyncio
async def test_goal_configuration_and_operational_status_are_independent(client):
    for code in ["GOAL_ACCESS", "GOAL_EDIT", "GOAL_CONFIG_ACCESS", "GOAL_CONFIG_EDIT"]:
        headers, _ = await actor([code])
        configuration = code.startswith("GOAL_CONFIG_")
        full = await client.get("/api/goals/settings", headers=headers)
        assert full.status_code == (200 if configuration else 403)
        runtime = await client.get("/api/goals/runtime-status", headers=headers)
        assert runtime.status_code == (403 if configuration else 200)
        if not configuration:
            assert "schedule" not in runtime.json()
        patched = await client.patch("/api/goals/settings", headers=headers, json={"globally_paused": True})
        assert patched.status_code == 403  # Readers or missing global management scope.
        bypass = await client.put("/api/params/goal.runtime.settings", headers=headers, json={"value": "{}"})
        assert bypass.status_code == 403
    headers, _ = await actor(["GOAL_CONFIG_EDIT", "AGENT_MANAGE_ALL"])
    assert (await client.patch("/api/goals/settings", headers=headers, json={"globally_paused": True})).status_code == 200


@pytest.mark.asyncio
async def test_calendar_roles_use_scoped_metadata_and_do_not_open_connector_configuration(client):
    for code in ["CALENDAR_ACCESS", "CALENDAR_EDIT", "CONNECTION_ACCESS"]:
        headers, user_id = await actor([code])
        own = await owned_agent(user_id)
        _, other_user = await actor([])
        other = await owned_agent(other_user)
        async with get_db_session() as db:
            tool = await db.scalar(select(Tool).where(Tool.code == "calendar"))
            connections = [Connection(agent_id=identity, tool_id=tool.id, active=True) for identity in [own, other]]
            db.add_all(connections)
            await db.flush()
            own_id, other_id = [connection.id for connection in connections]
        response = await client.get("/api/calendars/connection-options", headers=headers)
        if code == "CONNECTION_ACCESS":
            assert response.status_code == 403
            assert (await client.get("/api/calendars", params={"connection_id": own_id}, headers=headers)).status_code == 403
            continue
        assert response.status_code == 200 and response.json()
        assert all(set(item) == {"id", "agent_id", "label"} for item in response.json())
        assert {item["id"] for item in response.json()} == {own_id}
        assert (await client.get("/api/calendars", params={"connection_id": other_id}, headers=headers)).status_code == 404
        assert (await client.get(f"/api/connections/{own_id}/params", headers=headers)).status_code == 403
        created = await client.post("/api/calendars", headers=headers, json={"connection_id": own_id,
            "label": "Synthetic calendar", "url": "https://calendar.example.invalid/events.ics"})
        assert created.status_code == (201 if code == "CALENDAR_EDIT" else 403), created.text


@pytest.mark.asyncio
async def test_connector_metadata_does_not_disclose_global_tool_configuration(client):
    headers, _ = await actor(["CONNECTION_ACCESS"])
    async with get_db_session() as db:
        db.add(Tool(code=f"synthetic-{uuid4()}", label="Synthetic schema",
            mcp_config={"type": "http", "url": "https://synthetic-private.invalid", "env": {"TOKEN": "private-marker"}},
            global_params={"token": {"value": "private-marker", "type": "password"}},
            connection_schema={"properties": {"key": {"type": "password"}}}))
    response = await client.get("/api/connections/tool-options", headers=headers)
    assert response.status_code == 200 and response.json()
    assert "private-marker" not in response.text and "synthetic-private.invalid" not in response.text
    assert all(item["global_params"] == {} for item in response.json())
    assert (await client.get("/api/tools", headers=headers)).status_code == 403
