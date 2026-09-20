from collections.abc import Mapping
import asyncio
import time
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any, Dict, cast

from socketio import AsyncServer, ASGIApp  # pyright: ignore[reportMissingTypeStubs]
from fastapi import FastAPI
from jose import JWTError, jwt
from loguru import logger
from sqlalchemy import select

from .authorize import Privileges, role_id_ctx
from .authorize.logic import check_privilege
from .database import get_db_session
from .database.database import get_db
from .user.auth_service import (
    AuthenticationError,
    authenticate_from_jwt_token,
    deauthenticate,
    validate_access_claims,
)
from .user.models import User
from . import settings
from .secrets import auth_secret_key


_MAX_AUTH_TOKEN_LENGTH = 8192

_EVENT_PRIVILEGES: dict[str, tuple[str, ...]] = {
    "dream": (Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
    "goal": (Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT),
    "goal_settings": (Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT),
    "llm_call": (Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
    "memory": (
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ),
    "process_run": (Privileges.PROCESS_READ, Privileges.PROCESS_ADMIN),
    "task": (Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
    "voice_conversation": (Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
}


@dataclass(frozen=True)
class _SocketIdentity:
    user_id: int
    role_id: int | None
    token: str = field(default="", repr=False, compare=False)
    access_claims: dict[str, Any] | None = field(default=None, repr=False, compare=False)


class BaseRoom:
    """Instantiable base class for WebSocket rooms."""

    def __init__(self, resource_id: Any = None):
        self.resource_id = resource_id

    @property
    def name(self) -> str:
        """Generate a technical name such as 'Task:123' or 'Global'."""
        if self.resource_id:
            return f"{self.__class__.__name__}:{self.resource_id}"
        return self.__class__.__name__

    def __str__(self) -> str:
        return self.name


ResourceRoomAuthorization = Callable[[int, str], Awaitable[bool]]
EventAuthorization = Callable[[User, str, Mapping[str, Any]], Awaitable[bool]]


@dataclass(frozen=True)
class _ResourceRoomPolicy:
    subject: str
    room_type: type[BaseRoom]
    required_privileges: tuple[str, ...]
    authorize: ResourceRoomAuthorization
    displayed_only: bool = False


# Private module state.
_sio: AsyncServer | None = None
_app_asgi: ASGIApp | None = None
_connected_identities: dict[str, _SocketIdentity] = {}
_resource_room_policies: dict[str, _ResourceRoomPolicy] = {}
_displayed_resource_rooms: dict[str, str] = {}
_room_display_requests: dict[str, object] = {}
# Missing entries retain compatibility with clients loaded before subscriptions
# were supported. Updated clients declare even an empty list in their handshake.
_event_subscriptions: dict[str, frozenset[str]] = {}
_event_authorizations: dict[str, EventAuthorization] = {}
_session_monitor: asyncio.Task[None] | None = None


def register_event_authorization(subject: str, authorize: EventAuthorization) -> None:
    """Add the owning domain's resource policy to its existing privilege check."""
    _event_authorizations[subject] = authorize


async def _identity_is_valid(identity: _SocketIdentity, user: User | None = None) -> bool:
    if not identity.token:
        return False
    try:
        claims = identity.access_claims
        if claims is None:
            # Personal API tokens retain their revocable token lookup.
            user = await authenticate_from_jwt_token(identity.token, set_context=False)
            return user.id == identity.user_id
        # Signature and immutable claims were validated at the handshake. Only
        # expiry and mutable account/session revocation can change afterwards.
        expiry = claims.get("exp")
        if expiry is not None and int(expiry) < int(time.time()):
            return False
        if user is None:
            user = await get_db().get(User, identity.user_id, populate_existing=True)
        if user is None or not user.is_active or user.id != identity.user_id:
            return False
        await validate_access_claims(claims, user)
        return True
    except AuthenticationError:
        return False


async def _disconnect_invalid(sid: str) -> None:
    await _handle_disconnect(sid)
    if _sio:
        await _sio.disconnect(sid)  # type: ignore[reportUnknownMemberType]


async def check_sessions() -> None:
    for sid, identity in tuple(_connected_identities.items()):
        async with get_db_session():
            valid = await _identity_is_valid(identity)
        if not valid and _connected_identities.get(sid) is identity:
            await _disconnect_invalid(sid)


async def _monitor_sessions() -> None:
    while True:
        await check_sessions()
        await asyncio.sleep(30)


async def start_session_monitor() -> None:
    global _session_monitor
    if not session_monitor_running():
        _session_monitor = asyncio.create_task(_monitor_sessions(), name="websocket-sessions")


def session_monitor_running() -> bool:
    return _session_monitor is not None and not _session_monitor.done()


async def stop_session_monitor() -> None:
    global _session_monitor
    if _session_monitor is not None:
        _session_monitor.cancel()
        await asyncio.gather(_session_monitor, return_exceptions=True)
        _session_monitor = None


def register_resource_room(
    subject: str,
    room_type: type[BaseRoom],
    *,
    required_privileges: str | tuple[str, ...],
    authorize: ResourceRoomAuthorization,
    displayed_only: bool = False,
) -> None:
    """Register resource authorization, optionally limiting events to its open page.

    displayed_only filters clients before database checks; it does not replace
    the live session, privilege and domain authorization of those recipients.
    """

    privileges = (
        (required_privileges,)
        if isinstance(required_privileges, str)
        else required_privileges
    )
    if not subject or not privileges:
        raise ValueError("A resource WebSocket policy requires a subject and privileges.")
    _EVENT_PRIVILEGES[subject] = privileges
    _resource_room_policies[room_type.__name__] = _ResourceRoomPolicy(
        subject=subject,
        room_type=room_type,
        required_privileges=privileges,
        authorize=authorize,
        displayed_only=displayed_only,
    )


def start(app: FastAPI) -> ASGIApp:
    """
    Start Socket.IO and mount it on the FastAPI application.

    Args:
        app: FastAPI application on which to mount Socket.IO.

    Returns:
        The ASGI application with Socket.IO mounted.
    """
    global _sio, _app_asgi

    if _sio is None:
        _sio = AsyncServer(async_mode="asgi", cors_allowed_origins=[settings.APP_HOST])

        _sio.on("connect", _handle_connect)  # type: ignore
        _sio.on("disconnect", _handle_disconnect)  # type: ignore
        _sio.on("room.join", _handle_room_join)  # type: ignore
        _sio.on("room.leave", _handle_room_leave)  # type: ignore
        _sio.on("room.display", _handle_room_display)  # type: ignore
        _sio.on("events.subscribe", _handle_event_subscriptions)  # type: ignore

        _app_asgi = ASGIApp(_sio, app)

    assert _app_asgi is not None, "ASGI app should be initialized"
    return _app_asgi


async def emit(
    subject: str,
    action: str,
    data: Dict[str, Any],
    room: BaseRoom | None = None,
) -> None:
    """
    Emit an event only to connected users with the subject's read privilege.

    Args:
        subject: Event subject, for example ``task``.
        action: Action, for example ``created`` or ``updated``.
        data: Data to transmit.
        room: Optional resource room, authorized again for each recipient.
    """
    if _sio:
        required_privileges = _EVENT_PRIVILEGES.get(subject)
        if required_privileges is None:
            logger.error(
                "Refused unclassified WebSocket event subject={} action={}",
                subject,
                action,
            )
            return
        room_policy = (
            _resource_room_policies.get(type(room).__name__)
            if room is not None
            else None
        )
        if room is None and subject not in _event_authorizations:
            logger.error("Refused WebSocket event without a domain resource policy: {}", subject)
            return
        if room is not None and (
            room_policy is None or room_policy.subject != subject
        ):
            logger.error(
                "Refused WebSocket room emission without the matching resource policy: "
                "subject={} action={} room={}",
                subject,
                action,
                room,
            )
            return

        event_name = f"{subject}.{action}"
        displayed_room = str(room) if room_policy and room_policy.displayed_only else None
        identities = tuple(
            (sid, identity)
            for sid, identity in _connected_identities.items()
            if _event_is_requested(sid, event_name)
            and (displayed_room is None or _displayed_resource_rooms.get(sid) == displayed_room)
        )
        if not identities:
            return

        async with get_db_session():
            db = get_db()
            user_ids = {identity.user_id for _, identity in identities}
            result = await db.execute(select(User).where(User.id.in_(user_ids)))
            users = {user.id: user for user in result.scalars().all()}

            recipients: list[str] = []
            valid_tokens: dict[str, bool] = {}
            permissions: dict[tuple[int, int | None], bool] = {}
            for sid, identity in identities:
                user = users.get(identity.user_id)
                if identity.token not in valid_tokens:
                    valid_tokens[identity.token] = await _identity_is_valid(identity, user)
                if not valid_tokens[identity.token]:
                    await _disconnect_invalid(sid)
                    continue
                permission_key = (identity.user_id, identity.role_id)
                if permission_key in permissions:
                    if permissions[permission_key]:
                        recipients.append(sid)
                    continue
                role_token = role_id_ctx.set(identity.role_id)
                try:
                    allowed = user is not None and await check_privilege(
                        user, list(required_privileges), db, role_id=identity.role_id,
                    )
                    if allowed and user is not None and subject in _event_authorizations:
                        allowed = await _event_authorizations[subject](user, action, data)
                    if allowed and room is not None and room_policy is not None:
                        allowed = await room_policy.authorize(identity.user_id, str(room.resource_id))
                finally:
                    role_id_ctx.reset(role_token)
                permissions[permission_key] = bool(allowed)
                if allowed:
                    recipients.append(sid)

        logger.info(
            "📡 Emitting {}.{} to {} authorized WebSocket client(s)",
            subject,
            action,
            len(recipients),
        )
        for sid in recipients:
            if sid not in _connected_identities or not _event_is_requested(sid, event_name):
                continue
            # The page may have closed while authorization was awaiting the DB.
            if displayed_room is not None and _displayed_resource_rooms.get(sid) != displayed_room:
                continue
            await _sio.emit(  # type: ignore
                event_name,
                {"data": data},
                room=sid,
            )


def stop() -> None:
    """
    Stop the WebSocket server.

    This remains a placeholder for future cleanup logic.
    """
    pass


def _parse_event_subscriptions(raw: object) -> frozenset[str] | None:
    if not isinstance(raw, list):
        return None
    requested = cast(list[object], raw)
    if len(requested) > 128:
        return None
    events: set[str] = set()
    for event in requested:
        if not isinstance(event, str) or len(event) > 128:
            return None
        subject, separator, action = event.partition(".")
        if subject not in _EVENT_PRIVILEGES or not separator or not action:
            return None
        if not action.isascii() or not action.replace("_", "").isalnum():
            return None
        events.add(event)
    return frozenset(events)


def _event_is_requested(sid: str, event_name: str) -> bool:
    subscriptions = _event_subscriptions.get(sid)
    return subscriptions is None or event_name in subscriptions


async def _handle_event_subscriptions(sid: str, data: object) -> bool:
    """Interest narrows delivery; it never grants privileges or resource access."""
    if sid not in _connected_identities or not isinstance(data, Mapping):
        return False
    subscriptions = _parse_event_subscriptions(cast(Mapping[object, object], data).get("events"))
    if subscriptions is None:
        return False
    _event_subscriptions[sid] = subscriptions
    return True


def _extract_auth_token(auth: object) -> str | None:
    """Return a bounded token from the Socket.IO authentication payload."""
    if not isinstance(auth, Mapping):
        return None
    auth_payload = cast(Mapping[object, object], auth)
    token = auth_payload.get("token")
    if not isinstance(token, str):
        return None
    token = token.strip()
    if not token or len(token) > _MAX_AUTH_TOKEN_LENGTH:
        return None
    return token


def _role_id_from_token(token: str) -> int | None:
    """Return the signed active-role claim, or None for personal API tokens."""
    try:
        payload: dict[str, Any] = jwt.decode(  # type: ignore
            token,
            auth_secret_key(),
            algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None
    role_id = payload.get("role_id")
    if isinstance(role_id, int) and not isinstance(role_id, bool):
        return role_id
    return None


def _access_claims_from_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token, auth_secret_key(), algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None


async def _authenticate_socket_token(token: str) -> _SocketIdentity | None:
    """Authenticate one handshake without retaining a connection-long DB session."""
    try:
        async with get_db_session():
            user = await authenticate_from_jwt_token(token)
            return _SocketIdentity(
                user_id=user.id,
                role_id=_role_id_from_token(token),
                token=token,
                access_claims=_access_claims_from_token(token),
            )
    except AuthenticationError:
        return None
    finally:
        deauthenticate()


async def _handle_connect(
    sid: str,
    environ: dict[str, Any],
    auth: object = None,
) -> bool:
    """
    Authenticate and accept a frontend client connection.

    Args:
        sid: Unique client session ID.
        environ: Connection request environment including HTTP headers.
        auth: Socket.IO authentication payload.

    Returns:
        True when the connection is authenticated, otherwise False.
    """
    del environ
    token = _extract_auth_token(auth)
    if token is None:
        logger.warning("Rejected unauthenticated WebSocket connection: {}", sid)
        return False

    subscriptions: frozenset[str] | None = None
    if isinstance(auth, Mapping) and "events" in auth:
        subscriptions = _parse_event_subscriptions(cast(Mapping[object, object], auth)["events"])
        if subscriptions is None:
            return False

    identity = await _authenticate_socket_token(token)
    if identity is None:
        logger.warning("Rejected invalid WebSocket authentication: {}", sid)
        return False

    logger.debug(
        "Authenticated WebSocket client: {} user_id={} role_id={}",
        sid,
        identity.user_id,
        identity.role_id,
    )
    _displayed_resource_rooms.pop(sid, None)
    _room_display_requests.pop(sid, None)
    _connected_identities[sid] = identity
    _event_subscriptions.pop(sid, None)
    if subscriptions is not None:
        _event_subscriptions[sid] = subscriptions

    if _sio:
        await _sio.save_session(  # type: ignore
            sid,
            {"user_id": identity.user_id, "role_id": identity.role_id},
        )
        await _sio.emit("welcome", {"message": "Welcome to this server !"}, room=sid)  # type: ignore
    return True


async def _handle_disconnect(sid: str) -> None:
    """
    Handle client disconnection after tab closure or network loss.

    Args:
        sid: Disconnected client session ID.
    """
    _connected_identities.pop(sid, None)
    _displayed_resource_rooms.pop(sid, None)
    _room_display_requests.pop(sid, None)
    logger.debug("WebSocket client disconnected: {}", sid)
    _event_subscriptions.pop(sid, None)


async def _resource_room_is_authorized(sid: str, raw_room: object) -> bool:
    identity = _connected_identities.get(sid)
    if identity is None or not isinstance(raw_room, str) or ":" not in raw_room:
        return False
    room_type_name, resource_id = raw_room.split(":", 1)
    policy = _resource_room_policies.get(room_type_name)
    if policy is None or not resource_id or len(resource_id) > 512:
        return False
    async with get_db_session():
        if not await _identity_is_valid(identity):
            await _disconnect_invalid(sid)
            return False
        db = get_db()
        user = await db.get(User, identity.user_id)
        role_token = role_id_ctx.set(identity.role_id)
        try:
            return bool(
                user is not None
                and await check_privilege(
                    user, list(policy.required_privileges), db, role_id=identity.role_id,
                )
                and await policy.authorize(identity.user_id, resource_id)
            )
        finally:
            role_id_ctx.reset(role_token)


async def _handle_room_join(sid: str, data: Dict[str, Any]) -> bool:
    """
    Handle an explicit frontend room-join request.

    Args:
        sid: Client session ID.
        data: Request data containing the room name.
    """
    raw_room = data.get("room")
    allowed = await _resource_room_is_authorized(sid, raw_room)
    if not allowed or _sio is None:
        logger.warning(
            "Rejected unauthorized WebSocket room join request: sid={} room={}",
            sid,
            raw_room,
        )
        return False
    await _sio.enter_room(sid, raw_room)  # type: ignore
    logger.debug("SID {} joined resource room {}", sid, raw_room)
    return True


async def _handle_room_display(sid: str, data: Dict[str, Any]) -> bool:
    """Track the resource room actually rendered by one authenticated client."""

    raw_room = data.get("room")
    _displayed_resource_rooms.pop(sid, None)
    _room_display_requests.pop(sid, None)
    if raw_room is None:
        return sid in _connected_identities
    request = object()
    _room_display_requests[sid] = request
    try:
        allowed = await _resource_room_is_authorized(sid, raw_room)
        # A newer display request or a disconnect supersedes this DB lookup.
        if _room_display_requests.get(sid) is not request:
            return False
        if not allowed:
            logger.warning(
                "Rejected unauthorized displayed WebSocket room: sid={} room={}",
                sid,
                raw_room,
            )
            return False
        assert isinstance(raw_room, str)
        _displayed_resource_rooms[sid] = raw_room
        return True
    finally:
        if _room_display_requests.get(sid) is request:
            _room_display_requests.pop(sid, None)


def is_room_displayed_by_user(user_id: int, room_name: str) -> bool:
    """Return whether one connected client currently renders the resource room."""

    return any(
        identity.user_id == user_id
        and _displayed_resource_rooms.get(sid) == room_name
        for sid, identity in _connected_identities.items()
    )


async def _handle_room_leave(sid: str, data: Dict[str, Any]) -> None:
    """
    Handle an explicit frontend room-leave request.

    Args:
        sid: Client session ID.
        data: Request data containing the room name.
    """
    room_name = data.get("room")
    if room_name:
        await _leave_room(sid, room_name)


async def _leave_room(sid: str, room_name: str) -> None:
    """
    Remove a client from a room.

    Args:
        sid: Client session ID.
        room_name: Technical room name.
    """
    if _sio:
        await _sio.leave_room(sid, room_name)  # type: ignore
        logger.debug("SID {} left room {}", sid, room_name)
