"""Only clients displaying Dream receive its live monitoring updates."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.dream import events, scheduler, service
from core import websocket
from core.user.models import User


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["runtime", "receipt"])
async def test_updates_follow_the_displayed_page_and_current_rights(monkeypatch, source):
    user = User(id=1, email="viewer@example.test", hashed_password="x", is_active=True)
    server = SimpleNamespace(emit=AsyncMock(), disconnect=AsyncMock())
    db = Mock()
    db.get = AsyncMock(return_value=user)
    db.execute = AsyncMock(return_value=Mock())
    db.execute.return_value.scalars.return_value.all.return_value = [user]

    @asynccontextmanager
    async def session():
        yield

    privilege = AsyncMock(return_value=True)
    scope = SimpleNamespace(is_global=True)
    monkeypatch.setattr(websocket, "_sio", server)
    monkeypatch.setattr(websocket, "_connected_identities", {
        sid: websocket._SocketIdentity(user.id, None, token="test")
        for sid in ("monitoring-tab", "login-tab")
    })
    monkeypatch.setattr(websocket, "_displayed_resource_rooms", {})
    monkeypatch.setattr(websocket, "_resource_room_policies", {})
    monkeypatch.setattr(websocket, "_event_authorizations", {})
    monkeypatch.setattr(websocket, "get_db_session", session)
    monkeypatch.setattr(websocket, "get_db", lambda: db)
    monkeypatch.setattr(events, "get_db", lambda: db)
    monkeypatch.setattr(events, "management_scope_for", AsyncMock(return_value=scope))
    monkeypatch.setattr(websocket, "_identity_is_valid", AsyncMock(return_value=True))
    monkeypatch.setattr(websocket, "check_privilege", privilege)
    monkeypatch.setattr(scheduler, "_runtime_update_pending", False)
    events.register_events()
    receipt_id = uuid4()
    data = {"scope": source}
    if source == "receipt":
        data["id"] = str(receipt_id)

    async def update():
        if source == "runtime":
            scheduler._runtime_update_pending = True
            await scheduler._emit_runtime_updates()
        else:
            await service._emit_receipt_update(receipt_id)

    await update()
    server.emit.assert_not_awaited()
    db.execute.assert_not_awaited()
    assert await websocket._handle_room_display("monitoring-tab", {"room": "DreamRoom:monitoring"})
    await update()
    server.emit.assert_awaited_once_with("dream.update", {"data": data}, room="monitoring-tab")

    server.emit.reset_mock()
    assert await websocket._handle_room_display("monitoring-tab", {"room": None})
    db.execute.reset_mock()
    await update()
    server.emit.assert_not_awaited()
    db.execute.assert_not_awaited()
    assert await websocket._handle_room_display("monitoring-tab", {"room": "DreamRoom:monitoring"})
    privilege.return_value = False
    await update()
    server.emit.assert_not_awaited()
    privilege.return_value = True
    scope.is_global = False
    await update()
    server.emit.assert_not_awaited()
    scope.is_global = True
    await update()
    server.emit.assert_awaited_once()
    server.emit.reset_mock()

    # Closing the page during an in-flight permission check must also stop
    # delivery, even though it was still open when this emission began.
    async def close_during_authorization(*_args, **_kwargs):
        await websocket._handle_room_display("monitoring-tab", {"room": None})
        return True

    privilege.side_effect = close_during_authorization
    await update()
    server.emit.assert_not_awaited()
    privilege.side_effect = None
    assert await websocket._handle_room_display("monitoring-tab", {"room": "DreamRoom:monitoring"})
    await websocket._handle_disconnect("monitoring-tab")
    await update()
    server.emit.assert_not_awaited()
