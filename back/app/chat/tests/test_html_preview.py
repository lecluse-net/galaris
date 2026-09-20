from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.chat import html_preview
from app.chat import router as chat_router
from core.params.runtime_settings import runtime_settings
from core.settings import settings


def html_upload(content: bytes = b"<!doctype html><script src='https://cdn.example/app.js'></script>") -> UploadFile:
    return UploadFile(
        filename="dashboard.html",
        file=BytesIO(content),
        headers=Headers({"content-type": "text/html"}),
    )


@pytest.mark.asyncio
async def test_preview_ticket_round_trips_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    upload = html_upload()

    ticket = await html_preview.store(upload)
    resolved = await html_preview.resolve(ticket)

    assert resolved == html_preview.path_for(ticket)
    assert resolved is not None
    assert resolved.read_bytes() == await _upload_bytes(upload)


@pytest.mark.asyncio
async def test_expired_preview_ticket_is_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    ticket = await html_preview.store(html_upload(b"<p>expired</p>"))
    path = html_preview.path_for(ticket)
    expired = path.stat().st_mtime + 60 * 60 + 1

    assert await html_preview.resolve(ticket, now=expired) is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_preview_rejects_non_html_and_oversized_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )
    invalid = UploadFile(
        filename="payload.txt",
        file=BytesIO(b"plain text"),
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(html_preview.HtmlPreviewError, match="must be HTML"):
        await html_preview.store(invalid)

    monkeypatch.setattr(runtime_settings, "MESSENGER_CONTENT_MAX_MB", 1)
    with pytest.raises(html_preview.HtmlPreviewTooLargeError, match="exceeds"):
        await html_preview.store(html_upload(b"x" * 1_000_001))


@pytest.mark.asyncio
async def test_unknown_preview_ticket_is_not_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path)
    )

    assert await html_preview.resolve(uuid4()) is None


@pytest.mark.asyncio
async def test_preview_response_allows_cdns_inside_an_http_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "preview.html"
    path.write_text("<p>preview</p>")
    monkeypatch.setattr(html_preview, "resolve", AsyncMock(return_value=path))

    response = await chat_router.read_standalone_html_preview(uuid4())

    policy = response.headers["content-security-policy"]
    assert policy.startswith("sandbox allow-scripts")
    assert "script-src * data: blob:" in policy
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"


async def _upload_bytes(upload: UploadFile) -> bytes:
    await upload.seek(0)
    return await upload.read()


@pytest.mark.asyncio
async def test_previews_and_attachments_share_the_cumulative_quota(tmp_path, monkeypatch):
    from app.chat import storage
    from core.params import runtime_settings

    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path))
    monkeypatch.setattr(runtime_settings, "GALARIS_INTERNAL_MESSENGER_MAX_BYTES", 1_000_000)
    first = await html_preview.store(html_upload(b"x" * 999_996))
    with pytest.raises(storage.AttachmentStorageFullError):
        await storage.store_upload(UploadFile(filename="x.txt", file=BytesIO(b"12345")), uuid4())
    with pytest.raises(storage.AttachmentStorageFullError):
        await html_preview.store(html_upload(b"12345"))
    assert await html_preview.resolve(first) is not None
    assert not list(tmp_path.rglob("*.part"))
    await html_preview.cleanup_expired(now=html_preview.path_for(first).stat().st_mtime + 3601)
    assert await html_preview.resolve(await html_preview.store(html_upload(b"12345"))) is not None
