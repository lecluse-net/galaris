"""Resolve and connect streaming file transports for Galaris agents.

External shares are configured like MCP servers: a Tool selects one or more capabilities and each
agent supplies credentials through a connection. Resource URI schemes always use that Tool's
code; Messenger and file sharing are capability-specific transports behind the same namespace.
"""

from __future__ import annotations

from typing import Any

from app.connection import connection_service
from app.tools import tool_service
from app.tools import FileShareConfig, Tool
from core.i18n import render_prompt, t

from .bridges import get_bridge
from .interface import connected_resource_transport, resource_transport_factory
from .messenger_transport import MessengerFileTransport
from .transport import FileTransport, ShareableFileTransport


def _message(key: str, language: str | None = None, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}", language), **values)


def _has_messenger_files(tool: Tool) -> bool:
    """Return whether the Tool's Messenger bridge exposes file resources."""

    if tool.messenger is None:
        return False
    from app.messenger import Capability, get_spec

    spec = get_spec(tool.messenger.service)
    return spec is not None and Capability.FILES in spec.capabilities


def build_client(
    config: FileShareConfig,
    params: dict[str, object],
    *,
    language: str | None = None,
) -> FileTransport:
    """Build a service client from tool configuration and agent parameters."""
    bridge = get_bridge(config.service, language=language)
    resolved: dict[str, str] = {}
    for param in bridge.params:
        conn_name = (config.param_map or {}).get(param.key, "")
        value = params.get(conn_name) if conn_name else None
        if not value:
            if param.required:
                raise ValueError(_message(
                    "required_parameter",
                    language,
                    service=config.service,
                    parameter=param.key,
                    connection_parameter=conn_name or "none",
                ))
            continue
        resolved[param.key] = str(value)
    return bridge.build(config.base_url, resolved)


async def _resolve_tool_config(
    agent_id: int,
    tool_code: str,
    *,
    language: str | None = None,
) -> tuple[FileShareConfig, dict[str, object]]:
    """Resolve a connected file-sharing tool configuration for an agent."""
    connections = await connection_service.get_connections_by_agent(agent_id)
    for connection in connections:
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if not tool or tool.code != tool_code or not tool.file_share:
            continue
        _, params = await connection_service.get_params_as_dict(
            connection, decrypt_passwords=True
        )
        return tool.file_share, params
    raise ValueError(_message(
        "connection_not_found",
        language,
        tool_code=tool_code,
        agent_id=agent_id,
    ))


async def _resolve_connected_tool(
    agent_id: int,
    tool_code: str,
    *,
    language: str | None = None,
) -> tuple[Any, Tool]:
    """Resolve one active agent connection and its exact Tool code."""

    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool is not None and tool.code == tool_code:
            return connection, tool
    raise ValueError(_message(
        "connection_not_found",
        language,
        tool_code=tool_code,
        agent_id=agent_id,
    ))


async def _resolve_client_by_bridge_service(
    agent_id: int,
    service: str,
    *,
    language: str | None = None,
) -> FileTransport:
    """Resolve the first active client using a bridge service."""
    connections = await connection_service.get_connections_by_agent(agent_id)
    for connection in connections:
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if not tool or not tool.file_share or tool.file_share.service != service:
            continue
        _, params = await connection_service.get_params_as_dict(
            connection, decrypt_passwords=True
        )
        return build_client(tool.file_share, params, language=language)
    raise ValueError(_message(
        "service_connection_not_found",
        language,
        service=service,
        agent_id=agent_id,
    ))


async def list_tool_codes(agent_id: int) -> list[str]:
    """List active Tool codes carrying file-share or Messenger resources."""
    tool_codes: list[str] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool and (tool.file_share is not None or _has_messenger_files(tool)):
            tool_codes.append(tool.code)
    return sorted(set(tool_codes))


async def list_services(agent_id: int) -> list[str]:
    """Return connected file-sharing tool codes."""
    return await list_tool_codes(agent_id)


async def describe_targets(
    agent_id: int,
    *,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Describe available file-sharing targets for an agent."""
    targets: list[dict[str, Any]] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if not tool:
            continue
        if tool.code == "console":
            # console:// is a native provider. Its file-share configuration marks the Tool's
            # capability in the catalog but is described by resource_service with the complete
            # SSH-home capability matrix.
            continue
        has_messenger = _has_messenger_files(tool)
        if tool.file_share is None and not has_messenger:
            continue
        targets.append({
            "code": tool.code,
            "service": tool.file_share.service if tool.file_share else "messenger",
            "label": tool.label or tool.code,
            "description": tool.description or "",
            "has_file_share": tool.file_share is not None,
            "has_messenger": has_messenger,
        })
    return sorted(targets, key=lambda target: target["code"])


async def resolve_resource_transport_with_service(
    agent_id: int,
    tool_code: str,
    locator: str,
    *,
    language: str | None = None,
) -> tuple[FileTransport, str]:
    """Resolve a resource transport from Tool code and provider locator.

    A Tool carrying only Messenger always uses its messaging bridge. When it also carries a
    file-share capability, a first locator segment matching one of that connection's known rooms
    selects Messenger; all other paths select the file-share bridge.
    """

    if tool_code == "console":
        return await resolve_transport_with_service(
            agent_id,
            tool_code,
            language=language,
        )

    connection, tool = await _resolve_connected_tool(
        agent_id,
        tool_code,
        language=language,
    )
    if specialized := connected_resource_transport(tool.code, agent_id):
        return specialized, tool.code
    if _has_messenger_files(tool):
        from app.messenger import (
            messenger_for_agent_connection,
            messenger_room_locator_known,
        )

        room_locator = locator.strip("/").partition("/")[0]
        messenger_selected = tool.file_share is None or await messenger_room_locator_known(
            int(connection.id),
            room_locator,
        )
        if messenger_selected:
            messenger = await messenger_for_agent_connection(
                agent_id,
                int(connection.id),
            )
            return MessengerFileTransport(messenger, language=language), "messenger"
    if tool.file_share is None:
        raise ValueError(_message(
            "connection_not_found",
            language,
            tool_code=tool_code,
            agent_id=agent_id,
        ))
    _, params = await connection_service.get_params_as_dict(
        connection,
        decrypt_passwords=True,
    )
    return build_client(tool.file_share, params, language=language), tool.file_share.service


# =============================================================================
# Standard streaming transport resolution.
# =============================================================================

async def resolve_transport_with_service(
    agent_id: int,
    tool_code: str,
    *,
    language: str | None = None,
) -> tuple[FileTransport, str]:
    """Build a file-sharing tool transport and return its bridge service name."""
    if tool_code == "image":
        from app.image import ImageFileTransport

        return ImageFileTransport(), "image"
    if tool_code == "console":
        from app.console import build_run_resource

        return (await build_run_resource(agent_id)).files, "console"
    if factory := resource_transport_factory(tool_code):
        # Resolve first so an inactive or missing Mail account cannot be used as a
        # resource provider merely because the built-in Tool exists.
        await _resolve_connected_tool(agent_id, tool_code, language=language)
        return factory(agent_id), tool_code

    config, params = await _resolve_tool_config(
        agent_id, tool_code, language=language
    )
    return build_client(config, params, language=language), config.service


async def resolve_transport(
    agent_id: int,
    tool_code: str,
    *,
    language: str | None = None,
) -> FileTransport:
    """Build the ``FileTransport`` for an agent's tool code."""
    transport, _service = await resolve_transport_with_service(
        agent_id, tool_code, language=language
    )
    return transport


async def resolve_transport_by_service(
    agent_id: int,
    service: str,
    *,
    language: str | None = None,
) -> FileTransport:
    """Build a transport from a bridge service name."""
    if service == "image":
        from app.image import ImageFileTransport

        return ImageFileTransport()
    if service == "console":
        from app.console import build_run_resource

        return (await build_run_resource(agent_id)).files
    if factory := resource_transport_factory(service):
        await _resolve_connected_tool(agent_id, service, language=language)
        return factory(agent_id)
    return await _resolve_client_by_bridge_service(
        agent_id, service, language=language
    )


async def share(
    agent_id: int,
    remote: str,
    permissions: int = 1,
    share_with: str = "",
    *,
    language: str | None = None,
) -> str:
    """Create a public or user Nextcloud share and return its URL."""
    client = await _resolve_client_by_bridge_service(
        agent_id, "nextcloud", language=language
    )
    if not isinstance(client, ShareableFileTransport):
        raise ValueError(_message("nextcloud_only", language))
    return await client.share(remote, permissions=permissions, share_with=share_with or None)
