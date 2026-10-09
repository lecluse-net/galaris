"""AFFiNE resources must deliver blob bytes, never the application's HTML shell."""

import asyncio
import base64

import httpx
import pytest

from app.file_share import resource_service
from app.file_share.bridges import AffineResourceTransport
from app.file_share.resource_contracts import ResourceContext
from bridge.affine import AffineFileClient
from bridge.affine import client as affine_client
from app.tools.tool_errors import classify_tool_failure, render_tool_failure
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
    payload, requests = affine_http
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
    rebuilt = AffineResourceTransport("https://affine.example.test", "reader@example.test", "synthetic")
    assert (await rebuilt.blob_metadata("image-key=", target="workspace-test")).size == len(payload)
    assert sum(request.url.path == "/api/auth/sign-in" for request in requests) == 1
    with pytest.raises(httpx.HTTPStatusError):
        await resource_service.resource_info(ctx, "affine-test://workspace-test/denied")
    with pytest.raises(ValueError, match="HTML"):
        await resource_service.resource_info(ctx, "affine-test://workspace-test/missing")


@pytest.mark.asyncio
async def test_affine_keeps_html_attachments_and_download_limits(affine_http, tmp_path):
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    assert await client.download("page.html", "workspace-test") == b"<p>Attached HTML</p>"
    with pytest.raises(ValueError):
        await client.download_to("image-key=", tmp_path / "limited.jpg", target="workspace-test", max_bytes=3)


@pytest.mark.asyncio
async def test_affine_concurrent_rebuilt_clients_share_one_login(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    sign_ins = 0

    async def respond(request):
        nonlocal sign_ins
        if request.url.path == "/api/auth/sign-in":
            sign_ins += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, headers={"set-cookie": "session=synthetic; Path=/"})
        assert request.headers["cookie"] == "session=synthetic"
        return httpx.Response(200, content=b"synthetic-payload")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    clients = [AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic") for _ in range(25)]
    pending = [asyncio.create_task(client.download("image-key=", "workspace-test")) for client in clients]
    await asyncio.wait_for(entered.wait(), timeout=2)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*pending), timeout=2)
    assert results == [b"synthetic-payload"] * len(clients)
    assert sign_ins == 1


@pytest.mark.asyncio
async def test_affine_session_isolation_and_expiry(affine_http, monkeypatch):
    _, requests = affine_http
    now = 1000.0
    monkeypatch.setattr(affine_client, "monotonic", lambda: now)
    first = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    for client in (
        first,
        AffineFileClient("https://other-affine.example.test", "reader@example.test", "synthetic"),
        AffineFileClient("https://affine.example.test", "other-reader@example.test", "synthetic"),
        AffineFileClient("https://affine.example.test", "reader@example.test", "changed-synthetic"),
    ):
        await client.download("image-key=", "workspace-test")
    assert sum(request.url.path == "/api/auth/sign-in" for request in requests) == 4
    await first.download("image-key=", "workspace-test")
    assert sum(request.url.path == "/api/auth/sign-in" for request in requests) == 4
    now += 601.0
    await first.download("image-key=", "workspace-test")
    assert sum(request.url.path == "/api/auth/sign-in" for request in requests) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["sign_in", "download", "upload"])
@pytest.mark.parametrize("status,kind", [(401, "authentication"), (403, "permission_denied"), (429, "rate_limited"), (503, "provider")])
async def test_affine_http_failures_preserve_status_without_leaking_provider_data(monkeypatch, tmp_path, phase, status, kind):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/auth/sign-in" and phase != "sign_in":
            return httpx.Response(200, headers={"set-cookie": "session=synthetic; Path=/"})
        return httpx.Response(status, text="private-provider-detail password=synthetic-secret")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    source = tmp_path / "image.jpg"
    source.write_bytes(b"synthetic")
    # Both buffered and streamed operations retain the HTTP failure, with no replay.
    for operation in (
        lambda: client.upload(b"synthetic", "image.jpg", "workspace-test") if phase == "upload" else client.download("key", "workspace-test"),
        lambda: client.upload_from(source, "image.jpg", target="workspace-test") if phase == "upload" else client.download_to("key", tmp_path / "download", target="workspace-test"),
    ):
        before = len(requests)
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await operation()
        failure = classify_tool_failure(caught.value)
        assert failure.kind == kind
        assert failure.http_status == status
        diagnostic = render_tool_failure(tool_name="file_copy", failure=failure, language="en", reference="synthetic-ref")
        assert f"HTTP {status}" in diagnostic
        assert "private-provider-detail" not in diagnostic
        assert "synthetic-secret" not in diagnostic
        assert sum(request.url.path != "/api/auth/sign-in" for request in requests[before:]) == (0 if phase == "sign_in" else 1)
        assert sum(request.url.path == "/api/auth/sign-in" for request in requests[before:]) <= 1


@pytest.mark.asyncio
async def test_affine_missing_blob_retains_not_found_contract_and_http_status(affine_http):
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    with pytest.raises(FileNotFoundError) as caught:
        await client.blob_metadata("image.jpg", target="workspace-test")
    failure = classify_tool_failure(caught.value)
    assert failure.kind == "not_found"
    assert failure.http_status == 404


@pytest.mark.asyncio
async def test_affine_session_cache_evicts_idle_accounts(affine_http, monkeypatch):
    _, requests = affine_http
    monkeypatch.setattr(affine_client, "_SESSION_LIMIT", 2)
    for account in ("first", "second", "third", "first"):
        client = AffineFileClient("https://affine.example.test", f"{account}@example.test", "synthetic")
        await client.download("image-key=", "workspace-test")
    assert sum(request.url.path == "/api/auth/sign-in" for request in requests) == 4


@pytest.mark.asyncio
async def test_affine_rate_limited_login_defers_other_calls_until_retry_after(monkeypatch):
    sign_ins = 0
    now = 1000.0
    monkeypatch.setattr(affine_client, "monotonic", lambda: now)

    async def respond(request):
        nonlocal sign_ins
        if request.url.path == "/api/auth/sign-in":
            sign_ins += 1
            await asyncio.sleep(0)
            if sign_ins == 1:
                return httpx.Response(429, headers={"retry-after": "30"}, text="private-provider-body")
            return httpx.Response(200, headers={"set-cookie": "session=synthetic; Path=/"})
        return httpx.Response(200, content=b"synthetic-payload")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    clients = [AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic") for _ in range(25)]
    results = await asyncio.gather(*(client.download("key", "workspace-test") for client in clients), return_exceptions=True)
    assert all(isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 429 for result in results)
    assert sign_ins == 1
    now += 31.0
    assert await clients[0].download("key", "workspace-test") == b"synthetic-payload"
    assert sign_ins == 2


@pytest.mark.asyncio
async def test_affine_rejected_session_renews_on_next_explicit_call(monkeypatch):
    sign_ins = 0
    downloads = 0

    def respond(request):
        nonlocal sign_ins, downloads
        if request.url.path == "/api/auth/sign-in":
            sign_ins += 1
            return httpx.Response(200, headers={"set-cookie": f"session=synthetic-{sign_ins}; Path=/"})
        downloads += 1
        if downloads == 1:
            return httpx.Response(401)
        assert request.headers["cookie"] == "session=synthetic-2"
        return httpx.Response(200, content=b"synthetic-payload")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    with pytest.raises(httpx.HTTPStatusError):
        await client.download("key", "workspace-test")
    assert (sign_ins, downloads) == (1, 1)
    assert await client.download("key", "workspace-test") == b"synthetic-payload"
    assert await client.download("key", "workspace-test") == b"synthetic-payload"
    assert (sign_ins, downloads) == (2, 3)


@pytest.mark.asyncio
async def test_affine_late_unauthorized_response_keeps_the_new_session(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    sign_ins = 0

    async def respond(request):
        nonlocal sign_ins
        if request.url.path == "/api/auth/sign-in":
            sign_ins += 1
            return httpx.Response(200, headers={"set-cookie": f"session=synthetic-{sign_ins}; Path=/"})
        if request.url.path.endswith("/late"):
            entered.set()
            await release.wait()
            return httpx.Response(401)
        if request.url.path.endswith("/expired"):
            return httpx.Response(401)
        return httpx.Response(200, content=request.headers["cookie"].encode())

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    assert await client.download("key", "workspace-test") == b"session=synthetic-1"
    late = asyncio.create_task(client.download("late", "workspace-test"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    with pytest.raises(httpx.HTTPStatusError):
        await client.download("expired", "workspace-test")
    assert await client.download("key", "workspace-test") == b"session=synthetic-2"
    release.set()
    with pytest.raises(httpx.HTTPStatusError):
        await asyncio.wait_for(late, timeout=2)
    assert await client.download("key", "workspace-test") == b"session=synthetic-2"
    assert sign_ins == 2


@pytest.mark.asyncio
async def test_affine_missing_session_cookie_is_not_cached(monkeypatch):
    sign_ins = 0

    def respond(request):
        nonlocal sign_ins
        assert request.url.path == "/api/auth/sign-in"
        sign_ins += 1
        return httpx.Response(200)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await client.download("key", "workspace-test")
    assert sign_ins == 2


@pytest.mark.asyncio
async def test_affine_cancelled_login_releases_waiting_clients(monkeypatch):
    entered = asyncio.Event()
    sign_ins = 0

    async def respond(request):
        nonlocal sign_ins
        if request.url.path == "/api/auth/sign-in":
            sign_ins += 1
            if sign_ins == 1:
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(200, headers={"set-cookie": "session=synthetic; Path=/"})
        return httpx.Response(200, content=b"synthetic-payload")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = AffineFileClient("https://affine.example.test", "reader@example.test", "synthetic")
    cancelled = asyncio.create_task(client.download("key", "workspace-test"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    waiting = asyncio.create_task(client.download("key", "workspace-test"))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert await asyncio.wait_for(waiting, timeout=2) == b"synthetic-payload"
    assert sign_ins == 2
