"""
Low-level HTTP client for the Nextcloud Talk OCS spreed API.

Ported from ``refs/mcp-next-talk-bridge/src/talk/service.py`` and rewritten with
``httpx`` consistently with ``bridge/matrix/client.py``. Authentication uses a
Nextcloud login and password over Basic Auth. All OCS responses are unwrapped
from ``ocs.data``.

This client knows only the Nextcloud wire format (raw dictionaries).
``NextcloudTalkMessenger`` converts it to canonical messages.
"""

from __future__ import annotations

import asyncio
import html
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import httpx
from loguru import logger

from core.util import as_dict, as_list
from core.i18n import render_prompt, t
from app.messenger.interface import DeliveryOutcomeUnknown


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)

# OCS prefixes for the ``spreed`` (Talk) application.
_SPREED_V1 = "/ocs/v2.php/apps/spreed/api/v1"
_SPREED_V3 = "/ocs/v2.php/apps/spreed/api/v3"
_SPREED_V4 = "/ocs/v2.php/apps/spreed/api/v4"
_SPREED_CALL_APIS = (_SPREED_V4, _SPREED_V3, _SPREED_V1)
_SHARES = "/ocs/v2.php/apps/files_sharing/api/v1"

_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY = 2.0

# A long read timeout accommodates ``get_messages(look_into_future=1)`` long polling.
_TIMEOUT = httpx.Timeout(connect=10.0, read=70.0, write=30.0, pool=10.0)


def _http_error_summary(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    body = response.text.strip().replace("\n", " ")
    if len(body) > 300:
        body = body[:300] + "..."
    return f"status={response.status_code} url={response.request.url} body={body}"


class NextcloudTalkClient:
    """Low-level OCS client for a Nextcloud account."""

    def __init__(
        self,
        base_url: str,
        login: str,
        password: str,
        rate_limit: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.login = login
        self.password = password
        self._rate_limit = rate_limit
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._web_client: Optional[httpx.AsyncClient] = None
        self._web_login_lock = asyncio.Lock()
        self._web_login_attempted = False
        self._web_login_succeeded = False
        self._call_api_web_fallback_warned = False

    # -- HTTP plumbing --

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=(self.login, self.password),
                headers={"OCS-APIRequest": "true", "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._web_client is not None:
            await self._web_client.aclose()
            self._web_client = None
        self._web_login_attempted = False
        self._web_login_succeeded = False

    async def _throttle(self) -> None:
        if self._rate_limit <= 0:
            return
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request
            if elapsed < self._rate_limit:
                await asyncio.sleep(self._rate_limit - elapsed)
            self._last_request = asyncio.get_event_loop().time()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        timeout: Optional[float] = None,
        response_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute an OCS request and unwrap ``ocs.data``.

        Retry only idempotent GET/HEAD methods. Retrying a POST/PUT/
        DELETE is unsafe: Nextcloud Talk sometimes returns 500 (OCS 996) even
        though the mutation succeeded (for example, a posted message). Retrying would
        duplicate the action and previously caused triple replies.
        """
        idempotent = method.upper() in ("GET", "HEAD")
        retry_delay = _INITIAL_RETRY_DELAY
        req_timeout = httpx.Timeout(timeout) if timeout is not None else _TIMEOUT
        for attempt in range(_MAX_RETRIES + 1):
            await self._throttle()
            try:
                resp = await self._http().request(
                    method, endpoint, timeout=req_timeout, **kwargs
                )
            except httpx.TransportError as exc:
                if idempotent and attempt < _MAX_RETRIES:
                    logger.warning("Talk {} {}: {}; retrying in {}s", method, endpoint, exc, retry_delay)
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                    continue
                raise
            if idempotent and resp.status_code in _RETRYABLE and attempt < _MAX_RETRIES:
                retry_after = float(resp.headers.get("Retry-After", retry_delay))
                logger.warning("Talk HTTP {} at {}; retrying in {}s", resp.status_code, endpoint, retry_after)
                await asyncio.sleep(retry_after)
                retry_delay = min(retry_delay * 2, 60)
                continue
            if response_headers is not None:
                response_headers.update(resp.headers)
            if resp.status_code == 304:
                return []
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data_d = as_dict(data)
                if "ocs" in data_d:
                    ocs = as_dict(data_d["ocs"])
                    return ocs.get("data", data_d)
                return data_d
            return data
        return None

    def _web_http(self) -> httpx.AsyncClient:
        if self._web_client is None:
            self._web_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"OCS-APIRequest": "true", "Accept": "application/json"},
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
        return self._web_client

    async def _ensure_web_session(self) -> bool:
        if self._web_login_succeeded:
            return True
        # Several monitored Talk rooms initialize their HPB connections in
        # parallel. They must all wait for the same login instead of observing
        # ``_web_login_attempted`` mid-flight and falling back to Basic Auth.
        async with self._web_login_lock:
            if self._web_login_succeeded:
                return True
            if self._web_login_attempted:
                return False
            self._web_login_attempted = True
            client = self._web_http()
            page = await client.get("/login")
            token_match = re.search(r'name="requesttoken" value="([^"]+)"', page.text)
            if token_match is None:
                token_match = re.search(r'data-requesttoken="([^"]+)"', page.text)
            if token_match is None:
                logger.warning("Talk web session: request token not found")
                return False
            token = html.unescape(token_match.group(1))
            parsed_base_url = urlsplit(self.base_url)
            origin = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}"
            resp = await client.post(
                "/login",
                data={"user": self.login, "password": self.password, "requesttoken": token},
                headers={
                    "requesttoken": token,
                    # Nextcloud 34 rejects login POSTs without a same-origin Origin
                    # header before it even checks the supplied credentials.
                    "Origin": origin,
                    "Referer": f"{self.base_url}/login",
                },
            )
            location = resp.headers.get("location", "")
            if resp.status_code in (302, 303) and not location.startswith("/login"):
                self._web_login_succeeded = True
                logger.info("Talk web session: login web OK")
                return True
            logger.warning(
                "Talk web session: web login rejected (status={}, location={})",
                resp.status_code,
                location,
            )
            return False

    async def _web_request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        if not await self._ensure_web_session():
            raise RuntimeError(_error("web_session_unavailable"))
        resp = await self._web_http().request(method, endpoint, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data_d = as_dict(data)
            if "ocs" in data_d:
                ocs = as_dict(data_d["ocs"])
                meta = as_dict(ocs.get("meta"))
                if int(meta.get("statuscode") or resp.status_code) >= 400:
                    raise httpx.HTTPStatusError(
                        f"OCS failure {meta.get('statuscode')}: {meta.get('message', '')}",
                        request=resp.request,
                        response=resp,
                    )
                return ocs.get("data", data_d)
            return data_d
        return data

    async def _request_with_web_fallback(
        self,
        method: str,
        endpoint: str,
        *,
        web_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return await self._request(method, endpoint, **kwargs)
        except Exception:
            logger.opt(exception=True).debug("Talk: OCS request failed, trying a web session")
            return await self._web_request(method, endpoint, **(web_kwargs or kwargs))

    async def _request_prefer_web_session(
        self,
        method: str,
        endpoint: str,
        *,
        web_kwargs: Optional[Dict[str, Any]] = None,
        fallback_reason: str = "",
        **kwargs: Any,
    ) -> Any:
        """Execute a Talk request, preferring a real web session.

        HPB signaling validates the ``sessionId`` returned by some Talk routes.
        On some instances, app-password Basic Auth is sufficient for chat but is
        later rejected by the HPB. A configured web session must therefore be
        used from ``participants/active`` onward.
        """
        try:
            return await self._web_request(method, endpoint, **(web_kwargs or kwargs))
        except RuntimeError as exc:
            logger.warning(
                "Talk web session unavailable for {} ({}); trying Basic Auth{}",
                endpoint,
                exc,
                f" — {fallback_reason}" if fallback_reason else "",
            )
        except httpx.HTTPStatusError:
            logger.opt(exception=True).debug(
                "Talk web session rejected for {}; trying Basic Auth{}",
                endpoint,
                f" — {fallback_reason}" if fallback_reason else "",
            )
        return await self._request(method, endpoint, **kwargs)

    async def _request_call_api(
        self,
        method: str,
        token: str,
        *,
        suffix: str = "",
        **kwargs: Any,
    ) -> Any:
        web_kwargs = kwargs.pop("web_kwargs", None)
        method_upper = method.upper()
        suffix_path = f"/{suffix.lstrip('/')}" if suffix else ""
        endpoints = [f"{api}/call/{token}{suffix_path}" for api in _SPREED_CALL_APIS]
        for index, endpoint in enumerate(endpoints):
            try:
                try:
                    return await self._web_request(method, endpoint, **(web_kwargs or kwargs))
                except RuntimeError as exc:
                    if not self._call_api_web_fallback_warned:
                        logger.warning(
                            "Talk Call API: web session unavailable for {} ({}); "
                            "using Basic Auth for this client",
                            endpoint,
                            exc,
                        )
                        self._call_api_web_fallback_warned = True
                return await self._request(method, endpoint, **kwargs)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404 and index < len(endpoints) - 1:
                    log = logger.debug if method_upper == "GET" else logger.info
                    log(
                        "Talk Call API {} unavailable ({}), trying {}",
                        endpoint,
                        _http_error_summary(exc),
                        endpoints[index + 1],
                    )
                    continue
                raise
        raise RuntimeError(_error("call_api_unavailable", room_id=token))

    # ── Rooms ──────────────────────────────────────────────────────────────

    async def get_rooms(self) -> List[Dict[str, Any]]:
        data = await self._request("GET", f"{_SPREED_V4}/room")
        return as_list(data)

    async def get_messages(
        self,
        token: str,
        *,
        look_into_future: int = 0,
        limit: int = 100,
        last_known_message_id: int = 0,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """Get room messages; ``look_into_future=1`` enables long polling."""
        messages, _next_cursor = await self.get_messages_page(
            token,
            look_into_future=look_into_future,
            limit=limit,
            last_known_message_id=last_known_message_id,
            timeout=timeout,
        )
        return messages

    async def get_messages_page(
        self,
        token: str,
        *,
        look_into_future: int = 0,
        limit: int = 100,
        last_known_message_id: int = 0,
        timeout: int = 30,
    ) -> tuple[List[Dict[str, Any]], str | None]:
        """Get one Talk chat page and preserve its server-provided continuation cursor."""
        safe_limit = max(1, min(limit, 200))
        params: Dict[str, Any] = {
            "lookIntoFuture": look_into_future,
            "limit": safe_limit,
            "timeout": timeout,
        }
        if last_known_message_id > 0:
            params["lastKnownMessageId"] = last_known_message_id
        read_timeout = float(timeout + 10) if look_into_future == 1 else None
        response_headers: dict[str, str] = {}
        try:
            res = await self._request(
                "GET",
                f"{_SPREED_V1}/chat/{token}",
                params=params,
                timeout=read_timeout,
                response_headers=response_headers,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return [], None
            raise
        cursor = response_headers.get("x-chat-last-given")
        return as_list(res), cursor or None

    async def send_message(self, token: str, message: str, reply_to: int = 0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"message": message}
        if reply_to > 0:
            payload["replyTo"] = reply_to
        try:
            res = await self._request("POST", f"{_SPREED_V1}/chat/{token}", json=payload)
        except httpx.HTTPStatusError as exc:
            # Talk may fail before or after accepting the message. Neither
            # outcome is proven by a 5xx; retain uncertainty without resending.
            if exc.response.status_code >= 500:
                raise DeliveryOutcomeUnknown(
                    "Talk send returned a server error; delivery is uncertain"
                ) from exc
            raise
        except httpx.TransportError as exc:
            raise DeliveryOutcomeUnknown(
                "Talk send response was lost; delivery is uncertain"
            ) from exc
        return as_dict(res)

    async def create_conversation(
        self, invitees: List[str], room_type: int = 1, room_name: str = ""
    ) -> Dict[str, Any]:
        """Create a room; ``room_type`` 1 is direct and 2 is a group."""
        payload: Dict[str, Any] = {"roomType": room_type}
        if room_type == 1 and invitees:
            payload["invite"] = invitees[0]
        elif invitees:
            payload["invitees"] = invitees
        if room_name:
            payload["roomName"] = room_name
        res = await self._request("POST", f"{_SPREED_V4}/room", json=payload)
        return as_dict(res)

    async def get_room_participants(self, token: str) -> List[Dict[str, Any]]:
        res = await self._request("GET", f"{_SPREED_V4}/room/{token}/participants")
        return as_list(res)

    async def add_participant(self, token: str, user_id: str) -> Dict[str, Any]:
        res = await self._request(
            "POST",
            f"{_SPREED_V4}/room/{token}/participants",
            json={"newParticipant": user_id, "source": "users"},
        )
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    async def remove_participant(self, token: str, user_id: str) -> Dict[str, Any]:
        attendee_id: Optional[int] = None
        for p in await self.get_room_participants(token):
            if p.get("actorId") == user_id or p.get("userId") == user_id:
                attendee_id = p.get("attendeeId")
                break
        if attendee_id is None:
            raise ValueError(_error(
                "user_not_in_room", user_id=user_id, room_id=token
            ))
        res = await self._request(
            "DELETE", f"{_SPREED_V4}/room/{token}/attendees", params={"attendeeId": attendee_id}
        )
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    async def set_room_name(self, token: str, room_name: str) -> Dict[str, Any]:
        res = await self._request("PUT", f"{_SPREED_V4}/room/{token}", json={"roomName": room_name})
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    async def mark_room_as_read(self, token: str, last_read_message: int = 0) -> Dict[str, Any]:
        payload: Optional[Dict[str, Any]] = {"lastReadMessage": last_read_message} if last_read_message > 0 else None
        res = await self._request("POST", f"{_SPREED_V1}/chat/{token}/read", json=payload)
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    # -- Signaling / HPB real-time reception ----------------------------------

    async def join_call(self, token: str) -> Dict[str, Any]:
        """Join a room through ``participants/active`` and return a ``sessionId``.

        The returned ``sessionId`` later authenticates the WebSocket with the HPB.
        See ``signaling.py``.
        """
        res = await self._request_prefer_web_session(
            "POST",
            f"{_SPREED_V4}/room/{token}/participants/active",
            json={},
            web_kwargs={"data": {}},
            fallback_reason=(
                "the returned sessionId will be validated by the HPB"
            ),
        )
        return as_dict(res)

    async def join_media_call(
        self,
        token: str,
        *,
        flags: int = 3,
        silent: bool = True,
        recording_consent: bool = False,
    ) -> Any:
        """Mark the user as a visible participant in the Talk call.

        ``flags=3`` combines in-call (1) and audio (2). Call ``join_call`` or
        ``participants/active`` first to create the active Talk session.
        """
        payload = {
            "flags": flags,
            "silent": silent,
            "recordingConsent": recording_consent,
        }
        return await self._request_call_api(
            "POST", token, data=payload
        )

    async def update_media_call_flags(self, token: str, *, flags: int) -> Any:
        """Advertise the media that is actually ready on the current session."""
        payload = {"flags": flags}
        return await self._request_call_api(
            "PUT", token, data=payload
        )

    async def leave_media_call(
        self,
        token: str,
        *,
        all_participants: bool = False,
    ) -> Any:
        """Leave this participant or terminate the Talk call for everyone."""
        return await self._request_call_api(
            "DELETE", token, params={"all": all_participants}
        )

    async def get_call_participants(self, token: str) -> List[Dict[str, Any]]:
        """List participants connected to the call."""
        res = await self._request_call_api("GET", token)
        return as_list(res)

    async def ring_call_participant(self, token: str, attendee_id: int) -> Any:
        """Trigger a call notification for a room participant."""
        return await self._request_call_api(
            "POST", token, suffix=f"ring/{attendee_id}", json={}, web_kwargs={"data": {}}
        )

    async def get_signaling_settings(self, token: str = "") -> Dict[str, Any]:
        """Get signaling settings, including the external HPB URL when configured.

        Return the raw OCS v3 dictionary with ``server`` (HPB URL),
        ``helloAuthParams`` tickets/JWT, and STUN/TURN data. ``token`` identifies the room.
        """
        try:
            kwargs: Dict[str, Any] = {"params": {"token": token}} if token else {}
            res = await self._request_prefer_web_session(
                "GET",
                f"{_SPREED_V3}/signaling/settings",
                fallback_reason="helloAuthParams tickets must match the Talk session",
                **kwargs,
            )
        except httpx.HTTPStatusError:
            return {}
        return as_dict(res)

    # -- Users -----------------------------------------------------------------

    async def list_users(self, search: str = "") -> List[Dict[str, Any]]:
        """Search users through the sharees endpoint and return id/displayName rows."""
        res = await self._request(
            "GET", f"{_SHARES}/sharees", params={"search": search, "itemType": "file", "format": "json"}
        )
        raw: List[Dict[str, Any]] = []
        if isinstance(res, dict):
            res_d = as_dict(res)
            raw.extend(as_list(as_dict(res_d.get("exact")).get("users")))
            raw.extend(as_list(res_d.get("users")))
        return [
            {"id": as_dict(u.get("value")).get("shareWith", ""), "displayName": u.get("label", "")}
            for u in raw
        ]

    # -- Reactions -------------------------------------------------------------

    async def add_reaction(self, token: str, message_id: int, reaction: str) -> Dict[str, Any]:
        res = await self._request(
            "POST", f"{_SPREED_V1}/reaction/{token}/{message_id}", json={"reaction": reaction}
        )
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    async def remove_reaction(self, token: str, message_id: int, reaction: str) -> Dict[str, Any]:
        try:
            res = await self._request(
                "DELETE", f"{_SPREED_V1}/reaction/{token}/{message_id}", params={"reaction": reaction}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {"success": False, "error": "reaction_not_found"}
            raise
        return as_dict(res) if isinstance(res, dict) else {"success": True}

    # -- Files -----------------------------------------------------------------

    async def share_file_to_room(
        self, token: str, file_path: str, *, voice_message: bool = False
    ) -> Dict[str, Any]:
        """Share a file from the user's Nextcloud storage into a Talk room.

        ``voice_message=True`` adds Talk's ``messageType=voice-message`` metadata so the
        audio file appears with the inline player instead of as a downloadable attachment.
        """
        body: Dict[str, Any] = {"shareType": 10, "shareWith": token, "path": file_path}
        if voice_message:
            body["talkMetaData"] = '{"messageType":"voice-message"}'
        res = await self._request("POST", f"{_SHARES}/shares", json=body)
        return as_dict(res)

    async def download_dav(self, path: str) -> bytes:
        """Download a file on demand from the user's storage over WebDAV."""
        await self._throttle()
        url = f"/remote.php/dav/files/{self.login}/{path.lstrip('/')}"
        resp = await self._http().get(url)
        resp.raise_for_status()
        return resp.content

    async def download_by_id(
        self,
        file_id: str,
        *,
        fallback_path: str = "",
        search_dir: str = "Talk",
    ) -> bytes:
        """Download a room file through its stable Nextcloud ``fileId``.

        The ``path`` returned in Talk ``messageParameters`` is relative to the
        user who received the message: signaling computes it for the sender
        (for example ``img1.jpg``), while the bot may see
        ``Talk/img1.jpg``. Downloads use the bot's storage, so resolve the actual
        path from ``fileId``. Files shared into a room arrive in the bot's
        ``Talk/`` directory; ``fallback_path`` remains a fallback.
        """
        href = await self._resolve_dav_href_by_id(file_id, search_dir) if file_id else None
        if href:
            await self._throttle()
            resp = await self._http().get(href)
            resp.raise_for_status()
            return resp.content
        if fallback_path:
            return await self.download_dav(fallback_path)
        raise FileNotFoundError(
            f"Nextcloud file not found (fileId={file_id!r}, directory={search_dir!r})"
        )

    async def _stream_get_to_file(self, url: str, dest: Path, *, max_bytes: int = 512 * 1024 * 1024) -> int:
        """Stream a GET response to local ``dest`` and return bytes written."""
        await self._throttle()
        from core.util import copy_download
        async with self._http().stream("GET", url) as resp:
            resp.raise_for_status()
            return await copy_download(resp.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)

    async def download_by_id_to_file(
        self,
        file_id: str,
        dest: Path,
        *,
        fallback_path: str = "",
        search_dir: str = "Talk",
        max_bytes: int = 512 * 1024 * 1024,
    ) -> int:
        """Like ``download_by_id``, but stream the file into ``dest``.

        Memory stays bounded regardless of size, including large videos received
        in conversations. Return the number of bytes written.
        """
        href = await self._resolve_dav_href_by_id(file_id, search_dir) if file_id else None
        if href:
            return await self._stream_get_to_file(href, dest, max_bytes=max_bytes)
        if fallback_path:
            url = f"/remote.php/dav/files/{self.login}/{fallback_path.lstrip('/')}"
            return await self._stream_get_to_file(url, dest, max_bytes=max_bytes)
        raise FileNotFoundError(
            f"Nextcloud file not found (fileId={file_id!r}, directory={search_dir!r})"
        )

    async def _resolve_dav_href_by_id(
        self, file_id: str, search_dir: str = "Talk"
    ) -> Optional[str]:
        """Return a file's DAV href in the bot's storage from its ``fileId``.

        Run PROPFIND with ``Depth: 1`` on the bot's ``search_dir`` and match
        ``oc:fileid``. Return ``None`` when the directory or file is absent.
        """
        await self._throttle()
        folder = search_dir.strip("/")
        url = (
            f"/remote.php/dav/files/{self.login}/{folder}/"
            if folder
            else f"/remote.php/dav/files/{self.login}/"
        )
        body = (
            '<?xml version="1.0"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:prop><oc:fileid/></d:prop></d:propfind>"
        )
        resp = await self._http().request(
            "PROPFIND", url, headers={"Depth": "1"}, content=body
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return None
        dav, oc = "{DAV:}", "{http://owncloud.org/ns}"
        for response in root.findall(f"{dav}response"):
            href_el = response.find(f"{dav}href")
            fid_el = response.find(f".//{oc}fileid")
            if (
                href_el is not None
                and href_el.text
                and fid_el is not None
                and (fid_el.text or "").strip() == str(file_id)
            ):
                return href_el.text
        return None

    async def ensure_folder(self, folder: str) -> None:
        """Idempotently create a WebDAV directory in the user's storage."""
        await self._throttle()
        url = f"/remote.php/dav/files/{self.login}/{folder.strip('/')}"
        resp = await self._http().request("MKCOL", url)
        if resp.status_code not in (200, 201, 405):  # 405 means the directory already exists.
            resp.raise_for_status()

    async def upload_dav(
        self, path: str, data: bytes, content_type: Optional[str] = None
    ) -> None:
        """Upload bytes into the user's storage with a WebDAV PUT."""
        await self._throttle()
        url = f"/remote.php/dav/files/{self.login}/{path.lstrip('/')}"
        headers = {"Content-Type": content_type} if content_type else {}
        resp = await self._http().put(url, content=data, headers=headers)
        resp.raise_for_status()

    async def upload_dav_file(
        self, path: str, local_path: Path, content_type: Optional[str] = None
    ) -> None:
        """Stream a local file from disk into WebDAV with PUT.

        Read chunks with a declared Content-Length to avoid chunked transfer;
        memory remains bounded for arbitrarily large files such as videos.
        """
        await self._throttle()
        url = f"/remote.php/dav/files/{self.login}/{path.lstrip('/')}"
        headers = {"Content-Length": str(local_path.stat().st_size)}
        if content_type:
            headers["Content-Type"] = content_type

        # httpx async requires an async iterator; offload disk reads to a thread
        # so large files do not block the event loop.
        async def _aiter_file():
            with local_path.open("rb") as f:
                while True:
                    chunk = await asyncio.to_thread(f.read, 1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        resp = await self._http().put(url, content=_aiter_file(), headers=headers)
        resp.raise_for_status()

    async def verify_connection(self) -> Dict[str, Any]:
        """Verify credentials through the Provisioning API and return user data."""
        res = await self._request("GET", f"/ocs/v1.php/cloud/users/{self.login}")
        if isinstance(res, list) and res:
            first = as_list(res)[0]
            return as_dict(first) if isinstance(first, dict) else {"id": self.login}
        return as_dict(res) if isinstance(res, dict) else {"id": self.login}
