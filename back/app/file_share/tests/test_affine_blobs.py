"""AFFiNE resources must deliver blob bytes, never the application's HTML shell."""

import base64

import httpx
import pytest

from app.file_share import resource_service
from app.file_share.bridges import AffineResourceTransport
from app.file_share.resource_contracts import ResourceContext
from bridge.affine import AffineFileClient
from .local_file_transport import TemporaryFileTransport


@pytest.fixture
def affine_http(monkeypatch):
    payload = b"\xff\xd8\xffsynthetic-jpeg"
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/auth/sign-in":
            return httpx.Response(200, headers={"set-cookie": "session=synthetic; Path=/"})
        assert request.headers.get("cookie") == "session=synthetic"
        if request.url.path == "/graphql":
            assert b'filename="image.jpg"' in request.content
            return httpx.Response(200, json={"data": {"setBlob": "uploaded-key"}})
        if request.url.path == "/api/workspaces/workspace-test/blobs/image-key=":
            return httpx.Response(200, content=payload, headers={"content-type": "image/jpeg"})
        if request.url.path.endswith("/denied"):
            return httpx.Response(403)
        if request.url.path.endswith("/page.html"):
            return httpx.Response(200, text="<p>Attached HTML</p>", headers={
                "content-type": "text/html", "content-disposition": 'attachment; filename="page.html"',
            })
        if request.url.path.endswith("/image.jpg"):
            return httpx.Response(404)
        return httpx.Response(200, text="<!doctype html><html>Application shell</html>",
                              headers={"content-type": "text/html; charset=utf-8"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    return payload, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", ["image-key=", "blob/image-key=", "blobs/image-key="])
@pytest.mark.parametrize("streamed", [False, True])
async def test_affine_download_preserves_image_bytes(affine_http, tmp_path, remote, streamed):
    payload, _ = affine_http
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    if streamed:
        dest = tmp_path / "image.jpg"
        size = await client.download_to(remote, dest, target="workspace-test")
        assert size == len(payload)
        assert dest.read_bytes() == payload
    else:
        assert await client.download(remote, "workspace-test") == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_affine_rejects_html_shell_before_writing(affine_http, tmp_path, streamed):
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    dest = tmp_path / "image.jpg"
    with pytest.raises(ValueError, match="HTML"):
        if streamed:
            await client.download_to("missing", dest, target="workspace-test")
        else:
            await client.download("missing", "workspace-test")
    assert not dest.exists()


@pytest.mark.asyncio
async def test_affine_resource_read_and_copy_check_remote_access(affine_http, monkeypatch, tmp_path):
    payload, _ = affine_http
    client = AffineResourceTransport("https://affine.example.test", "reader@example.test", "synthetic")

    async def resolve(*args, **kwargs):
        return client, "affine"

    console = TemporaryFileTransport(tmp_path / "console")

    async def resolve_console(_ctx):
        return console

    monkeypatch.setattr(resource_service, "resolve_resource_transport_with_service", resolve)
    monkeypatch.setattr(resource_service, "_console_transport", resolve_console)
    ctx = ResourceContext(agent_id=1, runtime="internal")
    uri = "affine-test://workspace-test/blob/image-key="
    info = await resource_service.resource_info(ctx, uri)
    assert info.media_type == "image/jpeg"
    assert info.size == len(payload)
    assert info.name == "image-key=.jpg"
    assert info.uri == uri
    read = await resource_service.resource_read(ctx, uri)
    assert read.media_type == "image/jpeg"
    assert read.encoding == "base64"
    assert base64.b64decode(read.content) == payload
    copied = await resource_service.resource_copy(ctx, uri, "console://image.jpg")
    assert copied.size == len(payload)
    assert console.resolve_path("image.jpg", create_parent=False).read_bytes() == payload
    copied_collection = await resource_service.resource_copy(ctx, uri, "console://imports/")
    assert copied_collection.uri == "console://imports/image-key=.jpg"
    uploaded = await resource_service.resource_copy(ctx, copied.uri, "affine-test://workspace-test")
    assert uploaded.uri == "affine-test://workspace-test/uploaded-key"
    with pytest.raises(RuntimeError):
        await resource_service.resource_info(ctx, "affine-test://workspace-test/denied")
    with pytest.raises(ValueError, match="HTML"):
        await resource_service.resource_info(ctx, "affine-test://workspace-test/missing")


@pytest.mark.asyncio
async def test_affine_keeps_html_attachments_and_download_limits(affine_http, tmp_path):
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    assert await client.download("page.html", "workspace-test") == b"<p>Attached HTML</p>"
    with pytest.raises(ValueError):
        await client.download_to("image-key=", tmp_path / "limited.jpg", target="workspace-test", max_bytes=3)
