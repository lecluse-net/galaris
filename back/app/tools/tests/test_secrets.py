"""Sentinel tests for write-only tool configuration values."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.tools.models import Tool as ToolModel
from app.tools import router as tool_router
from app.tools.secrets import (
    MissingConnectionReference,
    SecretPlaceholderWithoutValue,
    password_default_fields,
    protect_listener_config,
    protect_mcp_config,
    public_connection_schema,
    public_listener_config,
    public_mcp_config,
    resolve_connection_references,
    resolve_mapping_references,
    runtime_listener_config,
    runtime_mcp_config,
)
from core.util import SECRET_MASK, get_encryption_service


_TOKEN = "synthetic-tool-token-never-return"
_HEADER = "synthetic-header-secret-never-return"
_ENV = "synthetic-env-secret-never-return"
_LISTENER = "synthetic-listener-secret-never-return"


def test_mcp_literals_are_encrypted_at_rest_and_write_only() -> None:
    raw = {
        "type": "stdio",
        "command": "demo",
        "auth": {"type": "bearer", "token_static": _TOKEN},
        "headers": {
            "X-Secret": _HEADER,
            "X-Connection": "${connection:api_key}",
        },
        "env": {
            "PRIVATE_VALUE": _ENV,
            "REFERENCED_VALUE": "${connection:password}",
        },
    }

    protected = protect_mcp_config(raw)
    protected_text = repr(protected)
    assert _TOKEN not in protected_text
    assert _HEADER not in protected_text
    assert _ENV not in protected_text

    encryption = get_encryption_service()
    assert encryption.is_encrypted(protected["auth"]["token_static"])
    assert encryption.is_encrypted(protected["headers"]["X-Secret"])
    assert encryption.is_encrypted(protected["env"]["PRIVATE_VALUE"])
    assert protected["headers"]["X-Connection"] == "${connection:api_key}"

    runtime = runtime_mcp_config(protected)
    assert runtime["auth"]["token_static"] == _TOKEN
    assert runtime["headers"]["X-Secret"] == _HEADER
    assert runtime["env"]["PRIVATE_VALUE"] == _ENV

    public = public_mcp_config(protected)
    assert _TOKEN not in repr(public)
    assert _HEADER not in repr(public)
    assert _ENV not in repr(public)
    assert "token_static" not in public["auth"]
    assert public["auth"]["token_static_configured"] is True
    assert public["headers"]["X-Secret"] == SECRET_MASK
    assert public["env"]["PRIVATE_VALUE"] == SECRET_MASK
    assert public["headers"]["X-Connection"] == "${connection:api_key}"


def test_write_only_placeholders_preserve_existing_values() -> None:
    existing = protect_mcp_config({
        "type": "http",
        "auth": {"type": "none"},
        "headers": {"X-Secret": _HEADER},
        "env": {},
    })

    updated = protect_mcp_config(
        {
            "type": "http",
            "auth": {"type": "none"},
            "headers": {"X-Secret": SECRET_MASK},
            "env": {},
        },
        existing=existing,
    )

    assert updated["headers"]["X-Secret"] == existing["headers"]["X-Secret"]
    with pytest.raises(SecretPlaceholderWithoutValue):
        protect_mcp_config({
            "type": "http",
            "auth": {"type": "none"},
            "headers": {"X-New": SECRET_MASK},
            "env": {},
        })


def test_listener_token_is_encrypted_masked_and_removable() -> None:
    protected = protect_listener_config({
        "url": "https://listener.example.test",
        "connection_key": "account",
        "token": _LISTENER,
    })

    assert _LISTENER not in repr(protected)
    assert runtime_listener_config(protected)["token"] == _LISTENER
    assert public_listener_config(protected) == {
        "url": "https://listener.example.test",
        "connection_key": "account",
        "token_configured": True,
    }
    removed = protect_listener_config(
        {
            "url": "https://listener.example.test",
            "connection_key": "account",
            "token": "",
        },
        existing=protected,
    )
    assert removed["token"] is None


def test_connection_references_resolve_only_at_runtime() -> None:
    params = {"api_key": _TOKEN, "login": "alice"}

    assert resolve_connection_references(
        "Bearer ${connection:api_key}",
        params,
    ) == f"Bearer {_TOKEN}"
    assert resolve_mapping_references(
        {"Authorization": "Bearer ${connection:api_key}"},
        params,
    ) == {"Authorization": f"Bearer {_TOKEN}"}
    with pytest.raises(MissingConnectionReference, match="missing"):
        resolve_connection_references("${connection:missing}", params)


def test_password_defaults_are_detected_and_never_projected() -> None:
    schema = {
        "params": {
            "login": {"type": "string", "default": "shared-login"},
            "password": {"type": "password", "default": _TOKEN},
        }
    }

    assert password_default_fields(schema) == ("password",)
    public = public_connection_schema(schema)
    assert public["params"]["login"]["default"] == "shared-login"
    assert public["params"]["password"]["default"] == ""
    assert _TOKEN not in repr(public)


def test_public_tool_projection_contains_presence_flags_only() -> None:
    now = datetime.now(timezone.utc)
    record = ToolModel(
        can_disable=True,
        id=9,
        code="sentinel-public-tool",
        label="Sentinel",
        description="",
        mcp_config=protect_mcp_config({
            "type": "http",
            "url": "https://mcp.example.test",
            "auth": {"type": "bearer", "token_static": _TOKEN},
            "headers": {"X-Secret": _HEADER},
            "env": {},
        }),
        listener_config=protect_listener_config({
            "connection_key": "account",
            "token": _LISTENER,
        }),
        connection_schema={
            "params": {
                "password": {"type": "password", "default": _ENV},
            }
        },
        global_params={
            "password": {"value": _TOKEN, "forced": True},
        },
        created_at=now,
        updated_at=now,
    )
    public = tool_router._to_public(record)
    payload = public.model_dump()
    serialized = public.model_dump_json()

    assert payload["mcp_config"]["auth"]["token_static_configured"] is True
    assert payload["listener_config"]["token_configured"] is True
    assert payload["connection_schema"]["params"]["password"]["default"] == ""
    assert payload["global_params"]["password"] == {
        "value": None,
        "configured": True,
        "secret": True,
        "forced": True,
    }
    for sentinel in (_TOKEN, _HEADER, _ENV, _LISTENER):
        assert sentinel not in serialized
