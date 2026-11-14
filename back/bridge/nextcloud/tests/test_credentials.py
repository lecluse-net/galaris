from types import SimpleNamespace

import pytest

from bridge.nextcloud.credentials import resolve_nextcloud_connection


@pytest.mark.asyncio
async def test_resolver_uses_messenger_config_independently_from_file_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import connection_service
    from app.services import service

    connection = SimpleNamespace(id=42, agent_id=9, service_id=7, active=True)
    tool = SimpleNamespace(
        code="my-nextcloud",
        file_share=SimpleNamespace(
            service="nextcloud",
            base_url="https://files.test/",
            param_map={"login": "files_username", "password": "files_secret"},
        ),
        messenger=SimpleNamespace(
            service="nextcloud_talk",
            settings={"base_url": "https://talk.test/"},
            param_map={"login": "talk_username", "password": "talk_secret"},
        ),
    )

    async def get_connection(connection_id: int) -> SimpleNamespace:
        assert connection_id == 42
        return connection

    async def get_service_by_id(service_id: int) -> SimpleNamespace:
        assert service_id == 7
        return tool

    async def get_params_as_dict(
        connection_id: int,
        decrypt_passwords: bool = False,
    ) -> tuple[SimpleNamespace, dict[str, str]]:
        assert (connection_id, decrypt_passwords) == (42, True)
        return connection, {
            "files_username": "files-bot",
            "files_secret": "files-password",
            "talk_username": "talk-bot",
            "talk_secret": "talk-password",
        }

    monkeypatch.setattr(connection_service, "get_connection", get_connection)
    monkeypatch.setattr(connection_service, "get_params_as_dict", get_params_as_dict)
    monkeypatch.setattr(service, "get_service_by_id", get_service_by_id)

    config = await resolve_nextcloud_connection(42)

    assert config.base_url == "https://talk.test"
    assert config.login == "talk-bot"
    assert config.password == "talk-password"
    assert config.self_id == "talk-bot"


@pytest.mark.asyncio
async def test_resolver_rejects_a_non_nextcloud_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connection import connection_service
    from app.services import service

    async def get_connection(_connection_id: int) -> SimpleNamespace:
        return SimpleNamespace(id=42, agent_id=9, service_id=7, active=True)

    async def get_service_by_id(_service_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            code="messenger",
            file_share=None,
            messenger=None,
            messenger_config=None,
        )

    monkeypatch.setattr(connection_service, "get_connection", get_connection)
    monkeypatch.setattr(service, "get_service_by_id", get_service_by_id)

    with pytest.raises(ValueError, match="7"):
        await resolve_nextcloud_connection(42)
