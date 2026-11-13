"""Functional Tool capabilities and their single selected technical protocol."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field


CONFIG_FIELDS = {
    "mcp": "mcp_config", "api": "rest_config", "file_share": "file_share_config",
    "messenger": "messenger_config", "listener": "listener_config",
    "mail": "mail_config", "calendar": "calendar_config",
}
STANDARD_PROTOCOLS: dict[str, tuple[str, ...]] = {
    "mcp": ("http", "sse", "stdio"), "api": ("rest",),
    "file_share": ("affine", "nextcloud", "samba"),
    "messenger": ("matrix", "nextcloud_talk", "one_bot", "telegram", "whatsapp"),
    "listener": ("webhook",), "mail": ("imap_smtp",), "calendar": ("caldav",),
}


class CapabilityProtocol(BaseModel):
    value: str
    capability: str
    label: str
    builtin: bool = True
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict[str, dict[str, Any]])
    connection_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict[str, dict[str, Any]])


class CapabilityDefinition(BaseModel):
    code: str
    label: str
    builtin: bool = True
    protocols: list[CapabilityProtocol] = Field(default_factory=list[CapabilityProtocol])


def capability_code(value: str) -> str:
    """Unknown identifiers stay opaque; their final segment is the functional key."""
    return value.rsplit(".", 1)[-1]


def validate_capabilities(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if len(values) > 100:
        raise ValueError("A Tool supports at most 100 capability selections")
    normalized = [value.strip() for value in values]
    if any(not value or len(value) > 255 for value in normalized):
        raise ValueError("Capability identifiers must contain between 1 and 255 characters")
    if len({capability_code(value) for value in normalized}) != len(normalized):
        raise ValueError("Select only one protocol for each Tool capability")
    return normalized


def capabilities_from_values(values: Mapping[str, Any]) -> list[str]:
    selections: list[str] = []
    for capability, field in CONFIG_FIELDS.items():
        config = values.get(field)
        if config is None:
            continue
        if capability == "mcp":
            protocol = str(config.get("type") or "")
        elif capability in {"file_share", "messenger"}:
            protocol = str(config.get("service") or "")
        else:
            protocol = STANDARD_PROTOCOLS[capability][0]
        if protocol:
            selections.append(f"{protocol}.{capability}")
    return selections


def configuration_values(record: Any) -> dict[str, Any]:
    return {field: getattr(record, field, None) for field in CONFIG_FIELDS.values()}


def effective_capabilities(record: Any) -> list[str]:
    """Read older producers while the additive column is being adopted."""
    return list(getattr(record, "capabilities", None) or capabilities_from_values(configuration_values(record)))


def resolve_selections(
    values: dict[str, Any], declared: list[str] | None,
    *, previous: Sequence[str] = (), previous_values: Mapping[str, Any] | None = None,
) -> list[str]:
    """Bridge legacy configuration writes and the explicit string-list contract.

    The list selects the protocol; the existing typed configuration fields retain
    execution settings and the established write-only secret behavior.
    """
    if declared is None:
        previous_concrete = set(capabilities_from_values(previous_values or {}))
        concrete = capabilities_from_values(values)
        occupied = {capability_code(value) for value in concrete}
        return concrete + [value for value in previous
            if value not in previous_concrete and capability_code(value) not in occupied]
    declared = validate_capabilities(declared) or []
    selected = {capability_code(value): value for value in declared}
    for capability, field in CONFIG_FIELDS.items():
        value = selected.get(capability)
        if value is None:
            values[field] = None
            continue
        if values.get(field) is None and value in {"imap_smtp.mail", "caldav.calendar"}:
            values[field] = {}
        actual = capabilities_from_values({field: values.get(field)})
        if actual and actual != [value]:
            raise ValueError(f"Configuration does not match selected capability {value}")
        if not actual and value in {f"{protocol}.{capability}" for protocol in STANDARD_PROTOCOLS[capability]}:
            raise ValueError(f"Configuration is required for selected capability {value}")
    return declared


def supported_capabilities() -> list[CapabilityDefinition]:
    """Advertise standard choices and installed bridge extensions without enums."""
    from app.file_share import available_bridges
    from app.messenger import all_specs
    from .protocols import protocol_parameters, protocol_parameter_bindings

    parameter_sets = {"imap_smtp.mail": protocol_parameters("mail"), "caldav.calendar": protocol_parameters("calendar")}

    definitions = {code: CapabilityDefinition(code=code, label=f"tools.capabilityLabels.{code}")
                   for code in CONFIG_FIELDS}
    dynamic = {
        "file_share": [(bridge.service, bridge.label) for bridge in available_bridges()],
        "messenger": [(spec.kind, spec.label or spec.kind) for spec in all_specs() if spec.kind not in {"mail", "internal"}],
    }
    for capability, definition in definitions.items():
        protocols = dynamic.get(capability, [(protocol, protocol) for protocol in STANDARD_PROTOCOLS[capability]])
        for protocol, label in protocols:
            builtin = protocol in STANDARD_PROTOCOLS[capability]
            bindings = protocol_parameter_bindings(capability)
            connection_names = {binding["legacy_parameter"] for binding in bindings.values()}
            parameters = {name: value for name, value in parameter_sets.get(f"{protocol}.{capability}", {}).items()
                if name not in connection_names}
            if capability == "mail":
                parameters = {name: {**value, "section": f"tools.protocolSections.{'smtp' if name.startswith(('smtp_', 'max_')) else 'imap'}"}
                    for name, value in parameters.items()}
            definition.protocols.append(CapabilityProtocol(value=f"{protocol}.{capability}", capability=capability,
                label=f"tools.protocolLabels.{protocol}" if builtin else label, builtin=builtin,
                parameters=parameters, connection_parameters=bindings))
    return list(definitions.values())
