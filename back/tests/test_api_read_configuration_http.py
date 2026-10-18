"""Real HTTP checks for optimized configuration writes and supervision reads."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine

from app.agent import Agent
from app.agent.models import Title
from app.connection import Connection
from app.goal.tests.factories import make_goal
from app.memory.tests.conftest import memory_storage as memory_storage
from app.messenger import Room
from app.tools import ToolModel
from app.voice.models import VoiceConversationSession
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password
from core.util import SECRET_MASK


@pytest.mark.asyncio
async def test_configuration_http_keeps_scopes_secrets_atomicity_and_reopening(client, memory_storage):
    password = "synthetic-configuration-password"
    async with get_db_session() as db:
        codes = ["CONNECTION_EDIT", "GOAL_ACCESS", "TASK_ACCESS", "READ_USER", "AGENT_EDIT"]
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        global_permission = await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL"))
        assert len(privileges) == len(codes) and global_permission is not None
        role = Role(code="synthetic-config-reader", privileges=privileges)
        global_role = Role(code="synthetic-config-global", privileges=[*privileges, global_permission])
        hashed_password = encrypt_password(password)
        users = [UserModel(email=f"synthetic-config-{index}@example.com", hashed_password=hashed_password, is_active=True) for index in range(4)]
        title = Title(label="Synthetic Config HTTP", gender="N")
        tool = ToolModel(code="synthetic-config-http", label="Synthetic Configuration", connection_schema={"params": {
            **{f"value{index}": {"type": "string"} for index in range(41)}, "token": {"type": "password"}, "count": {"type": "integer"},
        }})
        protected = ToolModel(code="synthetic-config-protected", label="Synthetic protected Tool", can_disable=False)
        db.add_all([role, global_role, title, tool, protected, *users])
        await db.flush()
        db.add_all([Assignment(user_id=users[index].id, role_id=role.id, is_default=True) for index in (0, 1)])
        db.add(Assignment(user_id=users[3].id, role_id=global_role.id, is_default=True))
        agents = [Agent(user_id=users[index].id, title_id=title.id, code=f"synthetic-config-http-{index}", first_name="Synthetic", last_name=str(index)) for index in (0, 1)]
        db.add_all(agents)
        await db.flush()
        connections = [Connection(agent_id=agent.id, tool_id=tool.id, active=True) for agent in agents]
        locked_connection = Connection(agent_id=agents[0].id, tool_id=protected.id, active=True)
        db.add_all([*connections, locked_connection])
        await db.flush()
        goals = []
        for index, agent in enumerate(agents):
            goal = await make_goal(agent_id=agent.id, title=f"Synthetic HTTP goal {index}", description="<p>Synthetic description</p>")
            db.add(goal)
            goals.append(goal)
        room = Room(connection_id=connections[0].id, external_id="synthetic-config-voice", label="Synthetic call", conversation_type="audio")
        db.add(room)
        await db.flush()
        now = datetime.now(timezone.utc)
        call = VoiceConversationSession(messenger_room_id=room.id, started_at=now, finished_at=now, status="COMPLETED")
        db.add(call)
        await db.flush()
        connection_id, locked_id, call_id = connections[0].id, locked_connection.id, str(call.id)
        goal_ids, user_ids = [str(row.id) for row in goals], [row.id for row in users]
    bulk_path = f"/api/connections/{connection_id}/params/bulk"
    voice_path = f"/api/voice/conversations/{call_id}"
    paths = ["/api/goals", "/api/goals/tree", "/api/auth/users", "/api/agents/managers", "/api/voice/conversations", voice_path]
    for path in [*paths, "/api/onboarding/overview", "/api/llm/me/options"]:
        assert (await client.get(path)).status_code == 401, path
    params = {f"value{index}": f"Synthetic value {index}" for index in range(41)}
    params.update(token="synthetic-http-secret", count="7")
    payload = {"connection_id": connection_id, "params": params}
    assert (await client.post(bulk_path, json=payload)).status_code == 401
    headers = []
    for index in range(4):
        login = await client.post("/api/auth/login-json", json={"email": f"synthetic-config-{index}@example.com", "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    for path in paths:
        assert (await client.get(path, headers=headers[2])).status_code == 403, path
        response = await client.get(path, headers=headers[0])
        assert response.status_code == 200, (path, response.text)
        assert (await client.get(path, headers=headers[0])).json() == response.json()
    assert [item["id"] for item in (await client.get("/api/goals", headers=headers[0])).json()["items"]] == goal_ids[:1]
    assert [item["id"] for item in (await client.get("/api/goals/tree", headers=headers[1])).json()["items"]] == goal_ids[1:]
    assert (await client.get(voice_path, headers=headers[1])).status_code == 404
    assert (await client.get("/api/voice/conversations", headers=headers[1])).json()["total"] == 0
    assert {item["id"] for item in (await client.get("/api/agents/managers", headers=headers[3])).json()} >= set(user_ids)
    assert (await client.get("/api/llm/me/options", headers=headers[2])).status_code == 200
    assert (await client.get("/api/onboarding/overview", headers=headers[2])).status_code == 200
    for identity, status in ((1, 404), (2, 403)):
        assert (await client.post(bulk_path, json=payload, headers=headers[identity])).status_code == status
    queries = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            queries.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        response = await client.post(bulk_path, json=payload, headers=headers[0])
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    report = {"fields": len(params), "queries": len(queries)}
    destination = Path(__file__).resolve().parents[2] / "artifacts/api-read-lot-configuration-bulk-http.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    assert response.status_code == 201, response.text
    assert [item["param_name"] for item in response.json()] == list(params)
    assert next(item["param_value"] for item in response.json() if item["param_name"] == "token") is None
    assert "synthetic-http-secret" not in response.text
    masked = await client.post(bulk_path, json={"connection_id": connection_id, "params": {"token": SECRET_MASK}}, headers=headers[0])
    assert masked.status_code == 201 and masked.json()[0]["param_value"] is None
    invalid = await client.post(bulk_path, json={"connection_id": connection_id, "params": {"value0": "must not persist", "count": "invalid"}}, headers=headers[0])
    assert invalid.status_code == 422
    reopened = (await client.get(f"/api/connections/{connection_id}/params", headers=headers[0])).json()
    assert reopened["params"]["value0"] == "Synthetic value 0" and "token" in reopened["configured_params"]
    assert (await client.post(f"/api/connections/{locked_id}/params/bulk", json={"connection_id": locked_id, "params": {}}, headers=headers[0])).status_code == 403
    assert (await client.post(bulk_path, json={"connection_id": -1, "params": {}}, headers=headers[0])).status_code == 400
    assert report["queries"] < 100, report


@pytest.mark.asyncio
async def test_parameter_batches_serialize_on_independent_committed_connections(committed_database):
    from app.connection import connection_service
    from app.connection.models import ConnectionParam

    async with get_db_session() as db:
        user = UserModel(email="synthetic-batch-concurrency@example.com", hashed_password="unused", is_active=True)
        title = Title(label="Synthetic batch concurrency", gender="N")
        tool = ToolModel(code="synthetic-batch-concurrency", label="Synthetic concurrent batches", connection_schema={"params": {
            f"field{index}": {"type": "string"} for index in range(41)
        }})
        db.add_all([user, title, tool])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code="synthetic-batch-concurrency", first_name="Synthetic", last_name="Writer")
        db.add(agent)
        await db.flush()
        connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        identifier = connection.id
    barrier = asyncio.Barrier(2)

    async def writer(marker):
        async with get_db_session() as db:
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            await barrier.wait()
            saved = await connection_service.set_params_bulk(identifier, {f"field{index}": marker for index in range(41)})
            return pid, {row.param_name: row.id for row in saved}

    async with asyncio.timeout(15):
        first, second = await asyncio.gather(writer("Synthetic A"), writer("Synthetic B"))
    assert first[0] != second[0] and first[1] == second[1]
    async with get_db_session() as db:
        values = list(await db.scalars(select(ConnectionParam.param_value).where(ConnectionParam.connection_id == identifier)))
        assert len(values) == 41 and set(values) in ({"Synthetic A"}, {"Synthetic B"})
