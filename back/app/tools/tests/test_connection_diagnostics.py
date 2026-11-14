"""Saved credential diagnostics do not activate connections or change their policies."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.models import Agent, Title
from app.connection import Connection, connection_service
from app.tools import connection_diagnostics as diagnostics
from app.tools.models import Tool
from app.tools.permission_catalog import agent_permission_catalog


@pytest.mark.asyncio
async def test_saved_mcp_credentials_inactive_connection_and_scoped_permissions(db, monkeypatch):
    title = Title(label="Synthetic diagnostic", gender="X")
    tool = Tool(code=f"diagnostic_{uuid4().hex}", label="Synthetic diagnostic",
        mcp_config={"type": "http", "url": "https://synthetic.example.test/mcp"},
        connection_schema={"params": {"token": {"type": "password"}}})
    db.add_all([title, tool]); await db.flush()
    agent = Agent(title_id=title.id, code=f"diagnostic-{uuid4().hex}", first_name="Synthetic", last_name="Diagnostic", agent_driver="internal")
    db.add(agent); await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=False)
    db.add(connection); await db.flush()
    await connection_service.set_param(connection.id, "token", "synthetic-secret")
    await connection_service.set_connection_function_state(connection.id, "lookup", "disabled")
    discover = AsyncMock(return_value=[])
    monkeypatch.setattr(diagnostics, "list_external_mcp_capabilities", discover)
    result = await diagnostics.test_saved_connection(connection.id)
    assert result.status == "success"  # A live, empty MCP catalogue is valid.
    assert discover.call_args.args[1]["token"] == "synthetic-secret"
    assert "synthetic-secret" not in result.model_dump_json()
    assert connection.active is False
    assert (await connection_service.list_function_states(connection.id))[0].state == "disabled"
    discover.side_effect = RuntimeError("https://synthetic.example.test/?token=synthetic-secret")
    failed = await diagnostics.test_saved_connection(connection.id)
    assert failed.status == "error"
    assert "synthetic-secret" not in failed.model_dump_json()
    # The scoped editor discovers even an inactive account, without other accounts.
    other = Tool(code=f"other_diagnostic_{uuid4().hex}", label="Other synthetic diagnostic", mcp_config=tool.mcp_config)
    db.add(other); await db.flush()
    db.add(Connection(tool_id=other.id, agent_id=agent.id, active=True)); await db.flush()
    scoped_discovery = AsyncMock(return_value=[("lookup", "Synthetic lookup", "tool")])
    monkeypatch.setattr("app.tools.permission_catalog.list_external_mcp_capabilities", scoped_discovery)
    catalog = await agent_permission_catalog(agent.id, connection_id=connection.id)
    assert [row.connection_id for row in catalog.connections] == [connection.id]
    assert scoped_discovery.await_count == 1
    assert [(row.name, row.connection_state, row.effective_state) for row in catalog.capabilities] == [("lookup", "disabled", "disabled")]
    assert not catalog.unavailable_catalogs


@pytest.mark.asyncio
async def test_mixed_protocol_diagnostics_report_failure_and_unsupported(db, monkeypatch):
    title = Title(label="Synthetic mixed diagnostic", gender="X")
    tool = Tool(code=f"mixed_{uuid4().hex}", label="Synthetic mixed diagnostic",
        mcp_config={"type": "http", "url": "https://synthetic.example.test/mcp"},
        mail_config={}, rest_config={"base_url": "https://synthetic.example.test/api"},
        messenger_config={"service": "matrix"},
        file_share_config={"service": "nextcloud", "base_url": "https://synthetic.example.test/files"})
    db.add_all([title, tool]); await db.flush()
    agent = Agent(title_id=title.id, code=f"mixed-{uuid4().hex}", first_name="Synthetic", last_name="Mixed", agent_driver="internal")
    db.add(agent); await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection); await db.flush()
    monkeypatch.setattr(diagnostics, "list_external_mcp_capabilities", AsyncMock(return_value=[]))
    probe = AsyncMock(return_value=False)
    monkeypatch.setitem(diagnostics._probes, "mail", probe)
    messenger_probe = AsyncMock(return_value=True)
    monkeypatch.setitem(diagnostics._probes, "messenger", messenger_probe)
    monkeypatch.setitem(diagnostics._probes, "file_share", AsyncMock(return_value=True))
    result = await diagnostics.test_saved_connection(connection.id)
    assert result.status == "error"
    assert {row.protocol: row.status for row in result.checks} == {
        "mcp": "success", "mail": "error", "rest": "unsupported", "messenger": "success", "file_share": "success"}
    probe.assert_awaited_once_with(connection.id)
    probe.return_value = True
    assert (await diagnostics.test_saved_connection(connection.id)).status == "unsupported"
    connection.active = False
    await db.flush()
    inactive = await diagnostics.test_saved_connection(connection.id)
    messaging = next(row for row in inactive.checks if row.protocol == "messenger")
    assert messaging.status == "unsupported"
    assert messenger_probe.await_count == 2
