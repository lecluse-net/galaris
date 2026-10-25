from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest

from bridge.one_bot.client import MessageSender, OneBot, OneBotMessage
from bridge.one_bot.messenger import OneBotMessenger, onebot_to_message


def _event(message_type: str, *, remote_id: str = "42") -> OneBotMessage:
    return OneBotMessage(
        time=1,
        self_id="bot",
        post_type="message",
        message_type=message_type,
        message_id=f"message-{message_type}",
        user_id=remote_id,
        group_id=remote_id if message_type == "group" else None,
        message="hello",
        raw_message="hello",
        sender=MessageSender(user_id=remote_id, nickname="User"),
    )


def test_group_and_direct_rooms_with_same_remote_id_do_not_collide() -> None:
    group = onebot_to_message(_event("group"), tool_id=3, connection_id=19)
    direct = onebot_to_message(_event("private"), tool_id=3, connection_id=19)

    assert group.room is not None and group.room.id == "group:42"
    assert group.room.kind == "group"
    assert direct.room is not None and direct.room.id == "direct:42"
    assert direct.room.kind == "direct"
    assert group.room.id != direct.room.id


@pytest.mark.parametrize("message_type", ["private", "group"])
def test_standard_numeric_identifiers_are_normalized(message_type):
    payload = _event(message_type).model_dump()
    payload.update(self_id=700, user_id=420, message_id=-123)
    payload["sender"]["user_id"] = 420
    if message_type == "group":
        payload["group_id"] = 42
    event = OneBotMessage.model_validate(payload)
    observed = onebot_to_message(event, tool_id=3, connection_id=19)
    assert observed.id == "-123"
    assert observed.sender.id == "420"
    assert observed.recipient.id == "700"
    assert observed.room.id == ("group:42" if message_type == "group" else "direct:420")


def test_group_event_without_group_id_is_rejected():
    event = _event("group").model_copy(update={"group_id": None})
    with pytest.raises(ValueError, match="conversation"):
        onebot_to_message(event, tool_id=3, connection_id=19)


@pytest.mark.asyncio
async def test_send_to_room_dispatches_by_namespaced_kind_and_keeps_remote_id() -> None:
    client = AsyncMock(spec=OneBot)
    client.send_group_msg.return_value = {
        "status": "ok",
        "retcode": 0,
        "data": {"message_id": "group-message"},
    }
    client.send_private_msg.return_value = {
        "status": "ok",
        "retcode": 0,
        "data": {"message_id": "direct-message"},
    }
    messenger = OneBotMessenger(
        cast(OneBot, client),
        tool_id=3,
        self_id="bot",
        connection_id=19,
    )

    literal = "group text [CQ:image,file=file:///synthetic/private.png]"
    group = await messenger.send_to_room("group:42", literal)
    direct = await messenger.send_to_room("direct:42", "direct text")

    client.send_group_msg.assert_awaited_once_with("42", [{"type": "text", "data": {"text": literal}}])
    client.send_private_msg.assert_awaited_once_with("42", [{"type": "text", "data": {"text": "direct text"}}])
    assert group.id == "group-message"
    assert group.text == literal
    assert group.room is not None and group.room.id == "group:42"
    assert direct.id == "direct-message"
    assert direct.room is not None and direct.room.id == "direct:42"


@pytest.mark.asyncio
async def test_direct_history_uses_private_history_action() -> None:
    client = AsyncMock(spec=OneBot)
    outgoing = _event("private").model_copy(update={"user_id": "bot"})
    client.get_private_msg_history.return_value = [outgoing]
    messenger = OneBotMessenger(
        cast(OneBot, client),
        tool_id=3,
        self_id="bot",
        connection_id=19,
        agent_id=7,
    )

    messages = await messenger.history("direct:42", 15)

    client.get_private_msg_history.assert_awaited_once_with("42", 15)
    client.get_group_msg_history.assert_not_awaited()
    assert messages[0].room is not None
    assert messages[0].room.id == "direct:42"
    assert messages[0].sender.agent_id == 7
    assert messages[0].recipient.id == "42" and messages[0].recipient.agent_id is None


@pytest.mark.asyncio
async def test_failed_or_incomplete_send_is_not_reported_as_delivered() -> None:
    client = AsyncMock(spec=OneBot)
    client.send_group_msg.return_value = {
        "status": "failed",
        "retcode": 1404,
        "msg": "not found",
    }
    messenger = OneBotMessenger(
        cast(OneBot, client),
        tool_id=3,
        self_id="bot",
        connection_id=19,
    )

    with pytest.raises(RuntimeError, match="not found"):
        await messenger.send_to_room("group:42", "hello")

    client.send_group_msg.return_value = {
        "status": "ok",
        "retcode": 0,
        "data": {},
    }
    with pytest.raises(RuntimeError, match="message_id"):
        await messenger.send_to_room("group:42", "hello")

    client.send_group_msg.return_value = {
        "status": "ok",
        "data": {"message_id": "unconfirmed-message"},
    }
    with pytest.raises(RuntimeError):
        await messenger.send_to_room("group:42", "hello")
