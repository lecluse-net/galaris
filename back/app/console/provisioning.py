"""Provision the embedded SSH console for internal agents."""

from __future__ import annotations

import asyncssh
from loguru import logger

from app.agent import Agent, get_agent_record
from app.connection import connection_service
from app.tools import tool_service

from .connection_service import resolve_connection
from .keys import generate_ed25519_keypair
from .manager import embedded_executor_manager
from .schemas import EmbeddedProvisionResult
from .ssh_client import SshExecutionTransport


async def provision_embedded_console(agent: Agent) -> EmbeddedProvisionResult:
    if agent.agent_driver != "internal":
        raise ValueError("SSH console provisioning is available only with the internal harness")
    tool = await tool_service.get_tool_record("console")
    if tool is None:
        raise RuntimeError("The built-in console tool has not been synchronized yet")
    tool_id = tool.id
    connection = await connection_service.get_or_create_connection(tool_id, agent.id)
    _, previous_params = await connection_service.get_params_as_dict(
        connection.id,
        decrypt_passwords=True,
    )
    previous_active = connection.active and all(
        previous_params.get(name)
        for name in ("host", "username", "private_key", "known_host_key")
    )
    await connection_service.set_connection_active(connection.id, False)

    private_key, public_key = generate_ed25519_keypair()
    params: dict[str, str | None] = {
        "host": "ssh-executor",
        "port": "22",
        "username": agent.code,
        "private_key": private_key,
        "private_key_passphrase": None,
        "known_host_key": "",
        "connect_timeout_s": "10",
        "command_timeout_s": "300",
    }
    try:
        health = await embedded_executor_manager.request("health")
        host_key = str(health.get("ssh_host_key") or "").strip()
        if not host_key:
            raise RuntimeError("The embedded executor exposes no SSH host key")
        params["known_host_key"] = host_key
        await embedded_executor_manager.request(
            "ensure_user",
            agent_id=agent.id,
            agent_code=agent.code,
            public_key=public_key,
        )
        await connection_service.set_params_bulk(connection.id, params)
        transport = SshExecutionTransport(await resolve_connection(connection.id))
        try:
            result = await transport.status()
        finally:
            await transport.close()
        if not (
            result.authenticated
            and result.host_key_verified
            and result.home_writable
            and result.sftp_available
        ):
            raise RuntimeError(result.error or "Embedded SSH self-test failed")
        await connection_service.set_connection_active(connection.id, True)
    except Exception as exc:
        try:
            if previous_params:
                restored_params = {
                    name: str(value) if value is not None else None
                    for name, value in previous_params.items()
                }
                await connection_service.set_params_bulk(connection.id, restored_params)
                if previous_params.get("host") == "ssh-executor":
                    previous_key = asyncssh.import_private_key(
                        str(previous_params.get("private_key") or ""),
                        passphrase=(
                            str(previous_params["private_key_passphrase"])
                            if previous_params.get("private_key_passphrase")
                            else None
                        ),
                    )
                    previous_public = previous_key.export_public_key().decode("ascii").strip()
                    await embedded_executor_manager.request(
                        "ensure_user",
                        agent_id=agent.id,
                        agent_code=agent.code,
                        public_key=previous_public,
                    )
                    if not previous_active:
                        await embedded_executor_manager.request(
                            "disable_user",
                            agent_id=agent.id,
                        )
                else:
                    await embedded_executor_manager.request(
                        "disable_user",
                        agent_id=agent.id,
                    )
                await connection_service.set_connection_active(
                    connection.id,
                    previous_active,
                )
            else:
                await embedded_executor_manager.request("disable_user", agent_id=agent.id)
        except Exception:
            logger.exception(
                "Embedded executor compensation failed for agent {} connection {}",
                agent.id,
                connection.id,
            )
        raise RuntimeError(str(exc)) from exc
    return EmbeddedProvisionResult(
        connection_id=connection.id,
        agent_id=agent.id,
        agent_code=agent.code,
        public_key=public_key,
        status=result,
    )



async def provision_new_agent_console(agent_id: int, action: str) -> None:
    """Create the default internal console once, preserving existing connections."""
    if action != "create":
        return
    agent = await get_agent_record(agent_id)
    if agent is None or agent.agent_driver != "internal":
        return
    tool = await tool_service.get_tool_record("console")
    if tool is None:
        raise RuntimeError("The built-in console tool has not been synchronized yet")
    if await connection_service.get_connection_by_agent_tool(tool.id, agent.id) is not None:
        return
    await provision_embedded_console(agent)
