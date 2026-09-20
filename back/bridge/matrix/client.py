"""
Low-level Matrix v3 Client-Server API client using ``httpx``.

Protocol-specific event models, HTTP calls, and the ``/sync`` loop remain in
this file. ``messenger.py`` converts them to canonical messages. Unlike OneBot,
Galaris acts as a client of a Matrix homeserver.

Shared environment settings:
    - ``MESSENGER_MATRIX_HOMESERVER``
    - ``MESSENGER_MATRIX_SYNC_TIMEOUT_MS``

Connection parameters:
    - ``user_id``: bot identifier (for example ``@bot:example.org``)
    - ``access_token``: recommended long-lived token
    - ``password``: optional fallback when no token is provided
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional
from urllib.parse import quote, urlsplit

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from core.i18n import render_prompt, t
from core.params import runtime_settings
from core.util import as_dict, as_list

from .schemas import MatrixConnectionConfig


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


# Stable Client-Server API prefix.
MATRIX_API = "/_matrix/client/v3"
# Authenticated media downloads introduced in Matrix 1.11.
MATRIX_MEDIA_API = "/_matrix/client/v1/media"
# Upload remains on the stable media v3 endpoint.
MATRIX_MEDIA_UPLOAD_API = "/_matrix/media/v3"
# A long read timeout accommodates the /sync long poll.
MATRIX_TIMEOUT = httpx.Timeout(connect=10.0, read=70.0, write=30.0, pool=10.0)
_MEDIA_CHUNK_BYTES = 64 * 1024
_MATRIX_CONTENT_MAX_BYTES = 100_000_000
# --- Matrix wire models (m.room.message events) ---


class MatrixContent(BaseModel):
    """Content of an ``m.room.message`` event."""

    msgtype: Optional[str] = None  # m.text, m.notice, m.image…
    body: str = ""
    filename: str = ""
    url: Optional[str] = None
    info: dict[str, Any] = Field(default_factory=dict)
    encrypted_file: dict[str, Any] = Field(default_factory=dict, alias="file")
    relates_to: dict[str, Any] = Field(default_factory=dict, alias="m.relates_to")
    mentions: dict[str, Any] = Field(default_factory=dict, alias="m.mentions")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class MatrixMessageEvent(BaseModel):
    """Matrix timeline event of type ``m.room.message``."""

    event_id: str = ""
    sender: str = ""              # @user:server
    type: str = ""
    origin_server_ts: int = 0     # Timestamp in milliseconds.
    room_id: Optional[str] = None
    content: MatrixContent = Field(default_factory=MatrixContent)

    model_config = ConfigDict(extra="ignore")


# --- Low-level Matrix Client-Server API client ---


class Matrix:
    """Low-level HTTP client for the Matrix v3 Client-Server API."""

    def __init__(
        self,
        homeserver: str = "",
        user_id: str = "",
        access_token: str = "",
        password: str = "",
        sync_timeout_ms: int = 30000,
        *,
        allowed_user_ids: frozenset[str] = frozenset(),
        allowed_room_ids: frozenset[str] = frozenset(),
        require_group_mention: bool = False,
        auto_join_invites: bool = False,
        media_max_bytes: int | None = None,
    ) -> None:
        self.homeserver = homeserver.rstrip("/")
        self.user_id: str = user_id
        self.access_token = access_token
        self.password = password
        self.sync_timeout_ms = sync_timeout_ms
        self.platform = ""
        self.tool_id = 0
        self.allowed_user_ids = allowed_user_ids
        self.allowed_room_ids = allowed_room_ids
        self.require_group_mention = require_group_mention
        self.auto_join_invites = auto_join_invites
        requested_content_max = (
            runtime_settings.messenger_content_max_bytes
            if media_max_bytes is None
            else media_max_bytes
        )
        self.media_max_bytes = min(
            requested_content_max,
            _MATRIX_CONTENT_MAX_BYTES,
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._direct_room_lock = asyncio.Lock()

    @classmethod
    async def from_connection(cls, connection: Any) -> "Matrix":
        """Create a Matrix client from a Connection object."""
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            int(connection.id),
            expected_service="matrix",
        )
        params = resolved.params
        config = MatrixConnectionConfig.model_validate(
            {
                **params,
                "access_token": params.get("token", ""),
            }
        )
        instance = cls(
            homeserver=resolved.settings.get("homeserver", ""),
            user_id=config.user_id,
            access_token=config.access_token,
            password=config.password,
            sync_timeout_ms=runtime_settings.MESSENGER_MATRIX_SYNC_TIMEOUT_MS,
            allowed_user_ids=config.users,
            allowed_room_ids=config.rooms,
            require_group_mention=config.require_group_mention,
            auto_join_invites=config.auto_join_invites,
        )
        if not instance.homeserver:
            raise ValueError(_error("matrix_homeserver_required"))
        # Matrix connections remain Matrix regardless of the legacy default
        # provider kept for upgrade compatibility.
        instance.platform = "matrix"
        instance.tool_id = int(connection.tool_id) if connection.tool_id else 0
        return instance

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "Matrix":
        """Create a Matrix client from a connection ID."""
        from app.connection.connection_service import get_connection

        connection = await get_connection(connection_id)
        if not connection:
            raise ValueError(_error(
                "connection_not_found", connection_id=connection_id
            ))
        return await cls.from_connection(connection)

    # -- HTTP plumbing --

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.homeserver, timeout=MATRIX_TIMEOUT
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        return (
            {"Authorization": f"Bearer {self.access_token}"}
            if self.access_token
            else {}
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_token(self) -> None:
        """Ensure an access token exists, logging in with a password when needed."""
        if self.access_token:
            return
        if not self.password:
            raise RuntimeError(_error("matrix_credentials_required"))
        await self.login()

    # -- API Matrix --

    async def login(self) -> dict[str, Any]:
        """Log in with a password and retain the returned access token."""
        payload: dict[str, Any] = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": self.user_id},
            "password": self.password,
        }
        resp = await self._http().post(f"{MATRIX_API}/login", json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        self.access_token = data.get("access_token", "")
        self.user_id = str(data.get("user_id") or self.user_id)
        return data

    async def whoami(self) -> str:
        """Return the authenticated Matrix user ID."""

        await self._ensure_token()
        resp = await self._http().get(
            f"{MATRIX_API}/account/whoami",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        user_id = str(as_dict(resp.json()).get("user_id") or "")
        if not user_id:
            raise ValueError("Matrix whoami response has no user_id")
        self.user_id = user_id
        return user_id

    async def search_users(self, query: str) -> list[dict[str, Any]]:
        """Search the homeserver user directory without truncating in Galaris."""

        term = query.strip()
        await self._ensure_token()
        response = await self._http().post(
            f"{MATRIX_API}/user_directory/search",
            headers=self._auth_headers(),
            json={"search_term": term, "limit": 10_000},
        )
        response.raise_for_status()
        return [
            as_dict(item)
            for item in as_list(as_dict(response.json()).get("results"))
            if as_dict(item).get("user_id")
        ]

    async def send_message(
        self,
        room_id: str,
        body: str,
        msgtype: str = "m.text",
        *,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Send an ``m.room.message`` with an idempotent txnId-based PUT."""

        content: dict[str, Any] = {"msgtype": msgtype, "body": body}
        if reply_to:
            content["m.relates_to"] = {
                "m.in_reply_to": {"event_id": reply_to}
            }
        return await self.send_room_event(room_id, "m.room.message", content)

    async def send_room_event(
        self,
        room_id: str,
        event_type: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Send an arbitrary room event with an idempotent transaction ID."""
        await self._ensure_token()
        txn_id = str(uuid.uuid4())
        url = (
            f"{MATRIX_API}/rooms/{quote(room_id, safe='')}"
            f"/send/{quote(event_type, safe='')}/{txn_id}"
        )
        resp = await self._http().put(
            url, headers=self._auth_headers(), json=content
        )
        resp.raise_for_status()
        return resp.json()

    async def upload_media(
        self,
        content: bytes,
        filename: str,
        mime: str,
    ) -> str:
        """Upload bounded bytes and return their ``mxc://`` URI."""

        if len(content) > self.media_max_bytes:
            raise ValueError("Matrix media exceeds the configured size limit")
        await self._ensure_token()
        resp = await self._http().post(
            f"{MATRIX_MEDIA_UPLOAD_API}/upload",
            headers={
                **self._auth_headers(),
                "Content-Type": mime,
            },
            params={"filename": filename},
            content=content,
        )
        resp.raise_for_status()
        content_uri = str(as_dict(resp.json()).get("content_uri") or "")
        self._parse_mxc(content_uri)
        return content_uri

    async def upload_media_path(
        self,
        path: Path,
        filename: str,
        mime: str,
    ) -> str:
        """Stream one bounded local file into the Matrix content repository."""

        size = path.stat().st_size
        if size > self.media_max_bytes:
            raise ValueError("Matrix media exceeds the configured size limit")
        await self._ensure_token()

        async def chunks() -> AsyncIterator[bytes]:
            transferred = 0
            with path.open("rb") as source:
                while chunk := await asyncio.to_thread(
                    source.read, _MEDIA_CHUNK_BYTES
                ):
                    transferred += len(chunk)
                    if transferred > self.media_max_bytes:
                        raise ValueError(
                            "Matrix media exceeds the configured size limit"
                        )
                    yield chunk

        resp = await self._http().post(
            f"{MATRIX_MEDIA_UPLOAD_API}/upload",
            headers={
                **self._auth_headers(),
                "Content-Type": mime,
                "Content-Length": str(size),
            },
            params={"filename": filename},
            content=chunks(),
        )
        resp.raise_for_status()
        content_uri = str(as_dict(resp.json()).get("content_uri") or "")
        self._parse_mxc(content_uri)
        return content_uri

    @staticmethod
    def _parse_mxc(content_uri: str) -> tuple[str, str]:
        parsed = urlsplit(content_uri)
        media_id = parsed.path.removeprefix("/")
        if (
            parsed.scheme != "mxc"
            or not parsed.netloc
            or not media_id
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Invalid Matrix content URI")
        return parsed.netloc, media_id

    async def _open_media_response(self, content_uri: str) -> httpx.Response:
        """Open an authenticated media response, with an old-server fallback."""

        await self._ensure_token()
        server_name, media_id = self._parse_mxc(content_uri)
        path = (
            f"{MATRIX_MEDIA_API}/download/{quote(server_name, safe='')}"
            f"/{quote(media_id, safe='')}"
        )
        request = self._http().build_request(
            "GET",
            path,
            headers=self._auth_headers(),
        )
        response = await self._http().send(
            request,
            stream=True,
            follow_redirects=True,
        )
        if response.status_code not in {404, 405}:
            return response

        await response.aclose()
        legacy_path = (
            f"{MATRIX_MEDIA_UPLOAD_API}/download/{quote(server_name, safe='')}"
            f"/{quote(media_id, safe='')}"
        )
        legacy_request = self._http().build_request(
            "GET",
            legacy_path,
            headers=self._auth_headers(),
        )
        return await self._http().send(
            legacy_request,
            stream=True,
            follow_redirects=True,
        )

    @staticmethod
    def _validate_media_length(response: httpx.Response, max_bytes: int) -> None:
        raw_length = response.headers.get("content-length")
        if not raw_length:
            return
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Matrix media has an invalid content length") from exc
        if length < 0:
            raise ValueError("Matrix media has an invalid content length")
        if length > max_bytes:
            raise ValueError("Matrix media exceeds the configured size limit")

    async def download_media(
        self,
        content_uri: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """Download media with authentication and a hard byte limit."""

        requested_limit = self.media_max_bytes if max_bytes is None else max_bytes
        if requested_limit < 1:
            raise ValueError("Matrix media size limit must be positive")
        limit = min(requested_limit, self.media_max_bytes)
        response = await self._open_media_response(content_uri)
        try:
            response.raise_for_status()
            self._validate_media_length(response, limit)
            content = bytearray()
            async for chunk in response.aiter_bytes(_MEDIA_CHUNK_BYTES):
                content.extend(chunk)
                if len(content) > limit:
                    raise ValueError(
                        "Matrix media exceeds the configured size limit"
                    )
            return bytes(content)
        finally:
            await response.aclose()

    async def download_media_to_file(
        self,
        content_uri: str,
        dest: Path,
        *,
        max_bytes: int | None = None,
    ) -> int:
        """Download media to an atomic temporary file with bounded memory."""

        requested_limit = self.media_max_bytes if max_bytes is None else max_bytes
        if requested_limit < 1:
            raise ValueError("Matrix media size limit must be positive")
        limit = min(requested_limit, self.media_max_bytes)
        response = await self._open_media_response(content_uri)
        part = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
        try:
            response.raise_for_status()
            self._validate_media_length(response, limit)
            size = 0
            with part.open("wb") as target:
                async for chunk in response.aiter_bytes(_MEDIA_CHUNK_BYTES):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError(
                            "Matrix media exceeds the configured size limit"
                        )
                    target.write(chunk)
            os.replace(part, dest)
            return size
        finally:
            await response.aclose()
            part.unlink(missing_ok=True)

    async def joined_members(self, room_id: str) -> dict[str, dict[str, Any]]:
        """Return joined room members keyed by Matrix user ID."""
        await self._ensure_token()
        resp = await self._http().get(
            f"{MATRIX_API}/rooms/{quote(room_id, safe='')}/joined_members",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        joined = as_dict(as_dict(resp.json()).get("joined"))
        return {str(user_id): as_dict(profile) for user_id, profile in joined.items()}

    async def room_is_encrypted(self, room_id: str) -> bool:
        """Fail closed unless the room's encryption state can be checked."""
        await self._ensure_token()
        resp = await self._http().get(
            f"{MATRIX_API}/rooms/{quote(room_id, safe='')}/state/m.room.encryption",
            headers=self._auth_headers(),
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def turn_server(self) -> dict[str, Any]:
        """Retrieve short-lived TURN credentials advertised by the homeserver."""
        await self._ensure_token()
        resp = await self._http().get(
            f"{MATRIX_API}/voip/turnServer", headers=self._auth_headers()
        )
        if resp.status_code in {404, 501}:
            return {}
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    async def get_room_messages(
        self,
        room_id: str,
        limit: int = 20,
        direction: str = "b",
        from_token: str | None = None,
    ) -> List[dict[str, Any]]:
        """Get room events; ``dir=b`` returns newest first."""
        chunk, _next_cursor = await self.get_room_messages_page(
            room_id,
            limit=limit,
            direction=direction,
            from_token=from_token,
        )
        return chunk

    async def get_room_messages_page(
        self,
        room_id: str,
        *,
        limit: int = 20,
        direction: str = "b",
        from_token: str | None = None,
    ) -> tuple[List[dict[str, Any]], str | None]:
        """Get one room-event page and its opaque Matrix continuation token."""
        await self._ensure_token()
        params: dict[str, str] = {"dir": direction}
        if limit > 0:
            params["limit"] = str(limit)
        if from_token:
            params["from"] = from_token
        url = f"{MATRIX_API}/rooms/{quote(room_id, safe='')}/messages"
        resp = await self._http().get(
            url, headers=self._auth_headers(), params=params
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        chunk: List[dict[str, Any]] = payload.get("chunk", [])
        end = payload.get("end")
        return chunk, str(end) if end else None

    async def direct_rooms(self) -> dict[str, list[str]]:
        """Return the account's ``m.direct`` mapping."""

        await self._ensure_token()
        url = (
            f"{MATRIX_API}/user/{quote(self.user_id, safe='')}"
            f"/account_data/m.direct"
        )
        resp = await self._http().get(url, headers=self._auth_headers())
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return {
            str(user_id): [
                str(room_id)
                for room_id in as_list(room_ids)
                if room_id
            ]
            for user_id, room_ids in as_dict(resp.json()).items()
            if user_id
        }

    async def direct_room_ids(self) -> frozenset[str]:
        return frozenset(
            room_id
            for room_ids in (await self.direct_rooms()).values()
            for room_id in room_ids
        )

    async def direct_room_for(self, user_id: str) -> Optional[str]:
        """Return the existing ``m.direct`` room with ``user_id``."""

        rooms = (await self.direct_rooms()).get(user_id, [])
        return rooms[0] if rooms else None

    async def _remember_direct_room(self, user_id: str, room_id: str) -> None:
        direct = await self.direct_rooms()
        rooms = direct.setdefault(user_id, [])
        if room_id in rooms:
            return
        rooms.append(room_id)
        url = (
            f"{MATRIX_API}/user/{quote(self.user_id, safe='')}"
            f"/account_data/m.direct"
        )
        resp = await self._http().put(
            url,
            headers=self._auth_headers(),
            json=direct,
        )
        resp.raise_for_status()

    async def create_dm(self, user_id: str) -> str:
        """Create a direct room with ``user_id`` and return its room ID."""
        await self._ensure_token()
        payload = {
            "is_direct": True,
            "preset": "trusted_private_chat",
            "invite": [user_id],
        }
        resp = await self._http().post(
            f"{MATRIX_API}/createRoom", headers=self._auth_headers(), json=payload
        )
        resp.raise_for_status()
        room_id = str(as_dict(resp.json()).get("room_id") or "")
        if not room_id:
            raise ValueError("Matrix createRoom response has no room_id")
        try:
            await self._remember_direct_room(user_id, room_id)
        except Exception as exc:
            # The room already exists remotely. Do not turn an account-data
            # bookkeeping failure into a second room on caller retry.
            logger.warning(
                "Matrix direct-room account data update failed type={}",
                type(exc).__name__,
            )
        return room_id

    async def ensure_direct_room(self, user_id: str) -> str:
        """Resolve or create the direct room with ``user_id``."""

        async with self._direct_room_lock:
            room_id = await self.direct_room_for(user_id)
            if room_id:
                return room_id
            return await self.create_dm(user_id)

    async def join_room(self, room_id: str) -> str:
        """Join an invited Matrix room and return its canonical room ID."""

        await self._ensure_token()
        resp = await self._http().post(
            f"{MATRIX_API}/join/{quote(room_id, safe='')}",
            headers=self._auth_headers(),
            json={},
        )
        resp.raise_for_status()
        joined_room_id = str(as_dict(resp.json()).get("room_id") or "")
        if not joined_room_id:
            raise ValueError("Matrix join response has no room_id")
        return joined_room_id

    async def sync(
        self, since: Optional[str] = None, timeout_ms: Optional[int] = None
    ) -> dict[str, Any]:
        """Long-poll ``/sync`` and return events after ``since``."""
        await self._ensure_token()
        effective_timeout = self.sync_timeout_ms if timeout_ms is None else timeout_ms
        params: dict[str, str] = {"timeout": str(effective_timeout)}
        if since:
            params["since"] = since
        resp = await self._http().get(
            f"{MATRIX_API}/sync", headers=self._auth_headers(), params=params
        )
        resp.raise_for_status()
        return resp.json()
