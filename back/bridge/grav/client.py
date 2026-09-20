"""
Grav media upload/download client.

Grav has no universal media API because it depends on installed plugins. This
client targets a simple documented REST convention and sends the API key in
both ``Authorization: Bearer`` and ``X-Api-Key`` headers:

    upload   : POST {base_url}/api/v1/pages/{page}/media  (multipart: file)
    download : GET  {base_url}/{remote}   (public media URL or user/... path)

Configure ``upload_path`` when a Grav installation uses another convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from core.util import DEFAULT_DOWNLOAD_BYTES, copy_download
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from core.util import as_dict, as_list
from core.i18n import render_prompt, t

_DEFAULT_UPLOAD_PATH = "/api/v1/pages/{page}/media"
_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=None, pool=10.0)
_CHUNK = 1 << 20


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"file_share.errors.{key}"), **values)


def _operation_error(operation: str, status: int, detail: Any) -> str:
    return _error(
        "operation_failed",
        service="Grav",
        operation=t(f"file_share.operations.{operation}"),
        status=status,
        detail=detail,
    )


class GravFileClient:
    """Media client for a Grav instance."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        upload_path: str = _DEFAULT_UPLOAD_PATH,
        default_page: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.upload_path = "/" + (upload_path or _DEFAULT_UPLOAD_PATH).strip("/")
        self.default_page = default_page.strip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "X-Api-Key": self.api_key}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    def _upload_url(self, target: str = "") -> tuple[str, bool]:
        """Return the upload URL and whether the URL already includes the page."""
        page = (target or self.default_page).strip("/")
        if "{page}" in self.upload_path:
            if not page:
                raise RuntimeError(_error("grav_target_required"))
            path = self.upload_path.replace("{page}", quote(page, safe="/"))
            return f"{self.base_url}{path}", True
        return f"{self.base_url}{self.upload_path}", False

    def _location_from_response(self, text: str, filename: str, target: str = "") -> str:
        location = ""
        try:
            body = json.loads(text)
            if isinstance(body, dict):
                body_d = as_dict(body)
                data = body_d.get("data")
                if isinstance(data, list):
                    match = next(
                        (
                            as_dict(item) for item in as_list(data)
                            if isinstance(item, dict) and as_dict(item).get("filename") == filename
                        ),
                        None,
                    )
                    if match is None:
                        match = next((as_dict(item) for item in as_list(data) if isinstance(item, dict)), None)
                    if match is not None:
                        location = str(match.get("url") or match.get("path") or "")
                location = location or str(body_d.get("url") or body_d.get("path") or "")
        except (json.JSONDecodeError, AttributeError):
            pass
        if not location:
            prefix = f"{target.strip('/')}/" if target else ""
            location = f"{self.base_url}/{prefix}{filename}"
        if location.startswith("/"):
            location = f"{self.base_url}{location}"
        return location

    async def upload(self, data: bytes, filename: str, target: str = "") -> str:
        """Upload media, targeting a Grav page when ``target`` is provided.

        Return the media URL from the response or reconstruct it when absent.
        """
        files = {"file": (filename, data, "application/octet-stream")}
        form: dict[str, str] = {}
        url, page_in_url = self._upload_url(target)
        if target and not page_in_url:
            form["page"] = target

        async with self._client() as http:
            resp = await http.post(
                url,
                headers=self._headers(),
                data=form,
                files=files,
            )
        if resp.status_code not in (200, 201):
            raise RuntimeError(_operation_error(
                "upload", resp.status_code, f"{url}: {resp.text[:200]}"
            ))

        location = self._location_from_response(resp.text, filename, target)
        logger.info("Grav: uploaded media to {}", location)
        return location

    async def download(self, remote: str) -> bytes:
        """Download media from a relative path or complete URL."""
        url = remote if remote.startswith(("http://", "https://")) else f"{self.base_url}/{remote.lstrip('/')}"
        async with self._client() as http:
            resp = await http.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(_operation_error(
                "download", resp.status_code, resp.text[:200]
            ))
        return resp.content

    # -- Standard FileTransport interface (streaming with bounded memory) --------

    async def download_to(self, remote: str, dest: Path, *, target: str = "", max_bytes: int = DEFAULT_DOWNLOAD_BYTES) -> int:
        """Stream Grav media to local ``dest``; ``target`` is ignored."""
        url = remote if remote.startswith(("http://", "https://")) else f"{self.base_url}/{remote.lstrip('/')}"
        total = 0
        async with self._client() as http:
            async with http.stream("GET", url, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:200]
                    raise RuntimeError(_operation_error(
                        "download", resp.status_code, repr(body)
                    ))
                total = await copy_download(resp.aiter_bytes(min(64 * 1024, max_bytes + 1)), dest, max_bytes=max_bytes)
        return total

    async def upload_from(self, src: Path, filename: str, *, target: str = "") -> str:
        """Stream local ``src`` as multipart data; ``target`` is the Grav page."""
        form: dict[str, str] = {}
        url, page_in_url = self._upload_url(target)
        if target and not page_in_url:
            form["page"] = target
        with src.open("rb") as fh:
            files = {"file": (filename, fh, "application/octet-stream")}
            async with self._client() as http:
                resp = await http.post(
                    url,
                    headers=self._headers(),
                    data=form,
                    files=files,
                )
        if resp.status_code not in (200, 201):
            raise RuntimeError(_operation_error(
                "upload", resp.status_code, f"{url}: {resp.text[:200]}"
            ))
        location = self._location_from_response(resp.text, filename, target)
        logger.info("Grav: streamed media to {}", location)
        return location
