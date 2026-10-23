"""Human deletion exercises real HTTP authorization and persistence."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection.models import Connection, ConnectionFunctionState, ConnectionParam
from app.tools.models import Tool
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_human_tool_purge_requires_edit_privilege_and_the_current_confirmation(client):
    suffix = uuid4().hex
    password = "synthetic-deletion-password"
    async with get_db_session() as db:
        users = []
        for code in ("TOOL_ACCESS", "TOOL_EDIT"):
            privilege = await db.scalar(select(Privilege).where(Privilege.code == code))
            role = Role(code=f"deletion-{code}-{suffix}", privileges=[privilege])
            user = UserModel(email=f"{code}-{suffix}@example.com", hashed_password=encrypt_password(password), is_active=True)
            db.add_all([role, user])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            users.append(user.email)
        title = Title(label="Synthetic deletion", gender="X")
        db.add(title)
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code=f"deletion-{suffix}", first_name="Synthetic", last_name="Operator")
        tool = Tool(code=f"deletion-{suffix}", label="Synthetic removable Tool")
        db.add_all([agent, tool])
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        db.add(ConnectionParam(connection_id=connection.id, param_name="secret", param_value="synthetic-secret-never-disclosed"))
        tool_id, connection_id = tool.id, connection.id
        system_id = await db.scalar(select(Tool.id).where(Tool.code == "galaris"))
    path = f"/api/tools/{tool_id}"
    assert (await client.get(f"{path}/deletion-impact")).status_code == 401
    assert (await client.delete(path, params={"cascade": "true"})).status_code == 401
    headers = []
    for email in users:
        login = await client.post("/api/auth/login-json", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    reader, editor = headers
    assert (await client.get(f"{path}/deletion-impact", headers=reader)).status_code == 403
    assert (await client.delete(path, params={"cascade": "true"}, headers=reader)).status_code == 403
    assert (await client.get(f"/api/tools/{system_id}/deletion-impact", headers=editor)).status_code == 403
    assert (await client.delete(f"/api/tools/{system_id}", params={"cascade": "true"}, headers=editor)).status_code == 403
    response = await client.get(f"{path}/deletion-impact", headers=editor)
    assert response.status_code == 200, response.text
    assert "synthetic-secret" not in response.text
    preview = response.json()
    assert {row["kind"]: row["count"] for row in preview["deleted"]} == {"connections": 1, "parameters": 1}
    assert (await client.delete(path, params={"cascade": "true"}, headers=editor)).status_code == 409
    async with get_db_session() as db:
        db.add(ConnectionFunctionState(connection_id=connection_id, function_name="read", enabled=False, state="ask"))
    stale = await client.delete(path, params={"cascade": "true", "expected_version": preview["version"]}, headers=editor)
    assert stale.status_code == 409, stale.text
    current = (await client.get(f"{path}/deletion-impact", headers=editor)).json()
    deleted = await client.delete(path, params={"cascade": "true", "expected_version": current["version"]}, headers=editor)
    assert deleted.status_code == 204, deleted.text
    async with get_db_session() as db:
        assert await db.get(Tool, tool_id) is None
        assert await db.get(Connection, connection_id) is None
        assert await db.scalar(select(ConnectionParam.id).where(ConnectionParam.connection_id == connection_id)) is None
        assert await db.scalar(select(ConnectionFunctionState.id).where(ConnectionFunctionState.connection_id == connection_id)) is None
        assert await db.get(Tool, system_id) is not None
