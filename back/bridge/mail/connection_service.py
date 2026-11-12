"""Resolve immutable Mail configuration from encrypted agent connections."""

from __future__ import annotations

import re
import json
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


def _allowed_mailboxes(params: dict[str, Any]) -> tuple[str, ...]:
    raw = str(params.get("allowed_mailboxes") or "")
    if raw.lstrip().startswith("["):
        try:
            values: object = json.loads(raw)
        except ValueError as exc:
            raise ValueError("Invalid Mail allowed_mailboxes parameter") from exc
        if not isinstance(values, list):
            raise ValueError("Invalid Mail allowed_mailboxes parameter")
        entries = cast(list[object], values)
        if any(not isinstance(name, str) or not name for name in entries):
            raise ValueError("Invalid Mail allowed_mailboxes parameter")
        names = tuple(dict.fromkeys(cast(list[str], entries)))
    else:
        names = tuple(dict.fromkeys(name.strip() for name in raw.split(",") if name.strip()))
    if len(names) > 500 or any(
        len(name) > 512 or re.search(r"[\x00-\x1f\x7f]", name) for name in names
    ):
        raise ValueError("Invalid Mail allowed_mailboxes parameter")
    return names


async def _config_from_connection(
    connection: Connection,
    *,
    require_active: bool,
) -> MailConnectionConfig:
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    if tool is None or tool.mail is None:
        raise ValueError("Connection is not a Mail connection")
    if require_active and not connection.active:
        raise ValueError("Mail connection is inactive")
    _, params = await connection_service.get_params_as_dict(
        connection,
        decrypt_passwords=True,
    )
    bindings = tool.mail.param_map
    settings = tool.mail.settings or params
    email_address = _required(params, bindings.get("email_address", "email_address"))
    # The common function policy owns new approvals. Historical deliveries retain
    # their approval_required snapshot and their original approval workflow.
    approval_required = False
    approver_user_id = _optional_user_id(params, bindings.get("approver_user_id", "approver_user_id"))
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
            resource_scheme=tool.code,
            resource_prefix=("mail/" if tool.file_share and tool.file_share.service != "mail" else "") + f"account/{connection.id}/",
            email_address=email_address,
            display_name="",
            agent_label=agent_label,
            imap=MailEndpointConfig(
                host=_required(settings, "imap_host"),
                port=_number(settings, "imap_port", 993, 1, 65535),
                security=_security(settings, "imap_security"),
                username=_required(params, bindings.get("imap_username", "email_address")),
                password=SecretStr(_required(params, bindings.get("imap_password", "password"))),
            ),
            smtp=MailEndpointConfig(
                host=_required(settings, "smtp_host"),
                port=_number(settings, "smtp_port", 465, 1, 65535),
                security=_security(settings, "smtp_security"),
                username=_required(params, bindings.get("smtp_username", "email_address")),
                password=SecretStr(_required(params, bindings.get("smtp_password", "password"))),
            ),
            sent_mailbox=None,
            trash_mailbox=None,
            allowed_mailboxes=_allowed_mailboxes({"allowed_mailboxes": params.get(bindings.get("allowed_mailboxes", "allowed_mailboxes"))}),
            connect_timeout_s=float(_number(settings, "connect_timeout_s", 10, 1, 60)),
            operation_timeout_s=float(_number(settings, "operation_timeout_s", 30, 1, 120)),
            poll_interval_s=float(
                _number(settings, "poll_interval_s", 60, 5, 86_400)
            ),
            max_attachment_bytes=_megabytes(
                settings, "max_attachment_mb", 10, 25
            ),
            max_total_attachment_bytes=_megabytes(
                settings, "max_total_attachment_mb", 20, 50
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
    from app.tools import current_protocol_connection, resolve_protocol_connection
    selected = current_protocol_connection("mail", agent_id)
    if selected is None:
        selected = await resolve_protocol_connection(agent_id, "mail")
    config = await resolve_connection(selected, require_active=True)
    if config.agent_id != agent_id:
        raise ValueError("Mail connection belongs to another agent")
    return config


__all__ = ["resolve_connection", "resolve_mail_connection"]
