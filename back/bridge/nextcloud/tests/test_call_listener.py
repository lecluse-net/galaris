import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bridge.nextcloud import call_listener
from bridge.nextcloud.call_listener import (
    _TalkAutoAnswerContext,
    _handle_signaling_event,
    _listen_connection,
    _maybe_answer_room,
    _remote_actor_ids_from_signaling_event,
    _suppressed_remote_calls,
    suppress_auto_answer,
)
from bridge.nextcloud.voice_provider import NEXTCLOUD_TALK_VOICE_PROVIDER


@pytest.fixture(autouse=True)
def clear_suppressed_remote_calls() -> None:
    _suppressed_remote_calls.clear()


def test_remote_actor_ids_from_signaling_event_detects_remote_callers() -> None:
    event = {
        "target": "participants",
        "type": "update",
        "update": [
            {
                "users": [
                    {"userid": "agent", "inCall": True, "flags": 3},
                    {"userid": "nicolas", "inCall": False, "flags": 3},
                    {"userid": "sample", "actorType": "bots", "inCall": True, "flags": 3},
                ]
            }
        ],
    }

    assert _remote_actor_ids_from_signaling_event(event, "agent") == {"nicolas"}


def test_remote_actor_ids_from_signaling_event_ignores_non_call_events() -> None:
    assert _remote_actor_ids_from_signaling_event({"target": "room", "type": "message"}, "agent") == set()


def test_remote_actor_ids_from_signaling_event_ignores_other_voice_agents() -> None:
    event = {
        "target": "participants",
        "type": "update",
        "update": {
            "users": [
                {"userid": "aster", "inCall": True},
                {"userid": "nicolas", "inCall": True},
            ]
        },
    }

    assert _remote_actor_ids_from_signaling_event(
        event,
        "orion",
        ignored_actor_ids={"orion", "aster"},
    ) == {"nicolas"}


@pytest.mark.asyncio
async def test_listener_stops_before_room_monitoring_when_voice_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _TalkAutoAnswerContext(
        connection_id=12,
        agent_id=7,
        self_id="agent-7",
        client=object(),
    )
    enabled = AsyncMock(return_value=False)
    refresh_rooms = AsyncMock()
    monkeypatch.setattr(call_listener, "_voice_listening_is_enabled", enabled)
    monkeypatch.setattr(call_listener, "_refresh_rooms", refresh_rooms)

    await _listen_connection(context)

    enabled.assert_awaited_once_with(context)
    refresh_rooms.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_starts_and_stops_listener_with_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = AsyncMock()

    async def run_listener(connection_id: int, agent_id: int) -> None:
        await started(connection_id, agent_id)
        await asyncio.Event().wait()

    discoveries = [[(12, 7)], []]

    async def discover() -> list[tuple[int, int]]:
        return discoveries.pop(0)

    monkeypatch.setattr(call_listener, "_run_connection_listener", run_listener)
    monkeypatch.setattr(
        call_listener,
        "_discover_voice_capable_talk_connections",
        discover,
    )
    call_listener._listener_tasks.clear()

    await call_listener._reconcile_voice_call_listeners()
    await asyncio.sleep(0)
    assert 12 in call_listener._listener_tasks
    started.assert_awaited_once_with(12, 7)

    await call_listener._reconcile_voice_call_listeners()
    assert call_listener._listener_tasks == {}


@pytest.mark.asyncio
async def test_incoming_call_builds_transport_in_managed_db_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _TalkAutoAnswerContext(
        connection_id=8,
        agent_id=1519,
        self_id="orion-demo-test",
        client=object(),
    )
    db_active = False
    transport = object()

    @asynccontextmanager
    async def managed_db_session() -> AsyncIterator[None]:
        nonlocal db_active
        db_active = True
        try:
            yield
        finally:
            db_active = False

    async def create_transport(connection_id: int, *, outgoing: bool) -> object:
        assert db_active is True
        assert connection_id == 8
        assert outgoing is False
        return transport

    def start_agent_call(**kwargs: object) -> tuple[SimpleNamespace, bool]:
        assert db_active is False
        assert kwargs == {
            "agent_id": 1519,
            "connection_id": 8,
            "room_id": "room-orion",
            "transport": transport,
        }
        return SimpleNamespace(call_id="voice-1519-8-room-orion"), True

    monkeypatch.setattr(call_listener, "get_db_session", managed_db_session)
    monkeypatch.setattr(
        NEXTCLOUD_TALK_VOICE_PROVIDER,
        "create_transport",
        create_transport,
    )
    monkeypatch.setattr(
        call_listener.voice_call_manager,
        "start_agent_call",
        start_agent_call,
    )

    await call_listener._start_incoming_call(
        context,
        "room-orion",
        {"nicolas"},
    )


@pytest.mark.asyncio
async def test_polling_does_not_rejoin_call_after_local_hangup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        get_call_participants=AsyncMock(
            return_value=[{"actorId": "nicolas", "actorType": "users"}]
        )
    )
    context = _TalkAutoAnswerContext(
        connection_id=8,
        agent_id=1519,
        self_id="orion",
        client=client,
    )
    start_incoming = AsyncMock()
    monkeypatch.setattr(call_listener, "_start_incoming_call", start_incoming)
    suppress_auto_answer(8, "room-orion", {"nicolas"})

    await _maybe_answer_room(context, "room-orion")

    start_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_signaling_reenables_answers_only_after_previous_caller_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(
        get_call_participants=AsyncMock(
            side_effect=[
                [{"actorId": "nicolas", "actorType": "users"}],
                [],
            ]
        )
    )
    context = _TalkAutoAnswerContext(
        connection_id=8,
        agent_id=1519,
        self_id="orion",
        client=client,
    )
    start_incoming = AsyncMock()
    monkeypatch.setattr(call_listener, "_start_incoming_call", start_incoming)
    suppress_auto_answer(8, "room-orion", {"nicolas"})
    same_call_event = {
        "target": "participants",
        "type": "update",
        "update": {"users": [{"userid": "nicolas", "inCall": True}]},
    }

    await _handle_signaling_event(context, "room-orion", same_call_event)
    await _handle_signaling_event(
        context,
        "room-orion",
        {"target": "participants", "type": "update", "update": {"users": []}},
    )

    start_incoming.assert_not_awaited()
    assert (8, "room-orion") not in _suppressed_remote_calls


@pytest.mark.asyncio
async def test_inactive_call_api_clears_local_hangup_suppression() -> None:
    request = httpx.Request("GET", "https://cloud.test/call/room-orion")
    inactive = httpx.HTTPStatusError(
        "call inactive",
        request=request,
        response=httpx.Response(404, request=request),
    )
    context = _TalkAutoAnswerContext(
        connection_id=8,
        agent_id=1519,
        self_id="orion",
        client=SimpleNamespace(
            get_call_participants=AsyncMock(side_effect=inactive)
        ),
    )
    suppress_auto_answer(8, "room-orion", {"nicolas"})

    await _maybe_answer_room(context, "room-orion")

    assert (8, "room-orion") not in _suppressed_remote_calls
