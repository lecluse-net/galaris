"""
AFFiNE blob upload/download client.

AFFiNE authenticates with a session cookie, not a bearer token. The client first
signs in with email and password, then reuses the session for GraphQL/REST calls.

    sign-in  : POST {base_url}/api/auth/sign-in  {email, password} -> session cookie
    upload   : mutation GraphQL ``setBlob(workspaceId, blob: Upload!)`` (multipart)
    download : GET {base_url}/api/workspaces/{workspaceId}/blobs/{key}

The sign-in endpoint may vary between AFFiNE versions; adjust ``_SIGN_IN_PATH``
when necessary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, AsyncGenerator
from urllib.parse import quote

from core.i18n import render_prompt, t
from core.util import DEFAULT_DOWNLOAD_BYTES, as_dict, copy_download

import httpx
from loguru import logger

_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
_SIGN_IN_PATH = "/api/auth/sign-in"
_SESSION_TTL = 600.0
_SESSION_LIMIT = 128


@dataclass(repr=False)
class _SessionState:
    cookies: httpx.Cookies = field(default_factory=httpx.Cookies)
    rate_limit_response: httpx.Response | None = None
    expires_at: float = 0.0
    generation: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Clients are rebuilt by file_share for each operation. Cache bounded cookies and
# body-free rate-limit responses, never open transports or plaintext credentials.
_SESSIONS: OrderedDict[tuple[asyncio.AbstractEventLoop, bytes], _SessionState] = OrderedDict()


def _session_state(base_url: str, email: str, password: str) -> _SessionState:
    loop = asyncio.get_running_loop()
    identity = hashlib.sha256(json.dumps([base_url, email, password]).encode()).digest()
    key = (loop, identity)
    for old_key, state in list(_SESSIONS.items()):
        if not state.lock.locked() and (old_key[0].is_closed() or state.expires_at <= monotonic()):
            del _SESSIONS[old_key]
    if key in _SESSIONS:
        _SESSIONS.move_to_end(key)
        return _SESSIONS[key]
    if len(_SESSIONS) >= _SESSION_LIMIT:
        for old_key, state in _SESSIONS.items():
            if not state.lock.locked():
                del _SESSIONS[old_key]
                break
        else:
            raise httpx.PoolTimeout("AFFiNE authentication sessions are busy; try again later.")
    state = _SessionState()
    _SESSIONS[key] = state
    return state


@dataclass(frozen=True)
class BlobMetadata:
    media_type: str
    size: int | None


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}"), **values)


class AffineFileClient:
    """Session-authenticated blob client for an AFFiNE instance."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password

    def _resolve_workspace(self, workspace: str = "") -> str:
        ws = (workspace or "").strip()
        if not ws:
            raise ValueError(_error("affine_workspace_required"))
        return ws

    def _blob_url(self, remote: str, workspace: str) -> str:
        if remote.startswith(("http://", "https://")):
            return remote
        workspace = self._resolve_workspace(workspace)
        key = remote.lstrip("/")
        # Markdown exports may retain a blob/ prefix alongside the sourceId.
        if key.startswith(("blob/", "blobs/")):
            key = key.split("/", 1)[1]
        if not key or "/" in key or key in {".", ".."}:
            raise ValueError(_error("affine_blob_reference_invalid"))
        return (
            f"{self.base_url}/api/workspaces/{quote(workspace, safe='')}/blobs/"
            f"{quote(key, safe='')}"
        )

    @staticmethod
    def _require_status(resp: httpx.Response, operation: str, accepted: tuple[int, ...] = (200,)) -> None:
        if resp.status_code not in accepted:
            # Retain HTTP status for the common tool diagnostic without exposing the
            # provider's body, which can contain account data or credentials.
            raise httpx.HTTPStatusError(
                f"AFFiNE {operation} failed (HTTP {resp.status_code}).",
                request=resp.request,
                response=resp,
            )

    @staticmethod
    def _check_blob_response(resp: httpx.Response) -> None:
        media_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        # AFFiNE serves its SPA with HTTP 200 for unmatched paths. Actual HTML
        # attachments remain downloadable when explicitly served as attachments.
        disposition = resp.headers.get("content-disposition", "").lower()
        if media_type in {"text/html", "application/xhtml+xml"} and not disposition.startswith("attachment"):
            raise ValueError(_error("affine_blob_html_response"))

    async def blob_metadata(self, remote: str, *, target: str) -> BlobMetadata:
        """Check access and read blob headers without buffering its body."""
        url = self._blob_url(remote, target)
        async with self._session() as http:
            async with http.stream("GET", url) as resp:
                try:
                    self._require_status(resp, "download")
                except httpx.HTTPStatusError as exc:
                    if resp.status_code == 404:
                        raise FileNotFoundError(remote) from exc
                    raise
                self._check_blob_response(resp)
                size = resp.headers.get("content-length", "")
                return BlobMetadata(
                    media_type=resp.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip(),
                    size=int(size) if size.isdecimal() else None,
                )

    @asynccontextmanager
    async def _session(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Reuse a credential-scoped session while owning this call's transport.

        Login is serialized across rebuilt clients. A rejected session is evicted
        for the next explicit call; no read or mutation is automatically replayed.
        """
        state = _session_state(self.base_url, self.email, self.password)
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as http:
            async with state.lock:
                if state.rate_limit_response is not None and state.expires_at > monotonic():
                    self._require_status(state.rate_limit_response, "sign_in", (200, 201, 204))
                if state.cookies and state.expires_at > monotonic():
                    http.cookies.update(state.cookies)
                else:
                    resp = await http.post(
                        f"{self.base_url}{_SIGN_IN_PATH}",
                        json={"email": self.email, "password": self.password},
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code == 429:
                        retry_after = resp.headers.get("retry-after", "")
                        cooldown = (
                            min(int(retry_after), int(_SESSION_TTL))
                            if len(retry_after) <= 9 and retry_after.isdecimal()
                            else 60
                        )
                        state.expires_at = monotonic() + max(1, cooldown)
                        # Do not cache the login request body, response body or headers
                        # that may contain credentials or account data.
                        state.rate_limit_response = httpx.Response(
                            429,
                            headers={"retry-after": str(max(1, cooldown))},
                            request=httpx.Request("POST", f"{self.base_url}{_SIGN_IN_PATH}"),
                        )
                    self._require_status(resp, "sign_in", (200, 201, 204))
                    if not http.cookies:
                        raise RuntimeError(_error("affine_session_cookie_missing"))
                    state.cookies = httpx.Cookies(http.cookies)
                    state.rate_limit_response = None
                    state.expires_at = monotonic() + _SESSION_TTL
                    state.generation += 1
                generation = state.generation
            try:
                yield http
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    async with state.lock:
                        # A late failure from an older operation must not invalidate
                        # a session already renewed by another explicit call.
                        if state.generation == generation:
                            state.cookies.clear()
                            state.expires_at = 0.0
                raise

    async def upload(self, data: bytes, filename: str, target: str = "") -> str:
        """Upload a blob and return its retrieval URL; ``target`` is the workspace."""
        workspace_id = self._resolve_workspace(target)
        query = (
            'mutation setBlob($blob: Upload!) '
            f'{{ setBlob(workspaceId: "{workspace_id}", blob: $blob) }}'
        )
        form = {
            "operations": json.dumps({"query": query, "variables": {"blob": None}}),
            "map": json.dumps({"0": ["variables.blob"]}),
        }
        files = {"0": (filename, data, "application/octet-stream")}

        async with self._session() as http:
            resp = await http.post(f"{self.base_url}/graphql", data=form, files=files)
            self._require_status(resp, "upload", (200, 201))
        body = json.loads(resp.text)
        if body.get("errors"):
            messages = "; ".join(e.get("message", "?") for e in body["errors"])
            raise RuntimeError(_error("affine_graphql_failed", error=messages))
        key = as_dict(body.get("data")).get("setBlob")
        if not key:
            raise RuntimeError(_error("affine_blob_key_missing"))
        logger.info("AFFiNE: uploaded blob {} (workspace {})", key, workspace_id)
        return f"{self.base_url}/api/workspaces/{workspace_id}/blobs/{key}"

    async def download(self, remote: str, workspace: str = "") -> bytes:
        """Download a blob by key or complete URL."""
        url = self._blob_url(remote, workspace)
        async with self._session() as http:
            resp = await http.get(url)
            self._require_status(resp, "download")
        self._check_blob_response(resp)
        return resp.content

    # -- Standard FileTransport interface (streaming with bounded memory) --------

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        """Stream an AFFiNE blob to local ``dest``; ``target`` is the workspace."""
        url = self._blob_url(remote, target)
        total = 0
        async with self._session() as http:
            async with http.stream("GET", url) as resp:
                self._require_status(resp, "download")
                self._check_blob_response(resp)
                total = await copy_download(resp.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)
        return total

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Stream local ``src`` as GraphQL multipart data; ``target`` is the workspace."""
        workspace_id = self._resolve_workspace(target)
        query = (
            'mutation setBlob($blob: Upload!) '
            f'{{ setBlob(workspaceId: "{workspace_id}", blob: $blob) }}'
        )
        form = {
            "operations": json.dumps({"query": query, "variables": {"blob": None}}),
            "map": json.dumps({"0": ["variables.blob"]}),
        }
        with src.open("rb") as fh:
            files = {"0": (filename, fh, "application/octet-stream")}
            async with self._session() as http:
                resp = await http.post(f"{self.base_url}/graphql", data=form, files=files)
                self._require_status(resp, "upload", (200, 201))
        body = json.loads(resp.text)
        if body.get("errors"):
            messages = "; ".join(e.get("message", "?") for e in body["errors"])
            raise RuntimeError(_error("affine_graphql_failed", error=messages))
        key = as_dict(body.get("data")).get("setBlob")
        if not key:
            raise RuntimeError(_error("affine_blob_key_missing"))
        logger.info("AFFiNE: streamed blob {} (workspace {})", key, workspace_id)
        return f"{self.base_url}/api/workspaces/{workspace_id}/blobs/{key}"
