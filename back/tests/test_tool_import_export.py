from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from app.tools import ConnectionParamDef, ConnectionSchema, ToolCreate, tool_service
from app.tools.models import Tool as ToolModel
from app.tools.secrets import runtime_listener_config, runtime_mcp_config


_STATIC_TOKEN = "synthetic-static-token-never-export"
_HEADER_SECRET = "synthetic-header-never-export"
_ENV_SECRET = "synthetic-env-never-export"
_LISTENER_TOKEN = "synthetic-listener-token-never-export"
_PASSWORD_DEFAULT = "synthetic-password-default-never-export"


def _complete_tool(*, tool_id: int | None = None) -> ToolModel:
    return ToolModel(
        id=tool_id,
        code="cloud-docs",
        label="Documents partages",
        description="A complete tool",
        mcp_config={
            "type": "http",
            "url": "https://mcp.example.test",
            "auth": {"type": "bearer", "token_static": _STATIC_TOKEN},
            "headers": {"X-Private": _HEADER_SECRET},
            "env": {"PRIVATE_ENV": _ENV_SECRET},
        },
        file_share_config={
            "service": "nextcloud",
            "base_url": "https://cloud.example.test",
            "param_map": {"login": "nc_login", "password": "nc_password"},
        },
        listener_config={
            "url": "https://hooks.example.test",
            "token": _LISTENER_TOKEN,
            "connection_key": "account",
        },
        connection_schema={
            "params": {
                "nc_login": {
                    "type": "string",
                    "required": True,
                    "default": "",
                    "description": "Login Nextcloud",
                },
                "nc_password": {
                    "type": "password",
                    "required": True,
                    "default": _PASSWORD_DEFAULT,
                    "description": "Nextcloud password",
                },
            }
        },
        task_config={
            "label": "Synchroniser",
            "objective": "Copy ${file}",
        },
    )


def test_export_contains_configuration_but_no_write_only_value():
    serialized = tool_service.serialize_to_yaml(_complete_tool())
    exported = yaml.safe_load(serialized)

    assert exported["mcp_config"]["url"] == "https://mcp.example.test"
    assert exported["mcp_config"]["auth"]["token_static"] == "********"
    assert "token_static_configured" not in exported["mcp_config"]["auth"]
    assert exported["mcp_config"]["headers"]["X-Private"] == "********"
    assert exported["mcp_config"]["env"]["PRIVATE_ENV"] == "********"
    assert exported["file_share_config"] == {
        "service": "nextcloud",
        "base_url": "https://cloud.example.test",
        "param_map": {"login": "nc_login", "password": "nc_password"},
    }
    assert exported["listener_config"]["connection_key"] == "account"
    assert exported["listener_config"]["token"] == "********"
    assert "token_configured" not in exported["listener_config"]
    assert set(exported["connection_schema"]["params"]) == {
        "nc_login",
        "nc_password",
    }
    assert exported["connection_schema"]["params"]["nc_password"]["default"] == ""
    assert exported["task_config"]["objective"] == "Copy ${file}"
    for sentinel in (
        _STATIC_TOKEN,
        _HEADER_SECRET,
        _ENV_SECRET,
        _LISTENER_TOKEN,
        _PASSWORD_DEFAULT,
    ):
        assert sentinel not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["http", "https", "workspace", "messenger", "galaris"])
async def test_create_rejects_reserved_tool_codes_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    db = MagicMock()
    monkeypatch.setattr(tool_service, "get_db", lambda: db)

    with pytest.raises(ValueError, match="reserved"):
        await tool_service.create_tool(ToolCreate(code=code, label="Reserved"))

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_file_share_tool_code_must_be_uri_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import FileShareConfig

    db = MagicMock()
    monkeypatch.setattr(tool_service, "get_db", lambda: db)
    data = ToolCreate(
        code="cloud_docs",
        label="Invalid file provider",
        file_share_config=FileShareConfig(
            service="nextcloud",
            base_url="https://cloud.example.test",
        ),
    )

    with pytest.raises(ValueError, match="lowercase URI scheme"):
        await tool_service.create_tool(data)

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_import_overwrite_replaces_every_configuration(monkeypatch):
    existing = _complete_tool(tool_id=42)
    db = AsyncMock()
    db.get.return_value = existing

    async def get_existing(code: str):
        assert code == "cloud-docs"
        return existing

    monkeypatch.setattr(tool_service, "get_db", lambda: db)
    monkeypatch.setattr(tool_service, "get_tool_record", get_existing)

    content = """
code: cloud-docs
label: New file share
file_share_config:
  service: grav
  base_url: https://grav.example.test
  param_map:
    api_key: grav_key
connection_schema:
  params:
    grav_key:
      type: password
      required: true
      description: Grav API key
"""
    record, created = await tool_service.import_from_yaml_string(content, overwrite=True)

    assert created is False
    assert record is existing
    assert existing.label == "New file share"
    assert existing.description == ""
    assert existing.file_share_config == {
        "service": "grav",
        "base_url": "https://grav.example.test",
        "param_map": {"api_key": "grav_key"},
    }
    assert existing.connection_schema["params"]["grav_key"]["type"] == "password"
    # Overwrite removes previous values that are absent from the YAML document.
    assert existing.mcp_config is None
    assert existing.listener_config is None
    assert existing.task_config is None
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(existing)


@pytest.mark.asyncio
async def test_redacted_export_can_overwrite_existing_secrets_without_losing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _complete_tool(tool_id=43)
    db = AsyncMock()
    db.get.return_value = existing

    async def get_existing(code: str):
        assert code == "cloud-docs"
        return existing

    monkeypatch.setattr(tool_service, "get_db", lambda: db)
    monkeypatch.setattr(tool_service, "get_tool_record", get_existing)

    content = tool_service.serialize_to_yaml(existing)
    record, created = await tool_service.import_from_yaml_string(
        content,
        overwrite=True,
    )

    assert created is False
    assert record is existing
    assert existing.mcp_config is not None
    assert existing.listener_config is not None
    runtime_mcp = runtime_mcp_config(existing.mcp_config)
    assert runtime_mcp["auth"]["token_static"] == _STATIC_TOKEN
    assert runtime_mcp["headers"]["X-Private"] == _HEADER_SECRET
    assert runtime_mcp["env"]["PRIVATE_ENV"] == _ENV_SECRET
    assert runtime_listener_config(existing.listener_config)["token"] == (
        _LISTENER_TOKEN
    )


@pytest.mark.asyncio
async def test_create_rejects_shared_password_default_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    monkeypatch.setattr(tool_service, "get_db", lambda: db)
    data = ToolCreate(
        code="unsafe-default",
        label="Unsafe default",
        connection_schema=ConnectionSchema(
            params={
                "api_key": ConnectionParamDef(
                    type="password",
                    default=_PASSWORD_DEFAULT,
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="api_key"):
        await tool_service.create_tool(data)

    db.add.assert_not_called()
