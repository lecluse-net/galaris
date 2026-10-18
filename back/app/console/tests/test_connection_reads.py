"""Console discovery stays bounded and observes live configuration without SSH I/O."""

from contextlib import asynccontextmanager
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection, connection_service
from app.connection.models import ConnectionParam
from app.console.connection_service import is_embedded_executor_in_use, resolve_ssh_connection
from app.file_share.browser import browser_context
from app.file_share.resource_service import list_schemes
from app.tools.models import Tool
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password
from core.util import get_encryption_service


def save_report(name, rows):
    destination = Path(__file__).resolve().parents[4] / f"artifacts/{name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, indent=2) + "\n")


@asynccontextmanager
async def count_queries(db):
    statements = []
    connection = await db.connection()

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)


async def owners(db, count=2, driver="internal"):
    title = Title(label="Synthetic Console reads", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"console-read-{index}", first_name="Synthetic",
                    last_name=str(index), agent_driver=driver) for index in range(count)]
    db.add_all(agents)
    await db.flush()
    return agents


@pytest.mark.asyncio
async def test_browser_discovery_does_not_scan_unrelated_tools(db):
    owner, peer = await owners(db)
    owner_id, peer_id = owner.id, peer.id
    console = await db.scalar(select(Tool).where(Tool.code == "console"))
    # A peer's active Console must not become the selected Agent's local filesystem.
    db.add(Connection(agent_id=peer_id, tool_id=console.id, active=True))
    source = Tool(code="synthetic-console-files", label="Synthetic files",
                  file_share_config={"service": "nextcloud", "base_url": "https://files.example.com"})
    db.add(source)
    await db.flush()
    db.add(Connection(tool_id=source.id, agent_id=owner_id, active=True))
    await db.commit()
    reports = []
    for start, stop in ((0, 1), (1, 41)):
        tools = [Tool(code=f"synthetic-console-ordinary-{index}", label=f"Synthetic Tool {index}")
                 for index in range(start, stop)]
        db.add_all(tools)
        await db.flush()
        db.add_all([Connection(tool_id=tool.id, agent_id=owner_id, active=True) for tool in tools])
        await db.commit()
        db.expunge_all()
        async with count_queries(db) as statements:
            async with browser_context(owner_id) as context:
                assert context.console_resource is None
                schemes = await list_schemes(context)
        names = {scheme.scheme for scheme in schemes}
        assert "synthetic-console-files" in names and "console" not in names
        assert not any(name.startswith("synthetic-console-ordinary-") for name in names)
        reports.append({"ordinary_tools": stop, "queries": len(statements)})
    save_report("console-browser-reads", reports)
    assert all(row["queries"] <= 7 for row in reports), reports


@pytest.mark.asyncio
async def test_console_resolution_keeps_secrets_globals_errors_and_freshness(db):
    owner, peer = await owners(db)
    owner_id, peer_id = owner.id, peer.id
    tool = await db.scalar(select(Tool).where(Tool.code == "console"))
    encryption = get_encryption_service()
    tool.global_params = {
        "host": {"value": "forced.example.com", "forced": True},
        "port": {"value": "2222", "forced": False},
        "private_key": {"value": encryption.encrypt("synthetic-private-key"), "forced": False},
        "known_host_key": {"value": encryption.encrypt("synthetic-pinned-key"), "forced": False},
    }
    connection = Connection(tool_id=tool.id, agent_id=owner_id, active=False)
    db.add(connection)
    await db.flush()
    db.add_all([ConnectionParam(connection_id=connection.id, param_name="host", param_value="local.example.com"),
                ConnectionParam(connection_id=connection.id, param_name="username", param_value="synthetic-user")])
    await db.commit()
    assert await resolve_ssh_connection(owner_id) is None
    connection.active = True
    await db.commit()
    config = await resolve_ssh_connection(owner_id)
    assert config is not None and config.connection_id == connection.id
    assert config.host == "forced.example.com" and config.port == 2222
    assert config.username == "synthetic-user"
    assert config.private_key.get_secret_value() == "synthetic-private-key"
    assert config.known_host_key == "synthetic-pinned-key"
    assert "synthetic-private-key" not in repr(config)
    assert await resolve_ssh_connection(peer_id) is None
    assert await resolve_ssh_connection(owner_id) == config

    # Changes committed by another session must win over the current identity map.
    async with AsyncSession(bind=db.bind, expire_on_commit=False, join_transaction_mode="create_savepoint") as writer:
        await writer.execute(update(Connection).where(Connection.id == connection.id).values(active=False))
        await writer.commit()
    assert await resolve_ssh_connection(owner_id) is None
    await db.refresh(connection)
    connection.active = True
    await db.commit()
    await connection_service.set_param(connection.id, "username", "synthetic-new-user")
    refreshed = await resolve_ssh_connection(owner_id)
    assert refreshed is not None and refreshed.username == "synthetic-new-user"
    await connection_service.set_param(connection.id, "username", None)
    with pytest.raises(ValueError):
        await resolve_ssh_connection(owner_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [41, 501])
async def test_executor_availability_batches_agents_and_keeps_effective_host_rules(db, count):
    """Cover the former mocked driver/activation cases through real configuration reads."""
    agents = await owners(db, count=count, driver="hermes")
    tool = await db.scalar(select(Tool).where(Tool.code == "console"))
    connections = [Connection(agent_id=agent.id, tool_id=tool.id, active=True) for agent in agents]
    db.add_all(connections)
    await db.flush()
    db.add_all([ConnectionParam(connection_id=connection.id, param_name="host", param_value="ssh-executor")
                for connection in connections])
    agent_ids = [agent.id for agent in agents]
    connection_ids = [connection.id for connection in connections]
    await db.commit()
    db.expunge_all()
    async with count_queries(db) as statements:
        assert await is_embedded_executor_in_use() is False
    report = {"connections": len(connection_ids), "queries": len(statements)}
    save_report("console-executor-reads" if count == 41 else "console-executor-large-reads", report)

    agent = await db.get(Agent, agent_ids[-1])
    agent.agent_driver = "internal"
    await db.commit()
    assert await is_embedded_executor_in_use() is True
    connection = await db.get(Connection, connection_ids[-1])
    connection.active = False
    await db.commit()
    assert await is_embedded_executor_in_use() is False
    connection.active = True
    agent.soft_delete()
    await db.commit()
    db.expunge_all()
    assert await is_embedded_executor_in_use() is False
    agent = await db.scalar(select(Agent).where(Agent.id == agent_ids[-1]).execution_options(include_historized=True))
    agent.restore()
    tool = await db.scalar(select(Tool).where(Tool.code == "console"))
    tool.global_params = {"host": {"value": "remote.example.com", "forced": True}}
    await db.commit()
    assert await is_embedded_executor_in_use() is False
    tool.global_params = {"host": {"value": "ssh-executor", "forced": True}}
    await db.commit()
    assert await is_embedded_executor_in_use() is True
    tool.global_params = {"host": {"value": "ssh-executor", "forced": False}}
    await db.commit()
    await connection_service.set_param(connection_ids[-1], "host", "remote.example.com")
    assert await is_embedded_executor_in_use() is False
    await connection_service.set_param(connection_ids[-1], "host", "")
    assert await is_embedded_executor_in_use() is True
    await db.execute(update(Connection).where(Connection.id.in_(connection_ids)).values(active=False))
    await db.commit()
    assert await is_embedded_executor_in_use() is False
    assert report["queries"] <= 3 + (count + 499) // 500, report


@pytest.mark.asyncio
async def test_console_discovery_http_permissions_scopes_and_reopening(client):
    password = "synthetic-console-reader-password"
    async with get_db_session() as db:
        privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(
            ["MEMORY_ACCESS", "CONSOLE_ACCESS"],
        )))).all())
        role = Role(code="synthetic-console-reader", privileges=privileges)
        password_hash = encrypt_password(password)
        users = [UserModel(email=f"console-reader-{index}@example.com", is_active=True,
                           hashed_password=password_hash) for index in range(2)]
        title = Title(label="Synthetic HTTP Console", gender="N")
        db.add_all([role, title, *users])
        await db.flush()
        db.add(Assignment(user_id=users[0].id, role_id=role.id, is_default=True))
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-http-console-{index}",
                        first_name="Synthetic", last_name=str(index), agent_driver="internal")
                  for index, user in enumerate(users)]
        db.add_all(agents)
        await db.flush()
        tool = await db.scalar(select(Tool).where(Tool.code == "console"))
        connection = Connection(agent_id=agents[0].id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        db.add_all([ConnectionParam(connection_id=connection.id, param_name=name, param_value=value)
                    for name, value in {
                        "host": "ssh-executor", "username": "synthetic-user",
                        "private_key": "synthetic-private-key", "known_host_key": "synthetic-pinned-key",
                    }.items()])
        owner_id, peer_id, connection_id = agents[0].id, agents[1].id, connection.id
    availability_path = "/api/console/executor/availability"
    schemes_path = "/api/file-share/browser/schemes"
    assert (await client.get(availability_path)).status_code == 401
    assert (await client.get(schemes_path, params={"agent_id": owner_id})).status_code == 401
    headers = []
    for index in range(2):
        login = await client.post("/api/auth/login-json", json={
            "email": f"console-reader-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert (await client.get(availability_path, headers=headers[1])).status_code == 403
    assert (await client.get(schemes_path, params={"agent_id": owner_id}, headers=headers[1])).status_code == 403
    assert (await client.get(schemes_path, params={"agent_id": peer_id}, headers=headers[0])).status_code == 404
    for active in (True, False, True):
        async with get_db_session() as db:
            await db.execute(update(Connection).where(Connection.id == connection_id).values(active=active))
        availability = await client.get(availability_path, headers=headers[0])
        assert availability.status_code == 200 and availability.json() == {"in_use": active}
        first = await client.get(schemes_path, params={"agent_id": owner_id}, headers=headers[0])
        reopened = await client.get(schemes_path, params={"agent_id": owner_id}, headers=headers[0])
        assert first.status_code == reopened.status_code == 200, first.text
        assert first.json() == reopened.json()
        assert ("console" in {item["scheme"] for item in first.json()}) is active
        assert "synthetic-private-key" not in first.text
