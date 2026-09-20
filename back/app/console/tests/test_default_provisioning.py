"""Default consoles are usable, internal-only, and preserve administrator choices."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent import notify_agent_profile
from app.agent.models import Agent, Title
from app.connection import Connection, connection_service
from app.console import provisioning
from app.console.connection_service import resolve_ssh_connection
from app.console.contracts import ConsoleStatus
from app.tools.models import Tool


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "hermes"])
async def test_agent_creation_provisions_only_internal_console(db, monkeypatch, driver):
    title = Title(label="Console defaults", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id, code="console-defaults", first_name="Console",
        last_name="Defaults", agent_driver=driver,
    )
    db.add(agent)
    await db.commit()
    manager = AsyncMock(return_value={"ssh_host_key": "ssh-ed25519 trusted-host-key"})
    monkeypatch.setattr(provisioning.embedded_executor_manager, "request", manager)
    transport = AsyncMock()
    transport.status.return_value = ConsoleStatus(
        reachable=True, authenticated=True, host_key_verified=True,
        home_writable=True, sftp_available=True,
    )
    monkeypatch.setattr(provisioning, "SshExecutionTransport", lambda config: transport)

    await notify_agent_profile(agent.id, "create")

    connection = await db.scalar(
        select(Connection).join(Tool).where(
            Connection.agent_id == agent.id, Tool.code == "console",
        )
    )
    if driver != "internal":
        assert connection is None
        manager.assert_not_awaited()
        return
    assert connection is not None and connection.active
    config = await resolve_ssh_connection(agent.id)
    assert config is not None and config.host == "ssh-executor"
    assert config.username == agent.code
    assert config.known_host_key == "ssh-ed25519 trusted-host-key"
    assert await connection_service.get_disabled_function_names(connection) == set()
    transport.close.assert_awaited_once()
    manager.assert_any_await(
        "ensure_user", agent_id=agent.id, agent_code=agent.code,
        public_key=manager.await_args.kwargs["public_key"],
    )
    _, previous_params = await connection_service.get_params_as_dict(
        connection.id, decrypt_passwords=True,
    )
    stored_key = previous_params["private_key"]
    await connection_service.set_connection_active(connection.id, False)
    manager.reset_mock()

    await notify_agent_profile(agent.id, "create")
    await notify_agent_profile(agent.id, "update")

    await db.refresh(connection)
    assert not connection.active
    _, params = await connection_service.get_params_as_dict(connection.id, decrypt_passwords=True)
    assert params["private_key"] == stored_key
    manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_default_provisioning_keeps_console_inactive(db, monkeypatch):
    title = Title(label="Console unavailable", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id, code="console-unavailable", first_name="Console",
        last_name="Unavailable", agent_driver="internal",
    )
    db.add(agent)
    await db.commit()
    manager = AsyncMock(side_effect=[RuntimeError("executor unavailable"), {}])
    monkeypatch.setattr(provisioning.embedded_executor_manager, "request", manager)

    with pytest.raises(RuntimeError, match="executor unavailable"):
        await provisioning.provision_new_agent_console(agent.id, "create")

    connection = await db.scalar(
        select(Connection).join(Tool).where(
            Connection.agent_id == agent.id, Tool.code == "console",
        )
    )
    assert connection is not None and not connection.active
    manager.assert_any_await("disable_user", agent_id=agent.id)
