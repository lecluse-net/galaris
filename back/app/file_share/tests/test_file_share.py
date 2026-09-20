from types import SimpleNamespace

import pytest

from app.file_share import file_share_service, available_bridges
from app.tools.schemas import (
    ConnectionSchema,
    FileShareConfig,
    MessengerConfig,
    Tool,
)
from bridge.affine import AffineFileClient
from bridge.grav import GravFileClient
from bridge.nextcloud import NextcloudFileClient


def test_available_bridges_lists_builtin():
    services = {b.service for b in available_bridges()}
    assert services == {"nextcloud", "grav", "affine"}
    nc = next(b for b in available_bridges() if b.service == "nextcloud")
    assert nc.supports_share is True
    assert {p.key for p in nc.params} == {"login", "password"}


def test_build_client_nextcloud_via_param_map():
    cfg = FileShareConfig(
        service="nextcloud",
        base_url="https://cloud.example.com",
        param_map={"login": "nc_login", "password": "nc_pw"},
    )
    client = file_share_service.build_client(cfg, {"nc_login": "alice", "nc_pw": "secret"})
    assert isinstance(client, NextcloudFileClient)
    assert client.username == "alice"
    assert client.password == "secret"
    assert client._webdav_url("Documents/report.txt") == (  # pyright: ignore[reportPrivateUsage]
        "https://cloud.example.com/remote.php/dav/files/alice/Documents/report.txt"
    )


def test_build_client_grav():
    cfg = FileShareConfig(
        service="grav", base_url="https://grav.example.com", param_map={"api_key": "k"}
    )
    client = file_share_service.build_client(cfg, {"k": "key123"})
    assert isinstance(client, GravFileClient)
    assert client.api_key == "key123"
    assert client.upload_path == "/api/v1/pages/{page}/media"


def test_build_client_grav_custom_upload_path():
    cfg = FileShareConfig(
        service="grav",
        base_url="https://grav.example.com",
        param_map={"api_key": "k", "upload_path": "grav_upload"},
    )
    client = file_share_service.build_client(cfg, {"k": "key123", "grav_upload": "galaris/media"})
    assert isinstance(client, GravFileClient)
    assert client.upload_path == "/galaris/media"


def test_build_client_grav_default_page():
    cfg = FileShareConfig(
        service="grav",
        base_url="https://grav.example.com",
        param_map={"api_key": "k", "default_page": "page"},
    )
    client = file_share_service.build_client(cfg, {"k": "key123", "page": "acceuil"})
    assert isinstance(client, GravFileClient)
    assert client.default_page == "acceuil"


def test_build_client_affine():
    # The workspace is not a connection parameter: each upload/download call prefixes it
    # to the path.
    cfg = FileShareConfig(
        service="affine",
        base_url="https://affine.example.com",
        param_map={"email": "mail", "password": "pw"},
    )
    client = file_share_service.build_client(
        cfg, {"mail": "max@example.com", "pw": "secret"}
    )
    assert isinstance(client, AffineFileClient)
    assert client.email == "max@example.com"
    assert client.password == "secret"


def test_build_client_missing_required_param_raises():
    # The password is mapped but absent from the connection parameters.
    cfg = FileShareConfig(
        service="nextcloud",
        base_url="https://x",
        param_map={"login": "l", "password": "p"},
    )
    with pytest.raises(ValueError):
        file_share_service.build_client(cfg, {"l": "alice"})


def test_build_client_unmapped_required_param_raises():
    # The password is not mapped at all.
    cfg = FileShareConfig(service="nextcloud", base_url="https://x", param_map={"login": "l"})
    with pytest.raises(ValueError):
        file_share_service.build_client(cfg, {"l": "alice"})


def test_build_client_unknown_service_raises():
    cfg = FileShareConfig(service="dropbox", base_url="https://x", param_map={})
    with pytest.raises(ValueError):
        file_share_service.build_client(cfg, {})


@pytest.mark.asyncio
async def test_resolve_transport_uses_tool_code(monkeypatch):
    cfg = FileShareConfig(
        service="nextcloud",
        base_url="https://cloud.example.com",
        param_map={"login": "nc_login", "password": "nc_pw"},
    )
    tool = Tool(
        code="cloud_docs",
        label="Cloud docs",
        file_share_config=cfg,
        connection_schema=ConnectionSchema(),
    )
    connection = SimpleNamespace(active=True, tool_id=42)

    async def get_connections_by_agent(agent_id: int):
        assert agent_id == 7
        return [connection]

    async def get_tool_by_id(tool_id: int):
        assert tool_id == 42
        return tool

    async def get_params_as_dict(connection_arg, decrypt_passwords: bool = False):
        assert connection_arg is connection
        assert decrypt_passwords is True
        return connection_arg, {"nc_login": "alice", "nc_pw": "secret"}

    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_connections_by_agent",
        get_connections_by_agent,
    )
    monkeypatch.setattr(file_share_service.tool_service, "get_tool_by_id", get_tool_by_id)
    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_params_as_dict",
        get_params_as_dict,
    )

    transport, service = await file_share_service.resolve_transport_with_service(7, "cloud_docs")

    assert service == "nextcloud"
    assert isinstance(transport, NextcloudFileClient)
    assert transport.username == "alice"
    with pytest.raises(ValueError):
        await file_share_service.resolve_transport(7, "nextcloud")
    with pytest.raises(ValueError):
        await file_share_service.resolve_transport(7, "messenger")


@pytest.mark.asyncio
async def test_messenger_without_files_does_not_expose_a_resource_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module

    tool = Tool(
        code="text-only",
        label="Text only",
        messenger_config=MessengerConfig(service="text_only"),
        connection_schema=ConnectionSchema(),
    )
    connection = SimpleNamespace(id=73, active=True, tool_id=42)

    async def connections(_agent_id: int) -> list[object]:
        return [connection]

    async def get_tool(_tool_id: int) -> Tool:
        return tool

    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_connections_by_agent",
        connections,
    )
    monkeypatch.setattr(file_share_service.tool_service, "get_tool_by_id", get_tool)
    monkeypatch.setattr(
        messenger_module,
        "get_spec",
        lambda _service: SimpleNamespace(capabilities=set()),
    )

    assert await file_share_service.list_tool_codes(7) == []
    assert await file_share_service.describe_targets(7) == []
    with pytest.raises(ValueError):
        await file_share_service.resolve_resource_transport_with_service(
            7,
            "text-only",
            "room/file-id",
        )


@pytest.mark.asyncio
async def test_console_file_share_capability_remains_one_native_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.console as console_module

    tool = Tool(
        code="console",
        label="Console SSH",
        file_share_config=FileShareConfig(service="console", base_url=""),
        connection_schema=ConnectionSchema(),
    )
    connection = SimpleNamespace(active=True, tool_id=42)

    async def connections(_agent_id: int) -> list[object]:
        return [connection]

    async def get_tool(_tool_id: int) -> Tool:
        return tool

    files = object()

    async def build_run_resource(agent_id: int) -> SimpleNamespace:
        assert agent_id == 7
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_connections_by_agent",
        connections,
    )
    monkeypatch.setattr(file_share_service.tool_service, "get_tool_by_id", get_tool)
    monkeypatch.setattr(console_module, "build_run_resource", build_run_resource)

    assert await file_share_service.list_tool_codes(7) == ["console"]
    assert await file_share_service.describe_targets(7) == []
    transport, service = await file_share_service.resolve_transport_with_service(
        7,
        "console",
    )
    assert transport is files
    assert service == "console"


@pytest.mark.asyncio
async def test_resource_transport_selects_messenger_capability_by_known_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module

    cfg = FileShareConfig(
        service="nextcloud",
        base_url="https://cloud.example.com",
        param_map={"login": "login", "password": "password"},
    )
    tool = Tool(
        code="nextcloud",
        label="Nextcloud",
        file_share_config=cfg,
        messenger_config=MessengerConfig(service="nextcloud_talk"),
        connection_schema=ConnectionSchema(),
    )
    connection = SimpleNamespace(id=73, active=True, tool_id=42)
    messenger = SimpleNamespace(tool_code="nextcloud")

    async def connections(_agent_id: int) -> list[object]:
        return [connection]

    async def get_tool(_tool_id: int) -> Tool:
        return tool

    async def known_room(connection_id: int, room_locator: str) -> bool:
        assert connection_id == 73
        return room_locator == "talk-token"

    async def resolve_messenger(agent_id: int, connection_id: int) -> object:
        assert (agent_id, connection_id) == (7, 73)
        return messenger

    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_connections_by_agent",
        connections,
    )
    monkeypatch.setattr(file_share_service.tool_service, "get_tool_by_id", get_tool)
    monkeypatch.setattr(
        messenger_module,
        "messenger_room_locator_known",
        known_room,
    )
    monkeypatch.setattr(
        messenger_module,
        "messenger_for_agent_connection",
        resolve_messenger,
    )

    transport, service = await file_share_service.resolve_resource_transport_with_service(
        7,
        "nextcloud",
        "talk-token/file-uuid",
    )

    assert service == "messenger"
    assert isinstance(transport, file_share_service.MessengerFileTransport)


@pytest.mark.asyncio
async def test_resource_transport_uses_file_share_for_non_room_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.messenger as messenger_module

    cfg = FileShareConfig(
        service="nextcloud",
        base_url="https://cloud.example.com",
        param_map={"login": "login", "password": "password"},
    )
    tool = Tool(
        code="nextcloud",
        label="Nextcloud",
        file_share_config=cfg,
        messenger_config=MessengerConfig(service="nextcloud_talk"),
        connection_schema=ConnectionSchema(),
    )
    connection = SimpleNamespace(id=73, active=True, tool_id=42)

    async def connections(_agent_id: int) -> list[object]:
        return [connection]

    async def get_tool(_tool_id: int) -> Tool:
        return tool

    async def unknown_room(_connection_id: int, _room: str) -> bool:
        return False

    async def params(
        connection_arg: object,
        decrypt_passwords: bool = False,
    ) -> tuple[object, dict[str, str]]:
        assert decrypt_passwords is True
        return connection_arg, {"login": "alice", "password": "secret"}

    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_connections_by_agent",
        connections,
    )
    monkeypatch.setattr(
        file_share_service.tool_service,
        "get_tool_by_id",
        get_tool,
    )
    monkeypatch.setattr(
        messenger_module,
        "messenger_room_locator_known",
        unknown_room,
    )
    monkeypatch.setattr(
        file_share_service.connection_service,
        "get_params_as_dict",
        params,
    )

    transport, service = await file_share_service.resolve_resource_transport_with_service(
        7,
        "nextcloud",
        "Shared/report.pdf",
    )

    assert service == "nextcloud"
    assert isinstance(transport, NextcloudFileClient)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["resolve_transport_with_service", "resolve_transport_by_service", "resolve_resource_transport_with_service"])
async def test_registered_transport_is_never_constructed_without_active_connection(monkeypatch, entrypoint):
    from unittest.mock import AsyncMock, Mock
    from app.file_share import interface
    factory = Mock()
    monkeypatch.setattr(interface, "_resource_transports", {"custom": factory})
    monkeypatch.setattr(file_share_service, "_resolve_connected_tool", AsyncMock(side_effect=PermissionError("inactive")))
    method = getattr(file_share_service, entrypoint)
    args = [1, "custom"] + (["attachment"] if entrypoint == "resolve_resource_transport_with_service" else [])
    with pytest.raises(PermissionError):
        await method(*args)
    factory.assert_not_called()
