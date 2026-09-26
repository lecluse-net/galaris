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

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download
from typing import Any, AsyncGenerator
from urllib.parse import quote

from core.i18n import render_prompt, t
from core.util import as_dict

import httpx
from loguru import logger

_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=None, pool=10.0)
_SIGN_IN_PATH = "/api/auth/sign-in"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class BlobMetadata:
    media_type: str
    size: int | None


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}"), **values)


def _operation_error(operation: str, status: int, detail: Any) -> str:
    return _error(
        "operation_failed",
        service="AFFiNE",
        operation=t(f"file_share.operations.{operation}"),
        status=status,
        detail=detail,
    )


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
                if resp.status_code == 404:
                    raise FileNotFoundError(remote)
                if resp.status_code != 200:
                    raise RuntimeError(_operation_error("download", resp.status_code, resp.reason_phrase))
                self._check_blob_response(resp)
                size = resp.headers.get("content-length", "")
                return BlobMetadata(
                    media_type=resp.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip(),
                    size=int(size) if size.isdecimal() else None,
                )

    @asynccontextmanager
    async def _session(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Open an authenticated httpx client with an AFFiNE session cookie."""
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as http:
            resp = await http.post(
                f"{self.base_url}{_SIGN_IN_PATH}",
                json={"email": self.email, "password": self.password},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(_operation_error(
                    "sign_in", resp.status_code, resp.text[:200]
                ))
            if not http.cookies:
                raise RuntimeError(_error("affine_session_cookie_missing"))
            yield http

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
        if resp.status_code not in (200, 201):
            raise RuntimeError(_operation_error(
                "upload", resp.status_code, resp.text[:200]
            ))
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
        if resp.status_code != 200:
            raise RuntimeError(_operation_error(
                "download", resp.status_code, resp.text[:200]
            ))
        self._check_blob_response(resp)
        return resp.content

    # -- Standard FileTransport interface (streaming with bounded memory) --------

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        """Stream an AFFiNE blob to local ``dest``; ``target`` is the workspace."""
        url = self._blob_url(remote, target)
        total = 0
        async with self._session() as http:
            async with http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:200]
                    raise RuntimeError(_operation_error(
                        "download", resp.status_code, repr(body)
                    ))
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
        if resp.status_code not in (200, 201):
            raise RuntimeError(_operation_error(
                "upload", resp.status_code, resp.text[:200]
            ))
        body = json.loads(resp.text)
        if body.get("errors"):
            messages = "; ".join(e.get("message", "?") for e in body["errors"])
            raise RuntimeError(_error("affine_graphql_failed", error=messages))
        key = as_dict(body.get("data")).get("setBlob")
        if not key:
            raise RuntimeError(_error("affine_blob_key_missing"))
        logger.info("AFFiNE: streamed blob {} (workspace {})", key, workspace_id)
        return f"{self.base_url}/api/workspaces/{workspace_id}/blobs/{key}"
