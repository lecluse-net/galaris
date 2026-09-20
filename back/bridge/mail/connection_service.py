"""Resolve immutable Mail configuration from encrypted agent connections."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import SecretStr, ValidationError

from app.agent import get_agent_record
from app.connection import Connection, connection_service
from app.tools import tool_service
from core.user import user_service

from .contracts import MailConnectionConfig, MailEndpointConfig, MailSecurity


BYTES_PER_MEGABYTE = 1024 * 1024


def _required(params: dict[str, Any], name: str) -> str:
    value = str(params.get(name) or "").strip()
    if not value:
        raise ValueError(f"Required Mail connection parameter is missing: {name}")
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"Invalid control character in Mail parameter: {name}")
    return value


def _number(
    params: dict[str, Any],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = params.get(name)
    try:
        value = default if raw in (None, "") else int(str(raw))
    except ValueError as exc:
        raise ValueError(f"Invalid numeric Mail parameter: {name}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"Mail parameter {name} must be between {minimum} and {maximum}")
    return value


def _security(params: dict[str, Any], name: str) -> MailSecurity:
    value = str(params.get(name) or "tls").strip().lower()
    if value not in {"tls", "starttls"}:
        raise ValueError(f"Mail parameter {name} must be tls or starttls")
    return cast(MailSecurity, value)


def _boolean(params: dict[str, Any], name: str, default: bool) -> bool:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    value = str(raw).strip().casefold()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Mail parameter {name} must be true or false")


def _optional_user_id(params: dict[str, Any], name: str) -> int | None:
    raw = params.get(name)
    if raw in (None, ""):
        return None
    return _number(params, name, 0, 1, 2_147_483_647)


def _megabytes(
    params: dict[str, Any],
    name: str,
    default: int,
    maximum: int,
) -> int:
    return _number(params, name, default, 1, maximum) * BYTES_PER_MEGABYTE


async def _config_from_connection(
    connection: Connection,
    *,
    require_active: bool,
) -> MailConnectionConfig:
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is None or tool.code != "mail":
        raise ValueError("Connection is not a Mail connection")
    if require_active and not connection.active:
        raise ValueError("Mail connection is inactive")
    _, params = await connection_service.get_params_as_dict(
        connection,
        decrypt_passwords=True,
    )
    email_address = _required(params, "email_address")
    password = _required(params, "password")
    approval_required = _boolean(params, "approval_required", False)
    approver_user_id = _optional_user_id(params, "approver_user_id")
    if approval_required and approver_user_id is None:
        raise ValueError("Mail approval requires a responsible approver user")
    if approver_user_id is not None:
        approver = await user_service.get_user_by_id(approver_user_id)
        if approver is None or not approver.is_active:
            raise ValueError("Mail approver user does not exist or is inactive")
    agent = await get_agent_record(connection.agent_id)
    agent_label = (
        " ".join((agent.first_name, agent.last_name)).strip()
        if agent is not None
        else f"Agent {connection.agent_id}"
    )
    try:
        return MailConnectionConfig(
            connection_id=connection.id,
            agent_id=connection.agent_id,
            email_address=email_address,
            display_name="",
            agent_label=agent_label,
            imap=MailEndpointConfig(
                host=_required(params, "imap_host"),
                port=_number(params, "imap_port", 993, 1, 65535),
                security=_security(params, "imap_security"),
                username=email_address,
                password=SecretStr(password),
            ),
            smtp=MailEndpointConfig(
                host=_required(params, "smtp_host"),
                port=_number(params, "smtp_port", 465, 1, 65535),
                security=_security(params, "smtp_security"),
                username=email_address,
                password=SecretStr(password),
            ),
            sent_mailbox=None,
            trash_mailbox=None,
            connect_timeout_s=float(_number(params, "connect_timeout_s", 10, 1, 60)),
            operation_timeout_s=float(_number(params, "operation_timeout_s", 30, 1, 120)),
            poll_interval_s=float(
                _number(params, "poll_interval_s", 60, 5, 86_400)
            ),
            max_attachment_bytes=_megabytes(
                params, "max_attachment_mb", 10, 25
            ),
            max_total_attachment_bytes=_megabytes(
                params, "max_total_attachment_mb", 20, 50
            ),
            approval_required=approval_required,
            approver_user_id=approver_user_id,
        )
    except ValidationError as exc:
        raise ValueError("Invalid Mail connection configuration") from exc


async def resolve_connection(
    connection_id: int,
    *,
    require_active: bool = False,
) -> MailConnectionConfig:
    connection = await connection_service.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"Connection {connection_id} not found")
    return await _config_from_connection(connection, require_active=require_active)


async def resolve_mail_connection(agent_id: int) -> MailConnectionConfig:
    for connection in await connection_service.get_connections_by_agent(agent_id):
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool is not None and tool.code == "mail" and connection.active:
            return await _config_from_connection(connection, require_active=True)
    raise ValueError("No active Mail connection is configured for this agent")


__all__ = ["resolve_connection", "resolve_mail_connection"]
