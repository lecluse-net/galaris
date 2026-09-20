"""Authenticated client for the generic host-side harness manager."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from core.i18n import render_prompt, t, tr
from core.params import runtime_settings as settings
from core.util import as_dict, as_list


class HarnessManagerError(RuntimeError):
    """Raised when the generic harness manager contract cannot be fulfilled."""


def _message(key: str, **values: Any) -> str:
    return render_prompt(t(f"harness.errors.{key}"), **values)


class HarnessManager:
    """Manage generic Compose instances and their file trees."""

    _ACTION_TIMEOUTS: dict[str, float] = {
        # The host manager allows 20 minutes for build-capable actions. Keep a
        # small HTTP transport margin so its structured 504 remains observable.
        "start": 1230.0,
        "stop": 60.0,
        "restart": 1230.0,
        "update": 1230.0,
    }
    _STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
    _STREAM_CHUNK = 256 * 1024

    def __init__(self) -> None:
        self._fernet: Fernet | None = None
        self._fernet_secret: str | None = None
        self._instance_locks: dict[str, asyncio.Lock] = {}

    @property
    def configured(self) -> bool:
        return bool(settings.HARNESS_MANAGER_SECRET.strip())

    def instance_lock(self, instance_id: str) -> asyncio.Lock:
        """Serialize lifecycle and file mutations for one instance."""
        return self._instance_locks.setdefault(instance_id, asyncio.Lock())

    def _get_fernet(self) -> Fernet:
        secret = settings.HARNESS_MANAGER_SECRET.strip()
        if not secret:
            raise HarnessManagerError(_message("secret_missing"))
        if self._fernet is not None and self._fernet_secret == secret:
            return self._fernet
        normalized = secret.rstrip("=") + "=" * (-len(secret.rstrip("=")) % 4)
        try:
            self._fernet = Fernet(normalized.encode())
        except ValueError as exc:
            raise HarnessManagerError(_message("secret_invalid", error=exc)) from exc
        self._fernet_secret = secret
        return self._fernet

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Harness-Token": self._get_fernet().encrypt(b"auth").decode()}

    def _base_url(self) -> str:
        url = settings.HARNESS_MANAGER_URL.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return url

    @property
    def base_url(self) -> str:
        """Configured transport URL; callers must sanitize it before displaying it."""
        return self._base_url()

    async def get_contract(self) -> dict[str, Any]:
        """Read the authenticated manager contract with a bounded timeout."""
        response = await self._request("GET", "/", timeout=8.0)
        return as_dict(response.json())

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
        params: dict[str, int] | None = None,
        timeout: float = 30.0,
        acceptable_statuses: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    f"{self._base_url()}{path}",
                    headers=headers,
                    json=json,
                    content=content,
                    params=params,
                )
                if response.status_code not in acceptable_statuses:
                    response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Harness manager {} {} returned {}",
                method,
                path,
                exc.response.status_code,
            )
            raise HarnessManagerError(
                render_prompt(
                    await tr("harness.errors.http_error"),
                    status=exc.response.status_code,
                    method=method,
                    path=path,
                )
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Harness manager is unreachable: {}", exc)
            raise HarnessManagerError(await tr("harness.errors.unreachable")) from exc

    async def get_instance_status(self, instance_id: str) -> str:
        response = await self._request(
            "GET",
            f"/instances/{instance_id}/status",
            timeout=15.0,
        )
        data = cast(dict[str, str], response.json())
        return data.get("status", "unknown")

    async def create_instance(self, name: str, template: str | None = None) -> None:
        await self._request(
            "POST",
            "/instances",
            json={"name": name, "template": template},
        )

    async def delete_instance(self, instance_id: str) -> None:
        response = await self._request(
            "DELETE",
            f"/instances/{instance_id}",
            acceptable_statuses=frozenset({404}),
        )
        if response.status_code == 404:
            logger.info("Harness instance already absent: instance={}", instance_id)

    async def run_action(self, instance_id: str, action: str) -> str:
        response = await self._request(
            "POST",
            f"/instances/{instance_id}/actions/{action}",
            timeout=self._ACTION_TIMEOUTS.get(action, 90.0),
        )
        data = cast(dict[str, str], response.json())
        output = data.get("output", "")
        logger.info("Harness action {} — instance={}, output={}", action, instance_id, output[:120])
        return output

    async def read_text_file(self, instance_id: str, filepath: str) -> str:
        response = await self._request("GET", f"/instances/{instance_id}/files/{filepath}")
        try:
            return self._get_fernet().decrypt(response.text.encode()).decode()
        except InvalidToken as exc:
            raise HarnessManagerError(
                render_prompt(
                    await tr("harness.errors.decrypt_failed"),
                    filepath=filepath,
                    instance_id=instance_id,
                )
            ) from exc

    async def write_text_file(
        self,
        instance_id: str,
        filepath: str,
        content: str,
        *,
        mode: int = 0o644,
    ) -> None:
        encrypted = self._get_fernet().encrypt(content.encode()).decode()
        await self._request(
            "PUT",
            f"/instances/{instance_id}/files/{filepath}",
            content=encrypted.encode(),
            extra_headers={"Content-Type": "text/plain"},
            params={"mode": mode},
        )

    async def download_file_to(self, instance_id: str, filepath: str, dest: Path) -> int:
        total = 0
        try:
            async with httpx.AsyncClient(timeout=self._STREAM_TIMEOUT) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url()}/instances/{instance_id}/raw/{filepath}",
                    headers=self._auth_headers(),
                ) as response:
                    response.raise_for_status()
                    with dest.open("wb") as output:
                        async for chunk in response.aiter_bytes(self._STREAM_CHUNK):
                            output.write(chunk)
                            total += len(chunk)
        except httpx.HTTPStatusError as exc:
            raise HarnessManagerError(
                render_prompt(
                    await tr("harness.errors.http_error"),
                    status=exc.response.status_code,
                    method="GET",
                    path=f"/instances/{instance_id}/raw/{filepath}",
                )
            ) from exc
        except httpx.RequestError as exc:
            raise HarnessManagerError(await tr("harness.errors.unreachable")) from exc
        return total

    async def upload_file_from(self, instance_id: str, filepath: str, src: Path) -> int:
        size = src.stat().st_size

        async def iter_file() -> AsyncIterator[bytes]:
            with src.open("rb") as source:
                while chunk := await asyncio.to_thread(source.read, self._STREAM_CHUNK):
                    yield chunk

        headers = self._auth_headers()
        headers["Content-Length"] = str(size)
        try:
            async with httpx.AsyncClient(timeout=self._STREAM_TIMEOUT) as client:
                response = await client.put(
                    f"{self._base_url()}/instances/{instance_id}/raw/{filepath}",
                    headers=headers,
                    content=iter_file(),
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HarnessManagerError(
                render_prompt(
                    await tr("harness.errors.http_error"),
                    status=exc.response.status_code,
                    method="PUT",
                    path=f"/instances/{instance_id}/raw/{filepath}",
                )
            ) from exc
        except httpx.RequestError as exc:
            raise HarnessManagerError(await tr("harness.errors.unreachable")) from exc
        return size

    async def delete_file(self, instance_id: str, filepath: str) -> None:
        await self._request("DELETE", f"/instances/{instance_id}/files/{filepath}")

    async def delete_tree(self, instance_id: str, dirpath: str) -> bool:
        response = await self._request("DELETE", f"/instances/{instance_id}/trees/{dirpath}")
        data = cast(dict[str, str], response.json())
        return data.get("status") == "deleted"

    async def list_instances(self) -> list[str]:
        response = await self._request("GET", "/instances")
        data = cast(dict[str, list[str]], response.json())
        return data.get("instances", [])

    async def get_system_info(self) -> dict[str, int]:
        response = await self._request("GET", "/system/info")
        return cast(dict[str, int], response.json())

    async def get_logs(self, instance_id: str, lines: int = 300) -> list[str]:
        response = await self._request(
            "GET",
            f"/instances/{instance_id}/logs?lines={lines}",
            timeout=20.0,
        )
        data = cast(dict[str, list[str]], response.json())
        return data.get("lines", [])

    async def check_reachable(self) -> bool:
        if not self.configured:
            return False
        try:
            payload = await self.get_contract()
        except (HarnessManagerError, ValueError, TypeError):
            return False
        capabilities = {
            str(value).strip().lower()
            for value in as_list(payload.get("capabilities"))
            if str(value).strip()
        }
        return (
            payload.get("service") == "bridge.harness"
            and {"compose-lifecycle", "file-share"} <= capabilities
        )


manager = HarnessManager()
