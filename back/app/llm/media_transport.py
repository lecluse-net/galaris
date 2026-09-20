"""Bounded HTTP support shared by specialist provider bridges."""

from pathlib import Path
from typing import Any
import asyncio

import httpx

from core.util import as_dict, read_response
from .media_contracts import MediaOperation, MediaRequest, MediaResult, MediaRequestRejected
from .provider_facade import ProviderConnection

MAX_MEDIA_BYTES = 100_000_000


async def media_http(
    connection: ProviderConnection, method: str, path: str,
    *, body: dict[str, Any] | None = None, auth_header: str = "Authorization",
    binary: bool = False,
) -> bytes:
    credential = connection.api_key or ""
    if auth_header == "Authorization":
        credential = f"Bearer {credential}"
    async with asyncio.timeout(600), httpx.AsyncClient(timeout=600.0, follow_redirects=False) as client:
        async with client.stream(
            method, f"{connection.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={auth_header: credential, "Accept-Encoding": "identity"}, json=body,
        ) as response:
            if not response.is_success:
                if 400 <= response.status_code < 500 and response.status_code != 408:
                    raise MediaRequestRejected(f"Media provider rejected the request (HTTP {response.status_code}).")
                raise ValueError(f"Media provider returned HTTP {response.status_code}.")
            limit = MAX_MEDIA_BYTES if binary else 2_000_000
            return await read_response(response, max_bytes=limit)


async def media_json(
    connection: ProviderConnection, method: str, path: str,
    *, body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import json

    return as_dict(json.loads(await media_http(connection, method, path, body=body)))


class GenerationProvider:
    """Defaults for providers with no analysis or remote polling service."""

    def supports(self, operation: MediaOperation, model: str) -> bool:
        return False

    def validate(self, request: MediaRequest) -> None:
        if not self.supports(request.operation, request.model):
            raise ValueError("This provider does not support the selected operation/model.")

    async def analyze(
        self, connection: ProviderConnection, request: MediaRequest,
        source: Path, media_type: str,
    ) -> MediaResult:
        raise ValueError("This provider does not analyze media.")

    async def submit(
        self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str,
    ) -> MediaResult:
        raise ValueError("This provider does not generate media.")

    async def poll(
        self, connection: ProviderConnection, request: MediaRequest, external_id: str,
    ) -> MediaResult:
        return MediaResult("unknown", external_id=external_id)
