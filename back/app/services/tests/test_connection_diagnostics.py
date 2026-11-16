"""Saved credential diagnostics do not activate connections or change their policies."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.agent.models import Agent, Title
from app.connection import Connection, connection_service
from app.services import connection_diagnostics as diagnostics
from app.services.models import Service
from app.services.permission_catalog import agent_permission_catalog


@pytest.mark.asyncio
@pytest.mark.parametrize("unrelated", [0, 500])
async def test_saved_mcp_credentials_inactive_connection_and_scoped_permissions(db, monkeypatch, unrelated):
    title = Title(label="Synthetic diagnostic", gender="X")
    tool = Service(code=f"diagnostic_{uuid4().hex}", label="Synthetic diagnostic",
        mcp_config={"type": "http", "url": "https://synthetic.example.test/mcp"},
        connection_schema={"params": {"token": {"type": "password"}}})
    db.add_all([title, tool]); await db.flush()
    agent = Agent(title_id=title.id, code=f"diagnostic-{uuid4().hex}", first_name="Synthetic", last_name="Diagnostic", agent_driver="internal")
    db.add(agent); await db.flush()
    connection = Connection(service_id=tool.id, agent_id=agent.id, active=False)
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
    other = Service(code=f"other_diagnostic_{uuid4().hex}", label="Other synthetic diagnostic", mcp_config=tool.mcp_config)
    db.add(other); await db.flush()
    db.add(Connection(service_id=other.id, agent_id=agent.id, active=True)); await db.flush()
    scoped_discovery = AsyncMock(return_value=[("lookup", "Synthetic lookup", "tool")])
    monkeypatch.setattr("app.services.permission_catalog.list_external_mcp_capabilities", scoped_discovery)
    prefix = f"synthetic-unconnected-{uuid4().hex}"
    db.add_all([Service(code=f"{prefix}-{index}", label="Synthetic unrelated configuration",
        description="Synthetic unrelated configuration. " * 4096) for index in range(unrelated)])
    await db.commit()
    agent_id, connection_id = agent.id, connection.id
    db.expunge_all()
    materialized = []

    def loaded(_session, record):
        if isinstance(record, Service) and record.code.startswith(prefix):
            materialized.append(len(record.description.encode()))

    event.listen(Session, "loaded_as_persistent", loaded)
    try:
        catalog = await agent_permission_catalog(agent_id, connection_id=connection_id)
    finally:
        event.remove(Session, "loaded_as_persistent", loaded)
    print(f"PERMISSION_CATALOG unrelated={unrelated} materialized={len(materialized)} bytes={sum(materialized)}")
    assert not materialized, "A connection permission view must not load unrelated Service configurations"
    assert [row.connection_id for row in catalog.connections] == [connection_id]
    assert scoped_discovery.await_count == 1
    assert [(row.name, row.connection_state, row.effective_state) for row in catalog.capabilities] == [("lookup", "disabled", "disabled")]
    assert not catalog.unavailable_catalogs
    # The same session can retain an old Service object. Reopening the scoped
    # inventory must expose current metadata and retain the disabled policy.
    retained = await db.get(Service, tool.id)
    assert retained is not None and retained.label == "Synthetic diagnostic"
    await db.execute(update(Service).where(Service.id == tool.id).values(
        label="Synthetic current diagnostic").execution_options(synchronize_session=False))
    reopened = await agent_permission_catalog(agent_id, connection_id=connection_id)
    assert reopened.connections[0].service_label == "Synthetic current diagnostic"
    assert reopened.capabilities[0].connection_state == "disabled"
    scoped_discovery.reset_mock()
    missing = await agent_permission_catalog(agent_id, connection_id=connection_id + 1_000_000)
    assert not missing.connections and not missing.capabilities and not missing.unavailable_catalogs
    scoped_discovery.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_protocol_diagnostics_report_failure_and_unsupported(db, monkeypatch):
    title = Title(label="Synthetic mixed diagnostic", gender="X")
    tool = Service(code=f"mixed_{uuid4().hex}", label="Synthetic mixed diagnostic",
        mcp_config={"type": "http", "url": "https://synthetic.example.test/mcp"},
        mail_config={}, rest_config={"base_url": "https://synthetic.example.test/api"},
        messenger_config={"service": "matrix"},
        file_share_config={"service": "nextcloud", "base_url": "https://synthetic.example.test/files"})
    db.add_all([title, tool]); await db.flush()
    agent = Agent(title_id=title.id, code=f"mixed-{uuid4().hex}", first_name="Synthetic", last_name="Mixed", agent_driver="internal")
    db.add(agent); await db.flush()
    connection = Connection(service_id=tool.id, agent_id=agent.id, active=True)
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
