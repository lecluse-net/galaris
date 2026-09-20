"""Protection and resolution of secret-bearing tool configuration."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any, cast

from core.util import SECRET_MASK, get_encryption_service


_CONNECTION_REFERENCE_RE = re.compile(
    r"\$\{connection:([A-Za-z0-9_.-]+)\}"
)


class SecretPlaceholderWithoutValue(ValueError):
    """A write-only placeholder cannot be resolved without an existing value."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class MissingConnectionReference(ValueError):
    """A configured secret reference has no value on the current connection."""

    def __init__(self, parameter: str) -> None:
        super().__init__(parameter)
        self.parameter = parameter


def is_connection_reference(value: str) -> bool:
    """Return whether a value is a single connection parameter reference."""
    return _CONNECTION_REFERENCE_RE.fullmatch(value) is not None


def _encrypt_literal(value: str) -> str:
    if not value or is_connection_reference(value):
        return value
    encryption = get_encryption_service()
    return value if encryption.is_encrypted(value) else encryption.encrypt(value)


def _protect_value(
    value: str,
    *,
    existing: str | None,
    field: str,
) -> str:
    if value == SECRET_MASK:
        if existing is None:
            raise SecretPlaceholderWithoutValue(field)
        return _encrypt_literal(existing)
    return _encrypt_literal(value)


def _runtime_value(value: str) -> str:
    if not value or is_connection_reference(value):
        return value
    encryption = get_encryption_service()
    return encryption.decrypt(value) if encryption.is_encrypted(value) else value


def _public_value(value: str) -> str:
    if not value or is_connection_reference(value):
        return value
    return SECRET_MASK


def _protect_mapping(
    values: Mapping[str, str],
    *,
    existing: Mapping[str, str],
    field: str,
) -> dict[str, str]:
    return {
        key: _protect_value(
            value,
            existing=existing.get(key),
            field=f"{field}.{key}",
        )
        for key, value in values.items()
    }


def protect_mcp_config(
    config: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Encrypt static MCP values while preserving write-only placeholders."""
    protected = copy.deepcopy(dict(config))
    previous = dict(existing or {})
    auth = cast(dict[str, Any], protected.get("auth") or {})
    previous_auth = cast(dict[str, Any], previous.get("auth") or {})
    token = auth.get("token_static")
    previous_token = previous_auth.get("token_static")
    if token is None and previous_token:
        auth["token_static"] = previous_token
    elif isinstance(token, str):
        auth["token_static"] = (
            None
            if token == ""
            else _protect_value(
                token,
                existing=(
                    str(previous_token)
                    if isinstance(previous_token, str)
                    else None
                ),
                field="mcp_config.auth.token_static",
            )
        )
    protected["auth"] = auth

    for name in ("headers", "env"):
        values = cast(dict[str, str], protected.get(name) or {})
        previous_values = cast(dict[str, str], previous.get(name) or {})
        protected[name] = _protect_mapping(
            values,
            existing=previous_values,
            field=f"mcp_config.{name}",
        )
    return protected


def runtime_mcp_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return an in-memory MCP configuration with static values decrypted."""
    runtime = copy.deepcopy(dict(config))
    auth = cast(dict[str, Any], runtime.get("auth") or {})
    token = auth.get("token_static")
    if isinstance(token, str):
        auth["token_static"] = _runtime_value(token)
    runtime["auth"] = auth
    for name in ("headers", "env"):
        values = cast(dict[str, str], runtime.get(name) or {})
        runtime[name] = {key: _runtime_value(value) for key, value in values.items()}
    return runtime


def public_mcp_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return MCP metadata without any literal static value."""
    public = copy.deepcopy(dict(config))
    auth = cast(dict[str, Any], public.get("auth") or {})
    token = auth.pop("token_static", None)
    auth["token_static_configured"] = bool(token)
    public["auth"] = auth
    for name in ("headers", "env"):
        values = cast(dict[str, str], public.get(name) or {})
        public[name] = {key: _public_value(value) for key, value in values.items()}
    return public


def export_mcp_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a redacted YAML shape that cannot silently lose a static token."""
    exported = public_mcp_config(config)
    auth = cast(dict[str, Any], exported.get("auth") or {})
    configured = bool(auth.pop("token_static_configured", False))
    if configured:
        auth["token_static"] = SECRET_MASK
    exported["auth"] = auth
    return exported


def protect_listener_config(
    config: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Encrypt the legacy listener token without exposing it to readers."""
    protected = copy.deepcopy(dict(config))
    previous = dict(existing or {})
    token = protected.get("token")
    previous_token = previous.get("token")
    if token is None and previous_token:
        protected["token"] = previous_token
    elif isinstance(token, str):
        protected["token"] = (
            None
            if token == ""
            else _protect_value(
                token,
                existing=(
                    str(previous_token)
                    if isinstance(previous_token, str)
                    else None
                ),
                field="listener_config.token",
            )
        )
    return protected


def runtime_listener_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return an internal listener configuration with its token decrypted."""
    runtime = copy.deepcopy(dict(config))
    token = runtime.get("token")
    if isinstance(token, str):
        runtime["token"] = _runtime_value(token)
    return runtime


def public_listener_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return listener metadata and credential presence only."""
    public = copy.deepcopy(dict(config))
    token = public.pop("token", None)
    public["token_configured"] = bool(token)
    return public


def export_listener_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a redacted YAML shape that preserves a legacy-token placeholder."""
    exported = public_listener_config(config)
    configured = bool(exported.pop("token_configured", False))
    if configured:
        exported["token"] = SECRET_MASK
    return exported


def protect_messenger_config(
    config: Mapping[str, Any],
    *,
    secret_fields: frozenset[str],
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Encrypt server-level Messenger secrets declared by the selected bridge."""

    protected = copy.deepcopy(dict(config))
    previous = dict(existing or {})
    settings = cast(dict[str, str], protected.get("settings") or {})
    previous_settings = cast(dict[str, str], previous.get("settings") or {})
    for name in secret_fields:
        value = settings.get(name)
        previous_value = previous_settings.get(name)
        if value is None and previous_value:
            settings[name] = previous_value
        elif isinstance(value, str):
            settings[name] = _protect_value(
                value,
                existing=previous_value,
                field=f"messenger_config.settings.{name}",
            )
    protected["settings"] = settings
    return protected


def runtime_messenger_config(
    config: Mapping[str, Any],
    *,
    secret_fields: frozenset[str],
) -> dict[str, Any]:
    """Decrypt Messenger server secrets for bridge construction."""

    runtime = copy.deepcopy(dict(config))
    settings = cast(dict[str, str], runtime.get("settings") or {})
    for name in secret_fields:
        value = settings.get(name)
        if isinstance(value, str):
            settings[name] = _runtime_value(value)
    runtime["settings"] = settings
    return runtime


def public_messenger_config(
    config: Mapping[str, Any],
    *,
    secret_fields: frozenset[str],
) -> dict[str, Any]:
    """Mask Messenger server secrets in API responses."""

    public = copy.deepcopy(dict(config))
    settings = cast(dict[str, str], public.get("settings") or {})
    for name in secret_fields:
        value = settings.get(name)
        if isinstance(value, str):
            settings[name] = _public_value(value)
    public["settings"] = settings
    return public


def export_messenger_config(
    config: Mapping[str, Any],
    *,
    secret_fields: frozenset[str],
) -> dict[str, Any]:
    """Return a redacted, re-importable Messenger configuration."""

    return public_messenger_config(config, secret_fields=secret_fields)


def public_connection_schema(config: Mapping[str, Any]) -> dict[str, Any]:
    """Clear defaults of password parameters before API or YAML serialization."""
    public = copy.deepcopy(dict(config))
    params = cast(dict[str, dict[str, Any]], public.get("params") or {})
    for definition in params.values():
        if definition.get("type") == "password":
            definition["default"] = ""
    return public


def password_default_fields(config: Mapping[str, Any]) -> tuple[str, ...]:
    """List password parameters that contain a forbidden shared default."""
    params = cast(dict[str, dict[str, Any]], config.get("params") or {})
    return tuple(
        sorted(
            name
            for name, definition in params.items()
            if definition.get("type") == "password"
            and bool(definition.get("default"))
        )
    )


def resolve_connection_references(
    value: str,
    connection_params: Mapping[str, Any],
) -> str:
    """Substitute ``${connection:name}`` from decrypted connection parameters."""

    def replace(match: re.Match[str]) -> str:
        parameter = match.group(1)
        resolved = connection_params.get(parameter)
        if resolved is None or resolved == "":
            raise MissingConnectionReference(parameter)
        return str(resolved)

    return _CONNECTION_REFERENCE_RE.sub(replace, value)


def resolve_mapping_references(
    values: Mapping[str, str],
    connection_params: Mapping[str, Any],
) -> dict[str, str]:
    """Resolve every connection reference in a static header or environment map."""
    return {
        key: resolve_connection_references(value, connection_params)
        for key, value in values.items()
    }
