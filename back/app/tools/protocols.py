"""Mail and Calendar protocols supply ordinary, inherited connection parameters."""

from contextvars import ContextVar, Token
from collections.abc import Collection, Callable, Awaitable
from typing import Any, Literal, cast
import re
from pydantic import BaseModel, ConfigDict, Field


class ProtocolConfig(BaseModel):
    """Presence enables the protocol; credentials remain connection-owned."""

    model_config = ConfigDict(extra="forbid")
    settings: dict[str, str] = Field(default_factory=dict[str, str])
    param_map: dict[str, str] = Field(default_factory=dict[str, str])


_protocol_connection: ContextVar[tuple[str, int, int] | None] = ContextVar("protocol_connection", default=None)
_resource_resolvers: dict[str, Callable[[int, int], Awaitable[int]]] = {}


def register_protocol_resource_resolver(protocol: str, resolver: Callable[[int, int], Awaitable[int]]) -> None:
    _resource_resolvers[protocol] = resolver


def bind_protocol_connection(protocol: str, agent_id: int, connection_id: int) -> Token[tuple[str, int, int] | None]:
    return _protocol_connection.set((protocol, agent_id, connection_id))


def reset_protocol_connection(token: Token[tuple[str, int, int] | None]) -> None:
    _protocol_connection.reset(token)


def current_protocol_connection(protocol: str, agent_id: int) -> int | None:
    value = _protocol_connection.get()
    return value[2] if value and value[:2] == (protocol, agent_id) else None


async def resolve_protocol_connection(agent_id: int, protocol: Literal["mail", "calendar"], requested: int | None = None,
                                      resource_id: int | None = None) -> int:
    from app.connection import connection_service
    from .tool_service import get_tool_by_id

    candidates: list[int] = []
    native: list[int] = []
    if requested is None and resource_id is not None and protocol in _resource_resolvers:
        requested = await _resource_resolvers[protocol](agent_id, resource_id)
    providers: list[str] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active or requested is not None and connection.id != requested:
            continue
        tool = await get_tool_by_id(connection.tool_id)
        if tool is not None and (getattr(tool, protocol) is not None or protocol == "calendar" and tool.code == "agenda"):
            candidates.append(connection.id)
            if tool.code == "agenda" and protocol == "calendar":
                native.append(connection.id)
            label = tool.code
            if protocol == "mail" and tool.mail is not None:
                _, params = await connection_service.get_params_as_dict(connection, decrypt_passwords=False)
                address = params.get(tool.mail.param_map.get("email_address", "email_address"))
                if address:
                    label += f" · {address}"
            providers.append(f"connection_id={connection.id} ({label})")
    if requested is None and len(native) == 1:
        return native[0]
    if len(candidates) != 1:
        choices = "; ".join(providers[:50])
        raise ValueError(f"Select one exact active {protocol} connection using connection_id" +
                         (f". Available providers: {choices}" if choices else ""))
    return candidates[0]


def _param(
    type_: str = "string",
    *,
    required: bool = True,
    default: str = "",
    description: str = "",
    options: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "required": required,
        "default": default,
        "description": description,
        "options": options or [],
    }



def _mail_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "email_address": _param(description="Mailbox email address used as SMTP sender"),
        "password": _param(
            "password",
            description="Mailbox password or application password used by IMAP and SMTP",
        ),
        "imap_host": _param(description="IMAP server DNS name"),
        "imap_port": _param("integer", default="993", description="IMAP server port"),
        "imap_security": _param(
            options=[{"value": "tls"}, {"value": "starttls"}],
            default="tls", description="IMAP transport security: tls or starttls"
        ),
        "allowed_mailboxes": _param(
            required=False,
            default="",
            description="Allowed IMAP folders separated by commas (e.g. INBOX, Projects); empty allows all folders. Exact names; list subfolders separately",
        ),
        "smtp_host": _param(description="SMTP submission server DNS name"),
        "smtp_port": _param("integer", default="465", description="SMTP submission port"),
        "smtp_security": _param(
            options=[{"value": "tls"}, {"value": "starttls"}],
            default="tls", description="SMTP transport security: tls or starttls"
        ),
        "connect_timeout_s": _param(
            "integer", required=False, default="10", description="Connection timeout in seconds"
        ),
        "operation_timeout_s": _param(
            "integer", required=False, default="30", description="I/O timeout in seconds"
        ),
        "poll_interval_s": _param(
            "integer",
            required=False,
            default="60",
            description="Delay between inbox polls in seconds",
        ),
        "max_attachment_mb": _param(
            "integer",
            required=False,
            default="10",
            description="Maximum size of one attachment in megabytes",
        ),
        "max_total_attachment_mb": _param(
            "integer",
            required=False,
            default="20",
            description="Maximum total attachment size per outgoing message in megabytes",
        ),
        "approver_user_id": _param(
            "user",
            required=False,
            description="Human user responsible for approving outgoing messages",
        ),
    }


def _calendar_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "url": _param("password", description="HTTPS CalDAV calendar URL, or iCalendar subscription URL; encrypted because it may contain a private token"),
        "username": _param(required=False, description="Optional HTTP authentication login"),
        "password": _param("password", required=False, description="Optional HTTP authentication password"),
        "label": _param(required=False, description="Calendar label; defaults to the provider label"),
        "owner_label": _param(required=False, description="Human owner of the calendar"),
        "source_kind": _param(required=False, default="caldav", description="External calendar source: caldav or ical subscription",
            options=[{"value": "caldav", "label": "CalDAV"}, {"value": "ical", "label": "iCalendar subscription"}]),
        "timezone": _param(
            required=False,
            default="Europe/Paris",
            description="IANA timezone used to search for available working-hour slots",
        ),
        "workday_start": _param(
            required=False,
            default="09:00",
            description="Default local start of the working day (HH:MM)",
        ),
        "workday_end": _param(
            required=False,
            default="18:00",
            description="Default local end of the working day (HH:MM)",
        ),
        "slot_step_minutes": _param(
            "integer",
            required=False,
            default="15",
            description="Default increment in minutes when searching for free slots",
        ),
    }


def protocol_parameters(protocol: str) -> dict[str, dict[str, Any]]:
    definitions = _mail_connection_params() if protocol == "mail" else _calendar_connection_params()
    if protocol == "mail":
        definitions["allowed_mailboxes"]["widget"] = "mail_folder_tree"
    for order, (name, definition) in enumerate(definitions.items()):
        definition.update(builtin=True, order=order,
            label=f"tools.connectionParamLabels.{name}",
            description=f"tools.connectionParamDescriptions.{protocol}.{name}")
        for option in definition.get("options", []):
            option["label"] = f"tools.connectionParamOptions.{protocol}.{name}.{option['value']}"
    return definitions


def protocol_parameter_bindings(protocol: str) -> dict[str, dict[str, Any]]:
    """Technical roles reference typed connection parameters, never literal credentials."""
    if protocol == "calendar":
        definitions = protocol_parameters(protocol)
        names = ("url", "username", "password", "label", "owner_label")
        return {name: {"parameter": "login" if name == "username" else name, "legacy_parameter": name,
            "label": f"tools.connectionParamLabels.{name}", "definition": definitions[name]} for name in names}
    if protocol != "mail":
        return {}
    definitions = protocol_parameters(protocol)
    roles = {"email_address": ("email_address", "email"), "imap_username": ("email_address", "login"),
        "imap_password": ("password", "password"), "smtp_username": ("email_address", "login"),
        "smtp_password": ("password", "password"), "allowed_mailboxes": ("allowed_mailboxes", "folders"),
        "approver_user_id": ("approver_user_id", "user_id")}
    return {role: {"parameter": suggested, "legacy_parameter": name,
        "label": f"tools.connectionParamLabels.{role}",
        "section": f"tools.protocolSections.{'smtp' if role.startswith('smtp_') or role in {'email_address', 'approver_user_id'} else 'imap'}",
        "definition": {**definitions[name], **({"label": "tools.connectionParamLabels.login", "description": ""} if suggested == "login" else {})}}
        for role, (name, suggested) in roles.items()}


def referenced_protocol_params(*configs: object) -> set[str]:
    """Keep a protocol parameter while another active protocol still references it."""
    names: set[str] = set()
    def visit(value: object) -> None:
        if isinstance(value, str):
            names.add(value)
            names.update(re.findall(r"\$\{connection:([^}]+)\}", value))
        elif isinstance(value, dict):
            for child in cast(dict[object, object], value).values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                visit(child)
    for config in configs:
        visit(config)
    return names


def with_protocol_params(schema: dict[str, Any], *, mail: ProtocolConfig | None, calendar: ProtocolConfig | None,
                         preserve: Collection[str] = ()) -> dict[str, Any]:
    params = dict(schema.get("params") or {})
    original = dict(params)
    for protocol, config in (("mail", mail), ("calendar", calendar)):
        definitions = protocol_parameters(protocol)
        owned_descriptions = {definition["description"] for definition in definitions.values()}
        for name, definition in list(params.items()):
            if definition.get("builtin") and definition.get("description") in owned_descriptions and name not in preserve:
                params.pop(name)
        if config is not None:
            bindings = protocol_parameter_bindings(protocol)
            bound_names = {binding["legacy_parameter"] for binding in bindings.values()}
            fixed = {name: definition for name, definition in definitions.items() if name not in bound_names}
            if config.settings:
                from app.connection.facade import validate_param_value
                if set(config.settings) - set(fixed):
                    raise ValueError(f"Unknown {protocol} Tool setting")
                for name, definition in fixed.items():
                    value = config.settings.get(name, str(definition.get("default") or ""))
                    if definition["required"] and not value.strip():
                        raise ValueError(f"{protocol} requires Tool setting {name}")
                    if value:
                        validate_param_value(definition["type"], value)
                        choices = cast(list[dict[str, str]], definition.get("options") or [])
                        if choices and value not in {option["value"] for option in choices}:
                            raise ValueError(f"Invalid {protocol} Tool setting {name}")
            for name, definition in definitions.items():
                if name in bound_names or config.settings:
                    continue
                # Empty legacy configurations retain their original connection contract.
                params[name] = definition
            mapping = config.param_map
            if protocol == "calendar":
                # Retired execution switches have no effect, including on older Tools.
                retired = {"access_mode", "trigger_on_start", "trigger_on_alarm", "action_kind",
                           "process_workflow_id", "action_instructions"}
                mapping = {name: value for name, value in mapping.items() if name not in retired}
            if set(mapping) - set(bindings):
                raise ValueError(f"Unknown {protocol} connection parameter role")
            used: dict[str, tuple[str, str]] = {}
            for role, binding in bindings.items():
                if protocol == "calendar" and not mapping:
                    # Older providers own CalendarFeed records, not source parameters.
                    continue
                target = mapping.get(role, str(binding["legacy_parameter"]) if not config.settings and not mapping else "")
                if not target and not binding["definition"]["required"]:
                    continue
                if not target.strip() or len(target) > 100:
                    raise ValueError(f"Invalid {protocol} connection parameter reference")
                definition = binding["definition"]
                signature = (str(definition["type"]), str(definition.get("widget") or ""))
                if target in used and used[target] != signature:
                    raise ValueError(f"Incompatible {protocol} roles cannot share a connection parameter")
                used[target] = signature
                current = params.get(target) or original.get(target)
                if current is None and (config.settings or config.param_map):
                    raise ValueError(f"{protocol} maps {role} to unknown connection parameter {target}")
                if current and current.get("type", "string") != definition["type"]:
                    raise ValueError(f"{protocol} parameter {role} must reference a {definition['type']} connection parameter")
                if current and current.get("widget") and current["widget"] != definition.get("widget", ""):
                    raise ValueError("Incompatible Mail connection parameter widget")
                params.setdefault(target, dict(definition))
                if definition.get("widget"):
                    params[target] = {**params[target], "widget": definition["widget"]}
        else:
            for name, definition in definitions.items():
                if name in preserve:
                    # Editors omit software-owned definitions on a full save.
                    # Another protocol still needs the same secret typing.
                    params.setdefault(name, definition)
                elif params.get(name, {}).get("description") == definition["description"]:
                    params.pop(name)
    return {**schema, "params": params}
