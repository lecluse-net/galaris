"""A mounted native MCP server never outlives an operator's current authorization."""

from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.browser import mcp as browser_mcp
from app.browser.service import BrowserExecutor
from app.connection.models import Connection, ConnectionFunctionState
from app.tools import mandatory_tools, mcp_loader
from app.tools.models import Tool
from app.tools.contracts import EXECUTION_META_KEY
from core.database import get_db_session
from core.user.models import User


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["connection", "function"])
async def test_mounted_tool_rechecks_rights_and_keeps_other_agents_operational(committed_database, monkeypatch, revocation):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"session_id": "session", "url": "https://example.org/",
            "title": "Public page", "revision": 1, "content": "Readable", "start": 0,
            "end": 8, "total": 8, "truncated": False, "next_offset": None})

    monkeypatch.setattr(browser_mcp, "browser_executor", BrowserExecutor(
        base_url="http://executor.test", token="synthetic-token", transport=httpx.MockTransport(respond)))
    async with get_db_session() as db:
        title = Title(label="Live authorization", gender="X")
        users = [User(email=f"permissions-{uuid4().hex}@example.test", hashed_password="unused") for _ in range(2)]
        db.add_all([title, *users])
        await db.flush()
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"permissions-{uuid4().hex}", first_name=name,
                        last_name="Synthetic", agent_driver="internal") for user, name in zip(users, ("One", "Two"))]
        db.add_all(agents)
        await db.flush()
        identifiers = [agent.id for agent in agents]
        for identifier in identifiers:
            await mandatory_tools.sync_integrated_tool_connections(identifier)
    async with get_db_session():
        servers = [await mcp_loader.build_agent_galaris_fastmcp(identifier, runtime="internal") for identifier in identifiers]
    async with Client(servers[0]) as client, Client(servers[1]) as other:
        arguments = {"url": "https://example.org/", "output": "content"}
        assert not (await client.call_tool("browser_open", arguments)).is_error
        async with get_db_session() as db:
            connection = await db.scalar(select(Connection).join(Tool).where(
                Connection.agent_id == identifiers[0], Tool.code == "browser"))
            connection_id = connection.id
            if revocation == "connection":
                connection.active = False
            else:
                db.add(ConnectionFunctionState(connection_id=connection_id, function_name="browser_open", enabled=False))
        denied = await client.call_tool("browser_open", arguments, raise_on_error=False)
        assert denied.is_error
        assert denied.meta[EXECUTION_META_KEY]["outcome"] == "rejected"
        assert len(requests) == 1, "Revocation must be checked before contacting the executor"
        assert not (await other.call_tool("browser_open", arguments)).is_error
        async with get_db_session() as db:
            if revocation == "connection":
                (await db.get(Connection, connection_id)).active = True
            else:
                state = await db.scalar(select(ConnectionFunctionState).where(
                    ConnectionFunctionState.connection_id == connection_id,
                    ConnectionFunctionState.function_name == "browser_open"))
                await db.delete(state)
        assert not (await client.call_tool("browser_open", arguments)).is_error
        assert len(requests) == 3
