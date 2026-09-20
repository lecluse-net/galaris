from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from bridge.matrix.client import (
    MATRIX_API,
    MATRIX_MEDIA_API,
    MATRIX_MEDIA_UPLOAD_API,
    Matrix,
)


def _matrix(
    handler: Any,
    *,
    media_max_bytes: int = 16_000_000,
) -> Matrix:
    matrix = Matrix(
        homeserver="https://matrix.example.test",
        user_id="@agent:example.test",
        access_token="secret",
        media_max_bytes=media_max_bytes,
    )
    matrix._client = httpx.AsyncClient(  # pyright: ignore[reportPrivateUsage]
        transport=httpx.MockTransport(handler),
        base_url=matrix.homeserver,
    )
    return matrix


@pytest.mark.asyncio
async def test_whoami_validates_the_authenticated_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{MATRIX_API}/account/whoami"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"user_id": "@real:example.test"})

    matrix = _matrix(handler)
    try:
        assert await matrix.whoami() == "@real:example.test"
        assert matrix.user_id == "@real:example.test"
    finally:
        await matrix.aclose()


@pytest.mark.asyncio
async def test_room_history_page_forwards_and_returns_matrix_cursor() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{MATRIX_API}/rooms/!room:example.test/messages"
        assert request.url.params["dir"] == "b"
        assert request.url.params["limit"] == "50"
        assert request.url.params["from"] == "previous-token"
        return httpx.Response(
            200,
            json={
                "chunk": [{"event_id": "$message"}],
                "end": "next-token",
            },
        )

    matrix = _matrix(handler)
    try:
        chunk, cursor = await matrix.get_room_messages_page(
            "!room:example.test",
            limit=50,
            from_token="previous-token",
        )
    finally:
        await matrix.aclose()

    assert chunk == [{"event_id": "$message"}]
    assert cursor == "next-token"


@pytest.mark.asyncio
async def test_media_upload_and_authenticated_download() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer secret"
        if request.url.path == f"{MATRIX_MEDIA_UPLOAD_API}/upload":
            assert request.url.params["filename"] == "photo.png"
            assert request.headers["Content-Type"] == "image/png"
            assert request.read() == b"image"
            return httpx.Response(
                200,
                json={"content_uri": "mxc://media.example.test/abc"},
            )
        assert request.url.path == (
            f"{MATRIX_MEDIA_API}/download/media.example.test/abc"
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png", "Content-Length": "5"},
            content=b"image",
        )

    matrix = _matrix(handler)
    try:
        uri = await matrix.upload_media(b"image", "photo.png", "image/png")
        assert uri == "mxc://media.example.test/abc"
        assert await matrix.download_media(uri) == b"image"
    finally:
        await matrix.aclose()

    assert paths == [
        f"{MATRIX_MEDIA_UPLOAD_API}/upload",
        f"{MATRIX_MEDIA_API}/download/media.example.test/abc",
    ]


@pytest.mark.asyncio
async def test_streamed_media_upload_preserves_size_and_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"document")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{MATRIX_MEDIA_UPLOAD_API}/upload"
        assert request.headers["Content-Length"] == "8"
        assert await request.aread() == b"document"
        return httpx.Response(
            200,
            json={"content_uri": "mxc://media.example.test/document"},
        )

    matrix = _matrix(handler)
    try:
        assert await matrix.upload_media_path(
            source,
            "document.pdf",
            "application/pdf",
        ) == "mxc://media.example.test/document"
    finally:
        await matrix.aclose()


@pytest.mark.asyncio
async def test_media_limits_apply_before_and_during_transfer() -> None:
    requests = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=b"12345")

    matrix = _matrix(handler, media_max_bytes=4)
    try:
        with pytest.raises(ValueError, match="size limit"):
            await matrix.upload_media(b"12345", "file.bin", "application/octet-stream")
        assert requests == 0

        with pytest.raises(ValueError, match="size limit"):
            await matrix.download_media("mxc://media.example.test/large")
        assert requests == 1
    finally:
        await matrix.aclose()


@pytest.mark.asyncio
async def test_media_download_falls_back_for_pre_authenticated_media_server(
    tmp_path: Path,
) -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.startswith(MATRIX_MEDIA_API):
            return httpx.Response(404)
        return httpx.Response(200, content=b"legacy")

    matrix = _matrix(handler)
    destination = tmp_path / "download.bin"
    try:
        size = await matrix.download_media_to_file(
            "mxc://old.example.test/media",
            destination,
        )
    finally:
        await matrix.aclose()

    assert size == 6
    assert destination.read_bytes() == b"legacy"
    assert paths == [
        f"{MATRIX_MEDIA_API}/download/old.example.test/media",
        f"{MATRIX_MEDIA_UPLOAD_API}/download/old.example.test/media",
    ]


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "https://media.example.test/file",
        "mxc:///file",
        "mxc://media.example.test",
        "mxc://user:password@media.example.test/file",
        "mxc://media.example.test/file?query=true",
    ],
)
def test_invalid_mxc_uri_is_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="Invalid Matrix content URI"):
        Matrix._parse_mxc(uri)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_direct_room_creation_updates_account_data() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        account_data = (
            f"{MATRIX_API}/user/@agent:example.test/account_data/m.direct"
        )
        if request.method == "GET" and request.url.path == account_data:
            return httpx.Response(404)
        if request.method == "POST":
            assert request.url.path == f"{MATRIX_API}/createRoom"
            assert request.read() == (
                b'{"is_direct":true,"preset":"trusted_private_chat",'
                b'"invite":["@alice:example.test"]}'
            )
            return httpx.Response(
                200,
                json={"room_id": "!direct:example.test"},
            )
        assert request.method == "PUT"
        assert request.url.path == account_data
        assert request.read() == (
            b'{"@alice:example.test":["!direct:example.test"]}'
        )
        return httpx.Response(200, json={})

    matrix = _matrix(handler)
    try:
        room_id = await matrix.ensure_direct_room("@alice:example.test")
    finally:
        await matrix.aclose()

    assert room_id == "!direct:example.test"
    assert requests == [
        (
            "GET",
            f"{MATRIX_API}/user/@agent:example.test/account_data/m.direct",
        ),
        ("POST", f"{MATRIX_API}/createRoom"),
        (
            "GET",
            f"{MATRIX_API}/user/@agent:example.test/account_data/m.direct",
        ),
        (
            "PUT",
            f"{MATRIX_API}/user/@agent:example.test/account_data/m.direct",
        ),
    ]
