from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.connection import connection_service
from app.messenger import service
from app.messenger.interface import BridgeSpec
from app.messenger.models import Capability, MessengerUser


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("messenger_kind", "expected_resolved"),
    [("matrix", True), ("telegram", False)],
)
async def test_task_messaging_keeps_exact_connection_and_platform(
    monkeypatch: pytest.MonkeyPatch,
    messenger_kind: str,
    expected_resolved: bool,
) -> None:
    connection = SimpleNamespace(id=73, agent_id=7, tool_id=9, active=True)
    messenger = SimpleNamespace(kind=messenger_kind)
    get_connection = AsyncMock(return_value=connection)
    monkeypatch.setattr(
        connection_service,
        "get_connection",
        get_connection,
    )
    monkeypatch.setattr(
        connection_service,
        "get_params_as_dict",
        AsyncMock(return_value=(connection, {"user_id": "@agent:example.test"})),
    )
    monkeypatch.setattr(
        service.facade,
        "get_messenger",
        AsyncMock(return_value=messenger),
    )
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        messenger_connection_id=73,
        message_platform="matrix",
        data={},
    )

    resolved, self_id = await service.resolve_task_messaging(task)

    assert (resolved is not None) is expected_resolved
    assert self_id == "@agent:example.test"
    get_connection.assert_awaited_once_with(73)


@pytest.mark.asyncio
async def test_task_messaging_rejects_another_agents_pinned_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(id=73, agent_id=99, tool_id=9, active=True)
    monkeypatch.setattr(
        connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    from app.tools import tool_service

    get_tool_record = AsyncMock(return_value=SimpleNamespace(id=9))
    monkeypatch.setattr(tool_service, "get_tool_record", get_tool_record)
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        messenger_connection_id=73,
        message_platform="matrix",
        data={},
    )

    resolved, self_id = await service.resolve_task_messaging(task)

    assert resolved is None
    assert self_id is None
    get_tool_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_messaging_rejects_inactive_pinned_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(id=73, agent_id=7, tool_id=9, active=False)
    monkeypatch.setattr(
        connection_service,
        "get_connection",
        AsyncMock(return_value=connection),
    )
    get_messenger = AsyncMock()
    monkeypatch.setattr(service.facade, "get_messenger", get_messenger)
    task = SimpleNamespace(
        id=uuid4(),
        agent_id=7,
        messenger_connection_id=73,
        message_platform="matrix",
        data={},
    )

    resolved, self_id = await service.resolve_task_messaging(task)

    assert resolved is None
    assert self_id is None
    get_messenger.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_messenger_does_not_choose_between_active_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import tool_service

    connections = [
        SimpleNamespace(id=17, agent_id=7, tool_id=3, active=True),
        SimpleNamespace(id=29, agent_id=7, tool_id=4, active=True),
    ]
    tools = {
        3: SimpleNamespace(
            code="custom-telegram",
            messenger=SimpleNamespace(service="telegram"),
        ),
        4: SimpleNamespace(
            code="custom-matrix",
            messenger=SimpleNamespace(service="matrix"),
        ),
    }
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_agent",
        AsyncMock(return_value=connections),
    )
    monkeypatch.setattr(
        tool_service,
        "get_tool_by_id",
        AsyncMock(side_effect=lambda tool_id: tools[tool_id]),
    )
    monkeypatch.setattr(service.facade, "is_kind_enabled", lambda _kind: True)
    monkeypatch.setattr(service.facade, "get_factory", lambda _kind: object)
    get_messenger = AsyncMock()
    monkeypatch.setattr(service.facade, "get_messenger", get_messenger)

    resolved = await service.messenger_for_agent(7)

    assert resolved is None
    get_messenger.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_search_combines_every_connection_without_collapsing_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.messenger import directory
    from app.tools import tool_service

    telegram = SimpleNamespace(id=17, agent_id=7, tool_id=3, active=True)
    matrix = SimpleNamespace(id=29, agent_id=7, tool_id=4, active=True)
    tools = {
        3: SimpleNamespace(
            code="custom-telegram",
            messenger=SimpleNamespace(service="telegram"),
        ),
        4: SimpleNamespace(
            code="custom-matrix",
            messenger=SimpleNamespace(service="matrix"),
        ),
    }
    class NativeDirectory:
        def __init__(
            self,
            *,
            kind: str,
            self_id: str,
            users: list[MessengerUser],
        ) -> None:
            self.kind = kind
            self.self_id = self_id
            self.users = users
            self.close = AsyncMock()

        def supports(self, capability: Capability) -> bool:
            return capability in {Capability.SEND, Capability.SEARCH_USERS}

        async def search_users(self, _query: str) -> list[MessengerUser]:
            return self.users

    messengers = {
        17: NativeDirectory(
            kind="telegram",
            self_id="bot-17",
            users=[
                MessengerUser(
                    id=uuid4(),
                    tool_id=3,
                    external_id="shared-42",
                    display_name="Nicolas Telegram",
                )
            ],
        ),
        29: NativeDirectory(
            kind="matrix",
            self_id="@agent:example.test",
            users=[
                MessengerUser(
                    id=uuid4(),
                    tool_id=4,
                    external_id="shared-42",
                    display_name="Nicolas Matrix",
                ),
                MessengerUser(
                    id=uuid4(),
                    tool_id=4,
                    external_id="@sarah:example.test",
                    display_name="Sarah",
                ),
            ],
        ),
    }

    monkeypatch.setattr(
        connection_service,
        "get_connections_by_agent",
        AsyncMock(return_value=[telegram, matrix]),
    )
    monkeypatch.setattr(
        tool_service,
        "get_tool_by_id",
        AsyncMock(side_effect=lambda tool_id: tools[tool_id]),
    )
    monkeypatch.setattr(service.facade, "is_kind_enabled", lambda _kind: True)
    monkeypatch.setattr(service.facade, "get_factory", lambda _kind: object)
    monkeypatch.setattr(
        service.facade,
        "get_spec",
        lambda kind: BridgeSpec(
            kind=kind,
            capabilities={Capability.SEND, Capability.SEARCH_USERS},
        ),
    )
    get_messenger = AsyncMock(side_effect=lambda connection_id: messengers[connection_id])
    monkeypatch.setattr(
        service.facade,
        "get_messenger",
        get_messenger,
    )

    results = await service.search_agent_users(7, "")

    assert [
        (connection_id, platform, user.external_id)
        for connection_id, _, platform, user in results
    ] == [
        (29, "matrix", "shared-42"),
        (17, "telegram", "shared-42"),
        (29, "matrix", "@sarah:example.test"),
    ]
    assert all(user.tool_id == tool_id for _, tool_id, _, user in results)
    assert get_messenger.await_count == 2
    messengers[17].close.assert_awaited_once()
    messengers[29].close.assert_awaited_once()
