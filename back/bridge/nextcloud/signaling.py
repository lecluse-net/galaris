"""
Real-time Nextcloud Talk reception through HPB WebSocket signaling.

Ported from ``refs/mcp-next-talk-bridge/src/signaling/``. Each room opens one
WebSocket to the High Performance Backend, providing native push at the cost of
requiring an HPB. Its URL comes from inbound options or Talk discovery.

Each ``TalkSignalingRoom`` calls ``join_call``, opens a Talk-subprotocol WebSocket,
authenticates with ``hello``, then listens with keep-alive pings and reconnect
backoff. Raw chat reaches the callback; the messenger handles relevance and echoes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from core.util import as_dict, as_list
from core.i18n import render_prompt, t
from .client import NextcloudTalkClient

# WebSocket subprotocol expected by the Nextcloud Talk HPB.
_SUBPROTOCOL = "com.nextcloud.spreed-signaling-v1"
# Keep-alive ping interval in seconds.
_PING_INTERVAL = 30.0
# Reconnection backoff bounds in seconds.
_RECONNECT_DELAY = 1.0
_MAX_RECONNECT_DELAY = 60.0

RawHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]
RefreshHandler = Callable[[str], Awaitable[None]]
EventHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


def normalize_hpb_url(url: str) -> str:
    """Normalize an HPB base URL to Talk's WebSocket ``/spreed`` endpoint.

    The signaling settings expose the external signaling *base* URL, while the
    Android client always appends ``spreed`` before opening the WebSocket.
    Explicit endpoint URLs that already end in ``/spreed`` are preserved.
    """
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("https://"):
        url = "wss://" + url.removeprefix("https://")
    elif url.startswith("http://"):
        url = "ws://" + url.removeprefix("http://")
    elif "://" not in url:
        url = f"wss://{url}"
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/spreed"):
        path += "/spreed"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def extract_hpb_url(settings: Dict[str, Any]) -> str:
    """Extract the HPB WebSocket URL from Talk signaling settings.

    Accept current and legacy schema variants: ``signaling_url``, ``server``,
    ``hpbUrl``, or ``servers[].server``. Return an empty string in internal mode.
    """
    direct = (
        settings.get("signaling_url")
        or settings.get("signalingUrl")
        or settings.get("server")
        or settings.get("hpbUrl")
        or settings.get("hpb_url")
    )
    if isinstance(direct, str) and direct:
        return normalize_hpb_url(direct)
    servers = settings.get("servers")
    if isinstance(servers, list):
        for s_item in as_list(servers):
            s = as_dict(s_item)
            server = s.get("server")
            if isinstance(server, str) and server:
                return normalize_hpb_url(server)
    return ""


def build_hello_message(
    nextcloud_url: str,
    settings: Dict[str, Any],
    *,
    legacy_room_token: str = "",
    legacy_session_id: str = "",
    legacy_user_id: str = "",
    client_features: Sequence[str] = (),
) -> Dict[str, Any]:
    """Build the ``hello`` message expected by standalone signaling.

    Talk publishes valid parameters in ``helloAuthParams``. Version 2.0 uses a
    preferred Nextcloud-signed JWT; version 1.0 uses a user ticket.

    ``legacy_*`` fields support older instances without ``helloAuthParams``.
    """
    hello_auth_params = as_dict(settings.get("helloAuthParams"))
    features = [str(feature) for feature in client_features if feature]
    if hello_auth_params:
        v2 = as_dict(hello_auth_params.get("2.0"))
        if v2.get("token"):
            msg: Dict[str, Any] = {
                "type": "hello",
                "hello": {
                    "version": "2.0",
                    "auth": {
                        "type": "client",
                        "url": nextcloud_url,
                        "params": {"token": v2["token"]},
                    },
                },
            }
            if features:
                msg["hello"]["features"] = features
            return msg
        v1 = hello_auth_params.get("1.0")
        if isinstance(v1, dict):
            msg = {
                "type": "hello",
                "hello": {
                    "version": "1.0",
                    "auth": {
                        "type": "client",
                        "url": nextcloud_url,
                        "params": as_dict(v1),
                    },
                },
            }
            if features:
                msg["hello"]["features"] = features
            return msg

    msg = {
        "type": "hello",
        "hello": {
            "version": "1.0",
            "auth": {
                "type": "client",
                "url": nextcloud_url,
                "params": {
                    "token": legacy_room_token,
                    "session": legacy_session_id,
                    "userid": legacy_user_id,
                },
            },
        },
    }
    if features:
        msg["hello"]["features"] = features
    return msg


def build_resume_hello_message(
    resume_id: str,
    *,
    client_features: Sequence[str] = (),
) -> Dict[str, Any]:
    """Build the abbreviated Android-compatible hello used to resume an HPB session."""
    hello: Dict[str, Any] = {
        "version": "1.0",
        "resumeid": resume_id,
    }
    features = [str(feature) for feature in client_features if feature]
    if features:
        hello["features"] = features
    return {"type": "hello", "hello": hello}


def build_room_join_message(
    room_token: str,
    session_id: str,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an HPB ``room`` message, including federation data when published."""
    room: Dict[str, Any] = {"roomid": room_token, "sessionid": session_id}
    federation = _extract_federation(settings)
    if federation:
        room["federation"] = federation
    return {"type": "room", "room": room}


def _extract_federation(settings: Dict[str, Any]) -> Dict[str, Any]:
    raw = settings.get("federation")
    if not isinstance(raw, dict):
        return {}

    # The Talk settings API uses Android model names (server,
    # nextcloudServer, roomId, helloAuthParams), while the HPB room message
    # expects signaling, url, roomid and token. Also accept already-normalized
    # values so callers can pass the wire representation directly.
    raw_federation = as_dict(raw)
    federation: Dict[str, Any] = {}
    signaling = raw_federation.get("signaling") or raw_federation.get("server")
    if signaling:
        # Unlike the primary ``server`` setting, Android forwards the
        # federation server verbatim in the room message. The Talk backend has
        # already produced the remote WebSocket URL expected by the HPB.
        federation["signaling"] = str(signaling)

    backend_url = raw_federation.get("url")
    if not backend_url and raw_federation.get("nextcloudServer"):
        backend_url = (
            str(raw_federation["nextcloudServer"]).rstrip("/")
            + "/ocs/v2.php/apps/spreed/api/v3/signaling/backend"
        )
    if backend_url:
        federation["url"] = str(backend_url)

    room_id = raw_federation.get("roomid") or raw_federation.get("roomId")
    if room_id:
        federation["roomid"] = str(room_id)

    token = raw_federation.get("token") or as_dict(
        raw_federation.get("helloAuthParams")
    ).get("token")
    if token:
        federation["token"] = str(token)

    mapped_keys = {
        "signaling",
        "server",
        "url",
        "nextcloudServer",
        "roomid",
        "roomId",
        "token",
        "helloAuthParams",
    }
    for key, value in raw_federation.items():
        if key in mapped_keys:
            continue
        if value in (None, ""):
            continue
        cleaned = _json_compatible(value)
        if cleaned is not None:
            federation[str(key)] = cleaned
    return federation


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        cleaned = [_json_compatible(item) for item in as_list(value)]
        return [item for item in cleaned if item is not None]
    if isinstance(value, dict):
        cleaned_dict: Dict[str, Any] = {}
        for key, item in as_dict(value).items():
            if item in (None, ""):
                continue
            cleaned_item = _json_compatible(item)
            if cleaned_item is not None:
                cleaned_dict[str(key)] = cleaned_item
        return cleaned_dict
    return None


class TalkSignalingRoom:
    """Self-reconnecting HPB WebSocket connection for one room."""

    def __init__(
        self,
        hpb_url: str,
        client: NextcloudTalkClient,
        room_token: str,
        self_id: str,
        nextcloud_url: str,
        on_raw: RawHandler,
        on_refresh: RefreshHandler | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self._hpb_url = hpb_url
        self._client = client
        self._room_token = room_token
        self._self_id = self_id
        self._nextcloud_url = nextcloud_url.rstrip("/")
        self._on_raw = on_raw
        self._on_refresh = on_refresh
        self._on_event = on_event

        self._websocket: Any = None
        self._running = False
        self._delay = _RECONNECT_DELAY
        self._ping_task: Optional["asyncio.Task[None]"] = None
        self._catchup_task: Optional["asyncio.Task[None]"] = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Connect and listen with exponential backoff until ``stop()``."""
        self._running = True
        while self._running:
            try:
                await self._connect()
                self._delay = _RECONNECT_DELAY  # Reset after a successful connection.
                # After joining, catch up messages already posted through OCS because
                # push only delivers future events. Run concurrently with the listener.
                self._catchup_task = asyncio.create_task(
                    self._catch_up_backlog(), name=f"talk_sig_catchup_{self._room_token}"
                )
                await self._listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Talk signaling [{}] WebSocket error: {}", self._room_token, exc)
            finally:
                await self._close_ping()
                await self._close_catchup()
                await self._close_websocket()
            if self._running:
                logger.info(
                    "Talk signaling [{}] reconnecting in {}s", self._room_token, self._delay
                )
                await asyncio.sleep(self._delay)
                self._delay = min(self._delay * 2, _MAX_RECONNECT_DELAY)

    async def stop(self) -> None:
        self._running = False
        await self._close_ping()
        await self._close_catchup()
        await self._close_websocket()

    async def _close_websocket(self) -> None:
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception as exc:
                logger.debug(
                    "Talk signaling [{}] websocket close failed: {}",
                    self._room_token,
                    type(exc).__name__,
                )
            self._websocket = None

    async def _close_ping(self) -> None:
        if self._ping_task is not None:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

    async def _close_catchup(self) -> None:
        if self._catchup_task is not None:
            self._catchup_task.cancel()
            try:
                await self._catchup_task
            except asyncio.CancelledError:
                pass
            self._catchup_task = None

    async def _catch_up_backlog(self) -> None:
        """Replay through OCS messages posted before the WebSocket was established.

        Signaling pushes only messages after connection, so a newly discovered
        room or reconnect may contain unprocessed events. Because the room is
        already joined at the HPB, events posted during catch-up queue server-side
        until listening begins, avoiding a loss window. ``_on_raw`` retains common
        relevance, echo, and deduplication handling.
        """
        try:
            await self._refresh_room_from_ocs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Talk signaling [{}] post-connect backlog catch-up failed",
                self._room_token,
            )

    async def _connect(self) -> None:
        """Open the WebSocket and authenticate to the HPB with ``hello``."""
        import websockets

        session = await self._client.join_call(self._room_token)
        session_id = session.get("sessionId")
        if not session_id:
            raise RuntimeError(_error(
                "session_missing", room_id=self._room_token
            ))

        settings = await self._client.get_signaling_settings(self._room_token)
        room_hpb_url = extract_hpb_url(settings) or self._hpb_url
        if room_hpb_url != self._hpb_url:
            logger.info("Talk signaling [{}] room-specific HPB={}", self._room_token, room_hpb_url)
        self._websocket = await websockets.connect(
            room_hpb_url, subprotocols=[_SUBPROTOCOL]  # type: ignore[list-item]
        )
        hello = build_hello_message(
            self._nextcloud_url,
            settings,
            legacy_room_token=self._room_token,
            legacy_session_id=session_id,
            legacy_user_id=self._self_id,
            client_features=("chat-relay",),
        )
        await self._websocket.send(json.dumps(hello))
        hello_resp = await self._recv_until("hello", timeout=10.0)
        sig_session = as_dict(hello_resp.get("hello")).get("sessionid", "")

        await self._websocket.send(json.dumps(build_room_join_message(
            self._room_token,
            session_id,
            settings,
        )))
        await self._recv_until("room", timeout=10.0)
        logger.info(
            "Talk signaling [{}] connected and joined room (sig_session={})",
            self._room_token,
            sig_session,
        )
        self._ping_task = asyncio.create_task(
            self._keep_alive(), name=f"talk_sig_ping_{self._room_token}"
        )

    async def _recv_until(self, msg_type: str, timeout: float) -> Dict[str, Any]:
        async def _loop() -> Dict[str, Any]:
            while self._websocket is not None:
                raw = await self._websocket.recv()
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                current_type = event.get("type")
                if current_type == msg_type:
                    return event
                if current_type in ("welcome", "pong"):
                    continue
                if current_type == "error":
                    error = as_dict(event.get("error"))
                    code = str(error.get("code") or "")
                    if msg_type == "room" and code == "already_joined":
                        return event
                    raise RuntimeError(_error("hpb_error", error=error or event))
            raise RuntimeError(_error("hpb_connection_closed"))

        return await asyncio.wait_for(_loop(), timeout=timeout)

    async def _listen(self) -> None:
        while self._running and self._websocket is not None:
            raw = await self._websocket.recv()
            await self._handle(raw)

    async def _handle(self, raw_message: str | bytes) -> None:
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            event = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return
        msg_type = event.get("type")
        if msg_type in ("pong", "welcome", "hello", "room"):
            return
        if msg_type == "error":
            logger.warning(
                "Talk signaling [{}] HPB error : {}",
                self._room_token, event.get("error", {}).get("message", "?"),
            )
            return
        if msg_type == "message":
            await self._handle_message_envelope(event.get("message"))
            return
        if msg_type == "event":
            payload_raw = event.get("event")
            if not isinstance(payload_raw, dict):
                return
            payload = as_dict(payload_raw)
            if self._on_event is not None:
                try:
                    await self._on_event(self._room_token, payload)
                except Exception:
                    logger.exception(
                        "Talk signaling [{}] event handler failed",
                        self._room_token,
                    )
            if payload.get("target") == "room" and payload.get("type") == "message":
                await self._handle_message_envelope(payload.get("message"))

    async def _handle_message_envelope(self, envelope_raw: Any) -> None:
        if not isinstance(envelope_raw, dict):
            return
        envelope = as_dict(envelope_raw)
        if _looks_like_chat_comment(envelope):
            await self._on_raw(self._room_token, envelope)
            return
        data = envelope.get("data")
        if isinstance(data, dict):
            await self._handle_message_data(as_dict(data))
            return
        if envelope.get("type") == "chat":
            await self._handle_message_data(envelope)

    async def _handle_message_data(self, data: Dict[str, Any]) -> None:
        if _looks_like_chat_comment(data):
            await self._on_raw(self._room_token, data)
            return
        if data.get("type") != "chat":
            return

        chat = as_dict(data.get("chat"))
        if not chat:
            return

        dispatched = False
        comments = chat.get("comments")
        if isinstance(comments, list):
            for comment_item in as_list(comments):
                if isinstance(comment_item, dict):
                    await self._on_raw(self._room_token, as_dict(comment_item))
                    dispatched = True

        comment = chat.get("comment")
        if isinstance(comment, dict):
            await self._on_raw(self._room_token, as_dict(comment))
            dispatched = True

        if not dispatched and chat.get("refresh"):
            await self._refresh_room_from_ocs()

    async def _refresh_room_from_ocs(self) -> None:
        if self._on_refresh is not None:
            await self._on_refresh(self._room_token)
            return
        try:
            raws = await self._client.get_messages(self._room_token, look_into_future=0, limit=20)
        except Exception:
            logger.exception("Talk signaling [{}] OCS refresh failed", self._room_token)
            return
        for raw in sorted(as_list(raws), key=lambda r: int(as_dict(r).get("id", 0) or 0)):
            if isinstance(raw, dict):
                await self._on_raw(self._room_token, as_dict(raw))

    async def _keep_alive(self) -> None:
        while self._running and self._websocket is not None:
            try:
                await asyncio.sleep(_PING_INTERVAL)
                if self._websocket is not None and self._running:
                    await self._websocket.send(json.dumps({"type": "ping"}))
            except asyncio.CancelledError:
                break
            except Exception:
                break


def _looks_like_chat_comment(value: Dict[str, Any]) -> bool:
    return (
        "id" in value
        and "message" in value
        and (
            "actorId" in value
            or "actorType" in value
            or "actorDisplayName" in value
            or "timestamp" in value
        )
    )
