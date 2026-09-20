import asyncio
from datetime import timedelta
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core import websocket
from core.user import create_access_token, encrypt_password
from core.user.models import User
from core.user import user_service


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_connected_identities() -> None:
    websocket._connected_identities.clear()  # pyright: ignore[reportPrivateUsage]
    websocket._displayed_resource_rooms.clear()  # pyright: ignore[reportPrivateUsage]


class FakeSocketServer:
    def __init__(self) -> None:
        self.sessions: list[tuple[str, dict[str, int]]] = []
        self.events: list[tuple[str, dict[str, str], str]] = []
        self.joined: list[tuple[str, str]] = []
        self.disconnected: list[str] = []

    async def disconnect(self, sid: str) -> None:
        self.disconnected.append(sid)

    async def save_session(self, sid: str, session: dict[str, int]) -> None:
        self.sessions.append((sid, session))

    async def emit(
        self,
        event: str,
        data: dict[str, str],
        *,
        room: str,
    ) -> None:
        self.events.append((event, data, room))

    async def enter_room(self, sid: str, room: str) -> None:
        self.joined.append((sid, room))

    async def leave_room(self, sid: str, room: str) -> None:
        try:
            self.joined.remove((sid, room))
        except ValueError:
            pass


@pytest.mark.parametrize(
    "auth",
    [
        None,
        {},
        {"token": None},
        {"token": ""},
        {"token": "x" * 8193},
        "token",
    ],
)
async def test_connect_rejects_missing_or_malformed_auth(
    monkeypatch: pytest.MonkeyPatch,
    auth: object,
) -> None:
    async def authenticate(_token: str) -> websocket._SocketIdentity | None:  # pyright: ignore[reportPrivateUsage]
        pytest.fail("Malformed authentication must not reach token verification")

    monkeypatch.setattr(websocket, "_authenticate_socket_token", authenticate)

    accepted = await websocket._handle_connect("sid-1", {}, auth)

    assert accepted is False


async def test_connect_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def authenticate(token: str) -> websocket._SocketIdentity | None:  # pyright: ignore[reportPrivateUsage]
        assert token == "invalid-token"
        return None

    fake_server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_authenticate_socket_token", authenticate)
    monkeypatch.setattr(websocket, "_sio", fake_server)

    accepted = await websocket._handle_connect(
        "sid-2",
        {},
        {"token": " invalid-token "},
    )

    assert accepted is False
    assert fake_server.sessions == []
    assert fake_server.events == []


async def test_connect_accepts_valid_token_and_stores_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authenticate(token: str) -> websocket._SocketIdentity | None:  # pyright: ignore[reportPrivateUsage]
        assert token == "valid-token"
        return websocket._SocketIdentity(user_id=42, role_id=7)  # pyright: ignore[reportPrivateUsage]

    fake_server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_authenticate_socket_token", authenticate)
    monkeypatch.setattr(websocket, "_sio", fake_server)

    accepted = await websocket._handle_connect(
        "sid-3",
        {},
        {"token": "valid-token"},
    )

    assert accepted is True
    assert fake_server.sessions == [("sid-3", {"user_id": 42, "role_id": 7})]
    assert fake_server.events == [
        ("welcome", {"message": "Welcome to this server !"}, "sid-3")
    ]


async def test_socket_token_authenticates_active_user(db: AsyncSession) -> None:
    user = User(
        email="socket-active@example.com",
        hashed_password=encrypt_password("secure-password"),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(
        {"sub": user.email, "user_id": user.id, "role_id": 7}
    )

    identity = await websocket._authenticate_socket_token(token)

    assert identity == websocket._SocketIdentity(user_id=user.id, role_id=7)  # pyright: ignore[reportPrivateUsage]
    assert user_service.get_current_user_id() is None


async def test_socket_token_rejects_expired_token(db: AsyncSession) -> None:
    user = User(
        email="socket-expired@example.com",
        hashed_password=encrypt_password("secure-password"),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(
        {"sub": user.email, "user_id": user.id},
        expires_delta=timedelta(seconds=-1),
    )

    identity = await websocket._authenticate_socket_token(token)

    assert identity is None


@pytest.mark.parametrize("revocation", ["session", "account", "password", "expiry"])
async def test_socket_authenticates_once_but_revocation_blocks_the_next_event(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, revocation: str,
) -> None:
    from core.user import refresh_session_service
    user = User(email=f"socket-revocation-{revocation}@example.com", hashed_password="unused", is_active=True)
    db.add(user)
    await db.commit()
    refresh_token = await refresh_session_service.create_refresh_session(user.id)
    family = await refresh_session_service.family_for_token(refresh_token)
    token = create_access_token({"sub": user.email, "user_id": user.id, "auth_version": user.auth_version, "session_family": family})
    authenticate = AsyncMock(wraps=websocket.authenticate_from_jwt_token)
    monkeypatch.setattr(websocket, "authenticate_from_jwt_token", authenticate)
    server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_sio", server)
    monkeypatch.setattr(websocket, "check_privilege", AsyncMock(return_value=True))
    monkeypatch.setitem(websocket._event_authorizations, "task", AsyncMock(return_value=True))
    assert await websocket._handle_connect("first", {}, {"token": token})
    assert await websocket._handle_connect("second", {}, {"token": token})
    assert authenticate.await_count == 2
    decode = Mock(wraps=websocket.jwt.decode)
    monkeypatch.setattr(websocket.jwt, "decode", decode)
    server.events.clear()
    for _ in range(30):
        await websocket.emit("task", "update", {"id": "task-1"})
    assert len(server.events) == 60
    assert authenticate.await_count == 2
    decode.assert_not_called()
    if revocation == "session":
        await refresh_session_service.revoke_refresh_token(refresh_token)
    elif revocation == "account":
        user.is_active = False
        await db.commit()
    elif revocation == "password":
        user.auth_version += 1
        await db.commit()
    else:
        identity = websocket._connected_identities["first"]
        assert identity.access_claims is not None
        monkeypatch.setattr(websocket.time, "time", lambda: int(identity.access_claims["exp"]) + 1)
    server.events.clear()
    await websocket.emit("task", "update", {"id": "task-1"})
    assert server.events == []
    assert set(server.disconnected) == {"first", "second"}


async def test_emit_only_targets_users_with_subject_privilege(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    users = [
        User(id=41, email="allowed@example.com", hashed_password="x", is_active=True),
        User(id=42, email="denied@example.com", hashed_password="x", is_active=True),
    ]

    class FakeScalars:
        def all(self) -> list[User]:
            return users

    class FakeResult:
        def scalars(self) -> FakeScalars:
            return FakeScalars()

    class FakeDb:
        async def execute(self, _statement: object) -> FakeResult:
            return FakeResult()

    fake_db = FakeDb()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def privilege_check(
        user: User | None,
        privileges: str | list[str],
        db: object,
        role_id: int | None = None,
    ) -> bool:
        assert privileges == ["TASK_ACCESS", "TASK_EDIT"]
        assert db is fake_db
        assert role_id in (7, 8)
        return user is not None and user.id == 41

    fake_server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_sio", fake_server)
    monkeypatch.setattr(websocket, "get_db_session", fake_db_session)
    monkeypatch.setattr(websocket, "get_db", lambda: fake_db)
    monkeypatch.setattr(websocket, "check_privilege", privilege_check)
    monkeypatch.setattr(websocket, "_identity_is_valid", AsyncMock(return_value=True))
    monkeypatch.setitem(websocket._event_authorizations, "task", AsyncMock(return_value=True))
    websocket._connected_identities.update(  # pyright: ignore[reportPrivateUsage]
        {
            "sid-allowed": websocket._SocketIdentity(41, 7),  # pyright: ignore[reportPrivateUsage]
            "sid-denied": websocket._SocketIdentity(42, 8),  # pyright: ignore[reportPrivateUsage]
        }
    )

    await websocket.emit("task", "update", {"id": "task-1"})

    assert fake_server.events == [
        ("task.update", {"data": {"id": "task-1"}}, "sid-allowed")
    ]


async def test_emit_rejects_unclassified_subject_and_resource_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_sio", fake_server)

    await websocket.emit("secret", "update", {"value": "hidden"})
    await websocket.emit(
        "task",
        "update",
        {"id": "task-1"},
        websocket.BaseRoom("task-1"),
    )

    assert fake_server.events == []


async def test_dream_events_use_task_monitoring_privileges() -> None:
    assert websocket._EVENT_PRIVILEGES["dream"] == (  # pyright: ignore[reportPrivateUsage]
        "TASK_ACCESS",
        "TASK_EDIT",
    )


async def test_memory_events_use_memory_privileges() -> None:
    assert websocket._EVENT_PRIVILEGES["memory"] == (  # pyright: ignore[reportPrivateUsage]
        "MEMORY_ACCESS",
        "MEMORY_EDIT",
        "MEMORY_ADMIN",
    )


async def test_client_room_join_is_rejected() -> None:
    accepted = await websocket._handle_room_join(  # pyright: ignore[reportPrivateUsage]
        "sid-1",
        {"room": "Task:secret"},
    )

    assert accepted is False


async def test_registered_resource_room_join_checks_privilege_and_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DocumentRoom(websocket.BaseRoom):
        pass

    user = User(id=77, email="member@example.com", hashed_password="x", is_active=True)

    class FakeDb:
        async def get(self, _model: object, user_id: int) -> User | None:
            return user if user_id == user.id else None

    fake_db = FakeDb()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def privilege_check(*_args: object, **_kwargs: object) -> bool:
        return True

    async def membership(user_id: int, resource_id: str) -> bool:
        return user_id == 77 and resource_id == "allowed"

    fake_server = FakeSocketServer()
    monkeypatch.setattr(websocket, "_sio", fake_server)
    monkeypatch.setattr(websocket, "get_db_session", fake_db_session)
    monkeypatch.setattr(websocket, "get_db", lambda: fake_db)
    monkeypatch.setattr(websocket, "check_privilege", privilege_check)
    websocket.register_resource_room(
        "document",
        DocumentRoom,
        required_privileges="DOCUMENT_ACCESS",
        authorize=membership,
    )
    monkeypatch.setattr(websocket, "_identity_is_valid", AsyncMock(return_value=True))
    websocket._connected_identities["sid-member"] = websocket._SocketIdentity(77, None)  # pyright: ignore[reportPrivateUsage]

    assert await websocket._handle_room_join(  # pyright: ignore[reportPrivateUsage]
        "sid-member", {"room": "DocumentRoom:allowed"}
    )
    assert not await websocket._handle_room_join(  # pyright: ignore[reportPrivateUsage]
        "sid-member", {"room": "DocumentRoom:denied"}
    )
    assert fake_server.joined == [("sid-member", "DocumentRoom:allowed")]


async def test_displayed_resource_room_is_authorized_and_scoped_to_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DocumentRoom(websocket.BaseRoom):
        pass

    user = User(id=78, email="viewer@example.com", hashed_password="x", is_active=True)

    class FakeDb:
        async def get(self, _model: object, user_id: int) -> User | None:
            return user if user_id == user.id else None

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def privilege_check(*_args: object, **_kwargs: object) -> bool:
        return True

    async def membership(user_id: int, resource_id: str) -> bool:
        return user_id == user.id and resource_id == "visible"

    monkeypatch.setattr(websocket, "get_db_session", fake_db_session)
    monkeypatch.setattr(websocket, "get_db", FakeDb)
    monkeypatch.setattr(websocket, "_identity_is_valid", AsyncMock(return_value=True))
    monkeypatch.setattr(websocket, "check_privilege", privilege_check)
    websocket.register_resource_room(
        "document",
        DocumentRoom,
        required_privileges="DOCUMENT_ACCESS",
        authorize=membership,
    )
    websocket._connected_identities["sid-viewer"] = websocket._SocketIdentity(  # pyright: ignore[reportPrivateUsage]
        user.id,
        None,
    )

    assert await websocket._handle_room_display(  # pyright: ignore[reportPrivateUsage]
        "sid-viewer", {"room": "DocumentRoom:visible"}
    )
    assert websocket.is_room_displayed_by_user(user.id, "DocumentRoom:visible")
    assert not websocket.is_room_displayed_by_user(user.id + 1, "DocumentRoom:visible")
    assert not await websocket._handle_room_display(  # pyright: ignore[reportPrivateUsage]
        "sid-viewer", {"room": "DocumentRoom:hidden"}
    )
    assert not websocket.is_room_displayed_by_user(user.id, "DocumentRoom:visible")
    assert await websocket._handle_room_display(  # pyright: ignore[reportPrivateUsage]
        "sid-viewer", {"room": None}
    )
    assert not websocket.is_room_displayed_by_user(user.id, "DocumentRoom:visible")
    assert await websocket._handle_room_display(  # pyright: ignore[reportPrivateUsage]
        "sid-viewer", {"room": "DocumentRoom:visible"}
    )
    await websocket._handle_disconnect("sid-viewer")  # pyright: ignore[reportPrivateUsage]
    assert not websocket.is_room_displayed_by_user(user.id, "DocumentRoom:visible")


@pytest.mark.parametrize("change", ["leave", "another-page", "disconnect"])
async def test_late_display_authorization_cannot_restore_a_closed_page(monkeypatch, change):
    started = asyncio.Event()
    release = asyncio.Event()

    async def authorize(_sid, room):
        if room == "DocumentRoom:old":
            started.set()
            await release.wait()
        return True

    monkeypatch.setattr(websocket, "_resource_room_is_authorized", authorize)
    websocket._connected_identities["viewer"] = websocket._SocketIdentity(78, None)
    pending = asyncio.create_task(websocket._handle_room_display("viewer", {"room": "DocumentRoom:old"}))
    try:
        await started.wait()
        if change == "disconnect":
            await websocket._handle_disconnect("viewer")
        else:
            room = "DocumentRoom:new" if change == "another-page" else None
            assert await websocket._handle_room_display("viewer", {"room": room})
        release.set()
        assert not await pending
        assert not websocket.is_room_displayed_by_user(78, "DocumentRoom:old")
        assert websocket.is_room_displayed_by_user(78, "DocumentRoom:new") == (change == "another-page")
    finally:
        release.set()
        await pending
