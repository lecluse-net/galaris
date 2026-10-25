"""HTTP authentication boundary shared by FastMCP and Pydantic AI transports."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from urllib.parse import urlsplit

import httpx2 as httpx

from core.database import get_db_session
from core.i18n import t
from .oauth_service import OAuthError, access_token, invalidate_token
from .parameter_resolution import RuntimeConnectionParams


class ConnectionOAuthAuth(httpx.Auth):
    def __init__(self, connection_id: int, server_url: str) -> None:
        self.connection_id = connection_id
        self.server_url = server_url

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        expected = urlsplit(self.server_url)
        actual = urlsplit(str(request.url))
        if ((actual.scheme, actual.hostname, actual.port or (443 if actual.scheme == "https" else 80))
                != (expected.scheme, expected.hostname, expected.port or (443 if expected.scheme == "https" else 80))):
            raise OAuthError("configuration")

        async def resolve() -> str:
            # A transport callback is an autonomous infrastructure root. Each
            # request owns its transaction; parallel discoveries never share the
            # parent AsyncSession. The row lock serializes refresh token rotation.
            async with get_db_session():
                return await access_token(self.connection_id, self.server_url)

        try:
            token = await asyncio.create_task(resolve())
        except OAuthError as exc:
            raise ValueError(t(f"connection_api.oauth.{exc}")) from None
        request.headers["Authorization"] = "Bearer " + token
        # Never replay a request with an uncertain remote effect after a 401.
        response = yield request
        if response.status_code == 401:
            async def invalidate() -> None:
                async with get_db_session():
                    await invalidate_token(self.connection_id, token)
            await asyncio.create_task(invalidate())


def mcp_oauth_auth(params: Mapping[str, object], server_url: str) -> httpx.Auth | None:
    if not isinstance(params, RuntimeConnectionParams) or not params.oauth_enabled:
        return None
    return ConnectionOAuthAuth(params.connection_id, server_url)
