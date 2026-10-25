from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import OneBot
from bridge.one_bot.messenger import OneBotMessenger


@pytest.mark.asyncio
async def test_search_users_combines_friends_and_every_group_member() -> None:
    client = AsyncMock(spec=OneBot)
    client.get_friend_list.return_value = {
        "status": "ok", "retcode": 0,
        "data": [{"user_id": "42", "nickname": "Nicolas", "remark": "Nico"}]
    }
    client.get_group_list.return_value = {
        "status": "ok", "retcode": 0,
        "data": [{"group_id": "100"}, {"group_id": "200"}]
    }
    client.get_group_member_list.side_effect = [
        {"status": "ok", "retcode": 0, "data": [{"user_id": "42", "nickname": "Nicolas"}]},
        {"status": "ok", "retcode": 0, "data": [{"user_id": "84", "nickname": "Sarah", "card": "Sarah D."}]},
    ]
    messenger = OneBotMessenger(
        cast(OneBot, client),
        tool_id=3,
        self_id="7",
        connection_id=19,
    )

    users = await messenger.search_users("")

    assert [(user.id, user.display_name) for user in users] == [
        ("42", "Nicolas"),
        ("84", "Sarah D."),
    ]
    assert all(user.connection_id == 19 for user in users)
    assert client.get_group_member_list.await_count == 2


@pytest.mark.asyncio
async def test_failed_directory_response_is_not_an_empty_search():
    client = AsyncMock(spec=OneBot)
    client.get_friend_list.return_value = {"status": "failed", "retcode": 1404, "msg": "not found", "data": None}
    messenger = OneBotMessenger(cast(OneBot, client), tool_id=3, self_id="7", connection_id=19)
    with pytest.raises(RuntimeError, match="not found"):
        await messenger.search_users("")
