"""Read APIs keep source discovery and indexing progress inside the manager scope."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.file_share.models import FileIndexRun
from app.tools.models import Tool
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_file_read_http_permissions_isolation_and_reopening(client):
    password = "synthetic-file-reader-password"
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "MEMORY_ACCESS"))
        role = Role(code="synthetic-file-reader", privileges=[privilege])
        users = [UserModel(email=f"file-reader-{index}@example.com", is_active=True,
                           hashed_password=encrypt_password(password)) for index in range(2)]
        title = Title(label="Synthetic HTTP file reads", gender="M")
        db.add_all([role, title, *users])
        await db.flush()
        db.add(Assignment(user_id=users[0].id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"file-read-http-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users)]
        tools = [Tool(code=f"synthetic-http-files-{index}", label=f"Synthetic source {index}",
                      file_share_config={"service": "nextcloud", "base_url": "https://files.example.com"})
                 for index in range(2)]
        db.add_all([*agents, *tools])
        await db.flush()
        now = datetime.now(timezone.utc)
        for agent, tool in zip(agents, tools, strict=True):
            db.add(Connection(agent_id=agent.id, tool_id=tool.id, active=True))
            db.add(FileIndexRun(agent_id=agent.id, binding_stamp="synthetic", root_uri=f"{tool.code}://",
                                frontier=[{"uri": f"{tool.code}://private-path"}],
                                started_at=now, updated_at=now, next_attempt_at=now))
        owner_id, peer_id = agents[0].id, agents[1].id

    paths = ("/api/file-share/browser/schemes", "/api/file-share/indexing")
    for path in paths:
        assert (await client.get(path, params={"agent_id": owner_id})).status_code == 401
    headers = []
    for index in range(2):
        login = await client.post("/api/auth/login-json", json={
            "email": f"file-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    for path in paths:
        assert (await client.get(path, params={"agent_id": peer_id}, headers=headers[0])).status_code == 404
        assert (await client.get(path, params={"agent_id": peer_id}, headers=headers[1])).status_code == 403
        first = await client.get(path, params={"agent_id": owner_id}, headers=headers[0])
        reopened = await client.get(path, params={"agent_id": owner_id}, headers=headers[0])
        assert first.status_code == reopened.status_code == 200
        assert first.json() == reopened.json()
        if path.endswith("schemes"):
            schemes = {row["scheme"] for row in first.json()}
            assert "synthetic-http-files-0" in schemes and "synthetic-http-files-1" not in schemes
        else:
            assert first.json()["total"] == 1
            assert first.json()["runs"][0]["root_uri"] == "synthetic-http-files-0://"
            assert "frontier" not in first.json()["runs"][0]
