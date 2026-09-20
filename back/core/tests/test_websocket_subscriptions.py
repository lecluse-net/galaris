"""Consumer subscriptions reduce delivery without granting resource access."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core import websocket
from core.user.models import User


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["task", "llm_call", "memory", "goal", "goal_settings", "process_run", "voice_conversation", "chat", "agent_run"])
async def test_no_consumer_skips_db_and_delivery_but_subscribed_users_keep_their_rights(monkeypatch, subject):
    user = User(id=1, email="listener@example.test", hashed_password="x", is_active=True)
    server = SimpleNamespace(emit=AsyncMock(), disconnect=AsyncMock())
    db = Mock()
    db.execute = AsyncMock(return_value=Mock())
    db.execute.return_value.scalars.return_value.all.return_value = [user]
    db.get = AsyncMock(return_value=user)

    @asynccontextmanager
    async def session():
        yield

    monkeypatch.setattr(websocket, "_sio", server)
    monkeypatch.setattr(websocket, "get_db_session", session)
    monkeypatch.setattr(websocket, "get_db", lambda: db)
    monkeypatch.setattr(websocket, "_connected_identities", {
        sid: websocket._SocketIdentity(user.id, None, token="test")
        for sid in ("page", "settings")
    })
    subscriptions = {"page": frozenset(), "settings": frozenset()}
    monkeypatch.setattr(websocket, "_event_subscriptions", subscriptions, raising=False)
    monkeypatch.setitem(websocket._EVENT_PRIVILEGES, subject, ("TASK_ACCESS",))
    authorize = AsyncMock(return_value=True)
    monkeypatch.setitem(websocket._event_authorizations, subject, authorize)
    monkeypatch.setattr(websocket, "_identity_is_valid", AsyncMock(return_value=True))
    monkeypatch.setattr(websocket, "check_privilege", AsyncMock(return_value=True))

    await websocket.emit(subject, "update", {"id": "resource"})
    server.emit.assert_not_awaited()
    db.execute.assert_not_awaited()
    assert await websocket._handle_event_subscriptions("page", {"events": [f"{subject}.update"]})
    await websocket.emit(subject, "update", {"id": "resource"})
    server.emit.assert_awaited_once_with(f"{subject}.update", {"data": {"id": "resource"}}, room="page")
    server.emit.reset_mock()
    authorize.return_value = False
    await websocket.emit(subject, "update", {"id": "resource"})
    server.emit.assert_not_awaited()
    authorize.return_value = True

    async def leave_during_authorization(*_args):
        await websocket._handle_event_subscriptions("page", {"events": []})
        return True

    authorize.side_effect = leave_during_authorization
    await websocket.emit(subject, "update", {"id": "resource"})
    server.emit.assert_not_awaited()
    authorize.side_effect = None
    db.execute.reset_mock()
    await websocket.emit(subject, "update", {"id": "resource"})
    db.execute.assert_not_awaited()
    assert await websocket._handle_event_subscriptions("page", {"events": [f"{subject}.update"]})
    await websocket.emit(subject, "update", {"id": "resource"})
    server.emit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [None, "task.update", [1], ["unknown.update"], ["task."], ["task.update"] * 129])
async def test_invalid_subscriptions_cannot_replace_current_interests(monkeypatch, events):
    monkeypatch.setattr(websocket, "_connected_identities", {"page": websocket._SocketIdentity(1, None)})
    interests = {"page": frozenset({"task.update"})}
    monkeypatch.setattr(websocket, "_event_subscriptions", interests)
    assert not await websocket._handle_event_subscriptions("page", {"events": events})
    assert not await websocket._handle_event_subscriptions("unauthenticated", {"events": []})
    assert interests == {"page": frozenset({"task.update"})}


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [None, [], ["task.update"]])
async def test_handshake_installs_interests_and_disconnect_discards_them(monkeypatch, events):
    monkeypatch.setattr(websocket, "_sio", SimpleNamespace(save_session=AsyncMock(), emit=AsyncMock()))
    monkeypatch.setattr(websocket, "_connected_identities", {})
    monkeypatch.setattr(websocket, "_event_subscriptions", {})
    monkeypatch.setattr(websocket, "_authenticate_socket_token", AsyncMock(return_value=websocket._SocketIdentity(1, None)))
    auth = {"token": "test"}
    if events is not None:
        auth["events"] = events
    assert await websocket._handle_connect("page", {}, auth)
    # Old cached clients keep receiving their authorized events until reload.
    assert websocket._event_is_requested("page", "task.update") == (events != [])
    assert websocket._event_is_requested("page", "memory.update") == (events is None)
    await websocket._handle_disconnect("page")
    assert "page" not in websocket._event_subscriptions


@pytest.mark.asyncio
async def test_handshake_rejects_malformed_interests_without_authentication_work(monkeypatch):
    authenticate = AsyncMock()
    monkeypatch.setattr(websocket, "_authenticate_socket_token", authenticate)
    assert not await websocket._handle_connect("page", {}, {"token": "test", "events": "task.update"})
    authenticate.assert_not_awaited()
