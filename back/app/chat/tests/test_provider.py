from unittest.mock import AsyncMock

import pytest

from app.chat.provider import InternalMessenger
from app.messenger import Capability, get_factory, get_spec
from app.messenger.interface import ObservedMessengerMessage, ObservedMessengerRoom


def test_internal_provider_is_registered_with_native_capabilities() -> None:
    assert get_factory("internal") is InternalMessenger
    spec = get_spec("internal")
    assert spec is not None
    assert spec.availability == "global"
    assert spec.inbound_admission == "conversation"
    assert not spec.deliver_task_result
    assert {
        Capability.SEND,
        Capability.HISTORY,
        Capability.FILES,
        Capability.SEARCH_USERS,
        Capability.VOICE_NOTES,
    } == spec.capabilities


@pytest.mark.asyncio
async def test_internal_direct_send_uses_the_existing_canonical_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messenger = InternalMessenger(
        connection_id=7,
        tool_id=8,
        tool_code="chat",
        agent_id=9,
        self_id="agent:9",
    )
    room = ObservedMessengerRoom(id="room-1", kind="direct")
    sent = ObservedMessengerMessage(id="message-1", room=room, text="Progress")
    ensure_direct_room = AsyncMock(return_value=room)
    send_to_room = AsyncMock(return_value=sent)
    monkeypatch.setattr(messenger, "ensure_direct_room", ensure_direct_room)
    monkeypatch.setattr(messenger, "send_to_room", send_to_room)

    result = await messenger.send_to_user("user:1", "Progress")

    assert result == sent
    ensure_direct_room.assert_awaited_once_with("user:1")
    send_to_room.assert_awaited_once_with("room-1", "Progress")
