"""Resolve one Tool Messenger service with one agent Connection.

The Tool owns server-level bridge settings. The Connection owns only the values
selected through ``param_map``. File sharing and messaging deliberately resolve
their configurations independently even when both select the same bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.params import runtime_settings

from . import facade


@dataclass(frozen=True)
class ResolvedMessengerConfiguration:
    """Server settings and mapped per-agent parameters for one connection."""

    connection_id: int
    agent_id: int
    tool_id: int
    service: str
    settings: dict[str, str]
    params: dict[str, Any]


def _legacy_settings(service: str, tool: Any) -> dict[str, str]:
    """Read the former server-level locations during the upgrade window."""

    if service == "nextcloud_talk":
        file_share = getattr(tool, "file_share", None)
        return {"base_url": str(getattr(file_share, "base_url", "") or "")}
    if service == "matrix":
        return {"homeserver": runtime_settings.MESSENGER_MATRIX_HOMESERVER}
    if service == "whatsapp":
        return {
            "app_secret": runtime_settings.MESSENGER_WHATSAPP_APP_SECRET,
            "verify_token": runtime_settings.MESSENGER_WHATSAPP_VERIFY_TOKEN,
        }
    if service == "one_bot":
        return {"platform": runtime_settings.MESSENGER_ONE_BOT_PLATFORM}
    return {}


def _legacy_param_aliases(service: str, params: dict[str, Any]) -> dict[str, Any]:
    """Normalize historical parameter names to the bridge contract."""

    normalized = dict(params)
    if service == "matrix":
        normalized["token"] = params.get("token") or params.get("access_token") or ""
    elif service == "telegram":
        normalized["token"] = params.get("token") or params.get("bot_token") or ""
    elif service == "one_bot":
        normalized["token"] = params.get("token") or params.get("password") or ""
    return normalized


async def resolve_messenger_configuration(
    connection_id: int,
    *,
    expected_service: str | None = None,
) -> ResolvedMessengerConfiguration:
    """Resolve and validate one Messenger-capable Tool connection."""

    from app.connection import connection_service
    from app.tools import tool_service

    connection = await connection_service.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"Messaging connection {connection_id} was not found.")
    if not connection.active:
        raise ValueError(f"Messaging connection {connection_id} is inactive.")
    tool = await tool_service.get_tool_by_id(int(connection.tool_id))
    if tool is None:
        raise ValueError(f"Messaging Tool {connection.tool_id} was not found.")

    service = facade.kind_for_tool(
        tool,
        preferred_kind=runtime_settings.MESSENGER_DRIVER,
    )
    if service is None:
        raise ValueError(f"Tool {connection.tool_id} has no Messenger service.")
    if expected_service is not None and service != expected_service:
        raise ValueError(
            f"Tool {connection.tool_id} selects Messenger service {service}, "
            f"not {expected_service}."
        )
    spec = facade.get_spec(service)
    if spec is None:
        raise ValueError(f"Messenger service {service} is not registered.")

    _, raw_params = await connection_service.get_params_as_dict(
        connection.id,
        decrypt_passwords=True,
    )
    messenger = getattr(tool, "messenger", None)
    if messenger is None:
        settings = _legacy_settings(service, tool)
        resolved_params = _legacy_param_aliases(service, raw_params)
    else:
        settings = dict(messenger.settings)
        resolved_params = dict(raw_params)
        for definition in spec.connection_params:
            connection_name = str(messenger.param_map.get(definition.name) or "")
            value = raw_params.get(connection_name) if connection_name else None
            if (value is None or value == "") and definition.required:
                raise ValueError(
                    f"Messenger service {service} requires mapped connection "
                    f"parameter {definition.name}."
                )
            resolved_params[definition.name] = value if value is not None else ""

    for definition in spec.tool_params:
        value = settings.get(definition.name, "")
        if definition.required and not value:
            raise ValueError(
                f"Messenger service {service} requires Tool setting {definition.name}."
            )

    return ResolvedMessengerConfiguration(
        connection_id=int(connection.id),
        agent_id=int(connection.agent_id),
        tool_id=int(connection.tool_id),
        service=service,
        settings=settings,
        params=resolved_params,
    )


__all__ = [
    "ResolvedMessengerConfiguration",
    "resolve_messenger_configuration",
]
