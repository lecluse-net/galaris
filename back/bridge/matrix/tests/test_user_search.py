from __future__ import annotations

import httpx
import pytest

from bridge.matrix.client import MATRIX_API, Matrix


@pytest.mark.asyncio
async def test_user_directory_search_allows_an_empty_term() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{MATRIX_API}/user_directory/search"
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.read() == b'{"search_term":"","limit":10000}'
        return httpx.Response(
            200,
            json={
                "results": [
                    {"user_id": "@nicolas:example.test", "display_name": "Nicolas"},
                    {"user_id": "@sarah:example.test", "display_name": "Sarah"},
                ]
            },
        )

    matrix = Matrix(
        homeserver="https://matrix.example.test",
        user_id="@agent:example.test",
        access_token="secret",
    )
    matrix._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=httpx.MockTransport(handler),
        base_url=matrix.homeserver,
    )
    try:
        users = await matrix.search_users("")
    finally:
        await matrix.aclose()

    assert [user["user_id"] for user in users] == [
        "@nicolas:example.test",
        "@sarah:example.test",
    ]
