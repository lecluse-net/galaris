"""Exercise the real URI facade and Nextcloud adapter at the HTTP boundary."""

import gzip
import asyncio
import zlib
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

import httpx
import pytest

from app.file_share import resource_service as files
from app.file_share.resource_contracts import ResourceContext
from bridge.nextcloud.file_share import NextcloudFileClient


class DavServer:
    """Synthetic WebDAV peer, including HTTP preconditions and concurrent writers."""

    prefix = "/cloud/remote.php/dav/files/synthetic/"

    def __init__(self):
        self.files = {}
        self.versions = {}
        self.requests = []
        self.race_on_put = None
        self.dirs = {""}
        self.share_body = {
            "ocs": {
                "meta": {"status": "ok", "statuscode": 200},
                "data": {"url": "https://cloud.example.test/s/synthetic-token"},
            }
        }
        self.forced_status = None
        self.response_encoding = None

    def put(self, path, content):
        self.files[path] = content
        self.versions[path] = self.versions.get(path, 0) + 1

    def etag(self, path):
        return f'"v{self.versions.get(path, 0)}"'

    def entry(self, path, directory=False):
        kind = "<d:collection/>" if directory else ""
        return (
            "<d:response><d:href>"
            + escape(self.prefix + quote(path, safe="/"))
            + "</d:href><d:propstat><d:prop><d:resourcetype>"
            + kind
            + "</d:resourcetype><d:getcontentlength>"
            + str(len(self.files.get(path, b"")))
            + "</d:getcontentlength><d:getcontenttype>text/plain</d:getcontenttype>"
            + "<d:getetag>"
            + escape(self.etag(path))
            + "</d:getetag>"
            + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        )

    async def handle(self, request):
        self.requests.append(request)
        if self.forced_status is not None:
            return httpx.Response(
                self.forced_status, content=b"sensitive response must not be echoed"
            )
        if request.url.path.endswith("/shares"):
            return httpx.Response(200, json=self.share_body)
        assert request.url.path == self.prefix.rstrip("/") or request.url.path.startswith(
            self.prefix
        )
        path = request.url.path[len(self.prefix.rstrip("/")) :].strip("/")
        dirs = self.dirs
        for name in self.files:
            parts = name.split("/")
            dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        if request.method == "PROPFIND":
            if request.headers.get("depth") == "infinity":
                return httpx.Response(403)
            if path not in self.files and path not in dirs:
                return httpx.Response(404)
            body = self.entry(path, path in dirs)
            if request.headers.get("depth") == "1":
                children = sorted(
                    name
                    for name in set(self.files) | dirs
                    if name and name.rpartition("/")[0] == path
                )
                body += "".join(self.entry(name, name in dirs) for name in children)
            content = ('<d:multistatus xmlns:d="DAV:">' + body + "</d:multistatus>").encode()
            if self.response_encoding:
                encoded = gzip.compress(content) if self.response_encoding == "gzip" else zlib.compress(content)
                return httpx.Response(207, stream=httpx.ByteStream(encoded), headers={
                    "Content-Encoding": self.response_encoding,
                    "Content-Length": str(len(encoded)),
                    "Content-Type": "application/xml",
                })
            return httpx.Response(207, content=content)
        if request.method == "GET":
            if path not in self.files:
                return httpx.Response(404)
            return httpx.Response(
                200,
                content=self.files[path],
                headers={"ETag": self.etag(path), "Content-Type": "text/plain"},
            )
        if request.method == "PUT":
            if self.race_on_put:
                self.put(path, self.race_on_put)
                self.race_on_put = None
            if request.headers.get("if-none-match") == "*" and path in self.files:
                return httpx.Response(412)
            expected = request.headers.get("if-match")
            if expected and (path not in self.files or expected != self.etag(path)):
                return httpx.Response(412)
            exists = path in self.files
            self.put(path, await request.aread())
            return httpx.Response(204 if exists else 201, headers={"ETag": self.etag(path)})
        if request.method == "MKCOL":
            status = 405 if path in dirs else 201
            dirs.add(path)
            return httpx.Response(status)
        if request.method in {"MOVE", "COPY"}:
            if path not in self.files:
                return httpx.Response(404)
            destination = unquote(urlsplit(request.headers["destination"]).path)[len(self.prefix) :]
            if request.headers.get("overwrite") == "F" and destination in self.files:
                return httpx.Response(412)
            if request.headers.get("if-match") != self.etag(path):
                return httpx.Response(412)
            self.put(destination, self.files[path])
            if request.method == "MOVE":
                del self.files[path]
            return httpx.Response(201)
        if request.method == "DELETE":
            if request.headers.get("if-match") != self.etag(path):
                return httpx.Response(412)
            del self.files[path]
            return httpx.Response(204)
        raise AssertionError(request.method)


@pytest.fixture
def dav(monkeypatch):
    server = DavServer()
    adapter = NextcloudFileClient("https://cloud.example.test/cloud", "synthetic", "synthetic")
    monkeypatch.setattr(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(server.handle))
    )

    async def resolve(*args, **kwargs):
        return adapter, "nextcloud"

    monkeypatch.setattr(files, "resolve_resource_transport_with_service", resolve)
    return server, adapter, ResourceContext(agent_id=1, runtime="internal")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("folder_denied", [False, True])
async def test_live_metadata_batch_bounds_concurrency_closes_pool_and_rechecks_rights(dav, monkeypatch, cancel, folder_denied):
    server, adapter, _ctx = dav
    paths = [f"{'shared' if folder_denied else f'folder-{index}'}/file-{index}.txt" for index in range(20)] + ["missing.txt"]
    for path in paths[:-1]:
        server.put(path, b"Synthetic data")
    started, release = asyncio.Event(), asyncio.Event()
    active, maximum = 0, 0
    clients = []
    async def handle(request):
        nonlocal active, maximum
        if request.headers.get('Depth') == '1' and folder_denied:
            return httpx.Response(403)
        active += 1
        maximum = max(maximum, active)
        if active == 8:
            started.set()
        try:
            await release.wait()
            if request.url.path.endswith("/file-3.txt"):
                return httpx.Response(403)
            return await server.handle(request)
        finally:
            active -= 1
    def client():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        clients.append(http)
        return http
    monkeypatch.setattr(adapter, "_client", client)
    pending = asyncio.create_task(adapter.resource_infos(paths))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
    except TimeoutError:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        raise
    assert maximum == 8 and len(clients) == 1
    if cancel:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        release.set()
        metadata = await pending
        assert set(metadata) == set(paths) - {paths[3], "missing.txt"}
        server.forced_status = 403
        assert await adapter.resource_infos(paths) == {}
    assert active == 0
    assert all(http.is_closed for http in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [300, 3000])
async def test_live_metadata_reads_scale_with_folders_and_preserve_exact_fallbacks(dav, monkeypatch, count):
    server, adapter, _ctx = dav
    paths = [f"folder-{index % 10}/synthetic-{index}.txt" for index in range(count)]
    for path in paths:
        server.put(path, b"Synthetic metadata")
    metadata = await adapter.resource_infos(paths)
    assert set(metadata) == set(paths)
    assert len(server.requests) == 10
    assert all(request.headers['Depth'] == '1' for request in server.requests)
    # Permissions are read anew, including a parent that cannot be listed while
    # its exact file remains accessible. A missing child is never admitted.
    async def partial(request):
        if request.headers.get('Depth') == '1':
            return httpx.Response(403)
        return await server.handle(request)
    monkeypatch.setattr(adapter, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(partial)))
    requested = [paths[0], paths[10], 'folder-0/missing.txt']
    assert set(await adapter.resource_infos(requested)) == set(requested) - {'folder-0/missing.txt'}
    server.forced_status = 403
    assert await adapter.resource_infos(requested) == {}


@pytest.mark.asyncio
async def test_create_does_not_overwrite_a_concurrent_pc_upload(dav):
    server, _, ctx = dav
    server.race_on_put = b"PC contribution"
    with pytest.raises(FileExistsError):
        await files.resource_create(ctx, "nextcloud://notes.txt", b"agent contribution")
    assert server.files["notes.txt"] == b"PC contribution"


@pytest.mark.asyncio
async def test_recursive_listing_and_search_reach_files_beyond_first_page(dav):
    server, _, ctx = dav
    for index in range(501):
        server.put(f"folder/item-{index:03}.txt", b"text")
    server.put("folder/z-needle.txt", b"result")
    uris = []
    cursor = None
    for _ in range(20):
        result = await files.resource_list(
            ctx, "nextcloud://", recursive=True, max_entries=50, cursor=cursor
        )
        uris.extend(item.uri for item in result.entries)
        cursor = result.next_cursor
        if not cursor:
            assert not result.truncated
            break
    assert len(uris) == len(set(uris)) == 503
    cursor = None
    hits = []
    for _ in range(20):
        result = await files.resource_search(ctx, "nextcloud://", "needle", cursor=cursor)
        hits.extend(hit.resource.uri for hit in result.hits)
        cursor = result.next_cursor
        if not cursor:
            assert not result.truncated
            break
    assert hits == ["nextcloud://folder/z-needle.txt"]
    assert cursor is None


@pytest.mark.asyncio
async def test_edit_preserves_concurrent_pc_changes(dav):
    server, _, ctx = dav
    server.put("notes.txt", b"original\n")
    server.race_on_put = b"PC contribution\n"
    from app.file_share.resource_uri import ResourceRevisionConflict

    with pytest.raises(ResourceRevisionConflict):
        await files.resource_edit(
            ctx, "nextcloud://notes.txt", start_line=1, end_line=1, content="agent"
        )
    assert server.files["notes.txt"] == b"PC contribution\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "résumé final.txt",
        "rapport#1.txt",
        "question?.txt",
        "literal%20name.txt",
        "literal%2Fname.txt",
    ],
)
async def test_complete_journey_preserves_names_content_and_versions(dav, name):
    import hashlib

    server, adapter, ctx = dav
    uri = "nextcloud://Shared/" + quote(name, safe="")
    created = await files.resource_create(ctx, "nextcloud://Shared/", b"one\ntwo\n", name=name)
    assert created.uri == uri
    listing = await files.resource_list(ctx, "nextcloud://Shared/")
    assert [(item.name, item.uri) for item in listing.entries] == [(name, uri)]
    read = await files.resource_read(ctx, uri)
    assert read.content == "one\ntwo\n" and read.etag
    info = await files.resource_info(ctx, uri, include_checksum=True)
    assert info.checksum == hashlib.sha256(b"one\ntwo\n").hexdigest()
    assert {"append", "edit", "move", "delete"} <= set(info.capabilities)
    await files.resource_edit(
        ctx, uri, start_line=2, end_line=2, content="updated", expected_etag=read.etag
    )
    await files.resource_append(ctx, uri, "end\n")
    assert server.files["Shared/" + name] == b"one\nupdated\nend\n"
    copied = await files.resource_copy(ctx, uri, "nextcloud://Archive/")
    assert copied.uri == "nextcloud://Archive/" + quote(name, safe="")
    moved = await files.resource_move(ctx, copied.uri, "nextcloud://Final/")
    assert moved.uri == "nextcloud://Final/" + quote(name, safe="")
    assert "Archive/" + name not in server.files
    await files.resource_delete(ctx, moved.uri)
    assert "Final/" + name not in server.files
    assert await adapter.share("Shared/" + name) == "https://cloud.example.test/s/synthetic-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["write", "edit", "append"])
async def test_stale_read_is_rejected_before_any_mutation(dav, operation):
    from app.file_share.resource_uri import ResourceRevisionConflict

    server, _, ctx = dav
    server.put("notes.txt", b"one\n")
    read = await files.resource_read(ctx, "nextcloud://notes.txt")
    server.put("notes.txt", b"PC change\n")
    before = len(server.requests)
    with pytest.raises(ResourceRevisionConflict):
        if operation == "write":
            await files.resource_write(ctx, read.uri, b"agent", expected_etag=read.etag)
        elif operation == "edit":
            await files.resource_edit(
                ctx, read.uri, start_line=1, end_line=1, content="agent", expected_etag=read.etag
            )
        else:
            await files.resource_append(ctx, read.uri, "agent", expected_etag=read.etag)
    assert server.files["notes.txt"] == b"PC change\n"
    assert all(
        request.method == "GET" or request.method == "PROPFIND"
        for request in server.requests[before:]
    )


@pytest.mark.asyncio
async def test_pagination_detects_changed_folder_and_rejects_other_scopes(dav):
    from app.file_share.resource_uri import ResourceRevisionConflict, ResourceValidationError

    server, _, ctx = dav
    for name in ["a.txt", "b.txt", "nested/c.txt"]:
        server.put(name, b"data")
    root = await files.resource_info(ctx, "nextcloud://")
    assert root.is_collection and root.uri == "nextcloud://"
    assert {"list", "search", "create"} <= set(root.capabilities)
    assert "delete" not in root.capabilities and "move" not in root.capabilities
    first = await files.resource_list(ctx, "nextcloud://", max_entries=1)
    with pytest.raises(ResourceValidationError):
        await files.resource_list(ctx, "nextcloud://nested/", cursor=first.next_cursor)
    server.put("aa.txt", b"new")
    with pytest.raises(ResourceRevisionConflict):
        await files.resource_list(ctx, "nextcloud://", cursor=first.next_cursor)


@pytest.mark.asyncio
async def test_text_search_reaches_late_content_and_reports_skipped_files(dav):
    server, _, ctx = dav
    server.put("long.txt", b"x" * 60000 + b"needle")
    server.put("binary.bin", b"\x00\xff")
    result = await files.resource_search(ctx, "nextcloud://", "needle", mode="text")
    assert [hit.resource.uri for hit in result.hits] == ["nextcloud://long.txt"]
    assert result.degraded and result.degradation_reason
    assert not result.truncated


@pytest.mark.asyncio
async def test_existing_create_move_and_collection_delete_preserve_data(dav):
    server, _, ctx = dav
    server.put("folder/a.txt", b"a")
    server.put("folder/b.txt", b"b")
    before = dict(server.files)
    with pytest.raises(FileExistsError):
        await files.resource_create(ctx, "nextcloud://folder/a.txt", b"new")
    with pytest.raises(FileExistsError):
        await files.resource_move(ctx, "nextcloud://folder/a.txt", "nextcloud://folder/b.txt")
    with pytest.raises(IsADirectoryError):
        await files.resource_delete(ctx, "nextcloud://folder/")
    assert server.files == before
    assert not any(request.method == "DELETE" for request in server.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"ocs": {"meta": {"status": "failure", "statuscode": 404}, "data": {}}},
        {"unexpected": "response"},
        {"ocs": {"meta": {"status": "ok", "statuscode": 200}, "data": {}}},
        {"ocs": {"meta": {"status": "ok", "statuscode": 200}, "data": {"url": "javascript:bad"}}},
        [],
        None,
    ],
)
async def test_share_rejects_unconfirmed_or_unusable_response(dav, body):
    server, adapter, _ = dav
    server.share_body = body
    with pytest.raises(RuntimeError, match="confirmed"):
        await adapter.share("file.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error",
    [
        (401, PermissionError),
        (403, PermissionError),
        (404, FileNotFoundError),
        (423, RuntimeError),
        (429, RuntimeError),
        (507, RuntimeError),
    ],
)
async def test_webdav_failures_remain_errors_without_echoing_remote_data(dav, status, error):
    server, adapter, _ = dav
    server.forced_status = status
    with pytest.raises(error) as failure:
        await adapter.resource_info("file.txt")
    assert "sensitive" not in str(failure.value)


@pytest.mark.asyncio
async def test_download_budget_and_connection_loss_clean_partial_files(dav, tmp_path, monkeypatch):
    server, adapter, _ = dav
    server.put("file.txt", b"123456")
    destination = tmp_path / "partial"
    with pytest.raises(ValueError):
        await adapter.download_to("file.txt", destination, max_bytes=3)
    assert not destination.exists()

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("connection lost")

    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=BrokenStream()))
        ),
    )
    with pytest.raises(httpx.ReadError):
        await adapter.download_to("file.txt", destination)
    assert not destination.exists()


@pytest.mark.asyncio
async def test_cross_provider_move_preserves_source_changed_during_copy(dav, monkeypatch, tmp_path):
    from app.file_share.tests.local_file_transport import TemporaryFileTransport

    server, _, ctx = dav
    server.put("file.txt", b"copied version")

    class Destination(TemporaryFileTransport):
        async def upload_from(self, src, filename, *, target=""):
            location = await super().upload_from(src, filename, target=target)
            server.put("file.txt", b"PC new version")
            return location

    destination = Destination(tmp_path / "console")

    async def resolve_console(_ctx):
        return destination

    monkeypatch.setattr(files, "_console_transport", resolve_console)
    with pytest.raises(RuntimeError, match="source deletion failed"):
        await files.resource_move(ctx, "nextcloud://file.txt", "console://copy.txt")
    assert server.files["file.txt"] == b"PC new version"
    assert (tmp_path / "console/copy.txt").read_bytes() == b"copied version"
    assert not any(request.method == "DELETE" for request in server.requests)


@pytest.mark.asyncio
async def test_copy_without_overwrite_uses_atomic_destination_precondition(
    dav, monkeypatch, tmp_path
):
    from app.file_share.tests.local_file_transport import TemporaryFileTransport

    server, _, ctx = dav
    source = TemporaryFileTransport(tmp_path / "console")
    await source.file_write_text("source.txt", "source", overwrite=False)

    async def resolve_console(_ctx):
        return source

    monkeypatch.setattr(files, "_console_transport", resolve_console)
    server.race_on_put = b"PC contribution"
    with pytest.raises(FileExistsError):
        await files.resource_copy(ctx, "console://source.txt", "nextcloud://copy.txt")
    assert server.files["copy.txt"] == b"PC contribution"


@pytest.mark.asyncio
async def test_missing_etag_cannot_silently_disable_edit_protection(dav, monkeypatch):
    from app.file_share.resource_uri import ResourceValidationError

    _, adapter, ctx = dav
    calls = []

    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, content=b"original\n")

    monkeypatch.setattr(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    with pytest.raises(ResourceValidationError, match="ETag"):
        await files.resource_edit(
            ctx, "nextcloud://file.txt", start_line=1, end_line=1, content="replacement"
        )
    assert calls == ["GET"]


@pytest.mark.asyncio
async def test_metadata_budget_and_malformed_response_are_explicit_errors(dav, monkeypatch):
    from app.file_share.resource_uri import ResourceValidationError
    from bridge.nextcloud import file_share as module

    _, adapter, _ = dav
    monkeypatch.setattr(module, "_METADATA_LIMIT", 100)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(207, content=b"x" * 101))
        ),
    )
    with pytest.raises(ResourceValidationError, match="limit"):
        await adapter.resource_list("", recursive=False, limit=10)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(207, content=b"<html/>"))
        ),
    )
    with pytest.raises(ResourceValidationError, match="envelope"):
        await adapter.resource_list("", recursive=False, limit=10)


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["timeout", "cancel"])
async def test_interrupted_download_cleans_up_without_retry(
    dav, monkeypatch, tmp_path, interruption
):
    import asyncio
    from bridge.nextcloud import file_share as module

    _, adapter, _ = dav
    calls = []
    started = asyncio.Event()

    class WaitingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            started.set()
            await asyncio.Event().wait()

    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, stream=WaitingStream())

    monkeypatch.setattr(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    if interruption == "timeout":
        monkeypatch.setattr(module, "_REQUEST_SECONDS", 0.05)
    destination = tmp_path / "partial"
    task = asyncio.create_task(adapter.download_to("file.txt", destination))
    await asyncio.wait_for(started.wait(), timeout=1)
    if interruption == "cancel":
        task.cancel()
    with pytest.raises(TimeoutError if interruption == "timeout" else asyncio.CancelledError):
        await task
    assert calls == ["GET"]
    assert not destination.exists()


@pytest.mark.asyncio
async def test_ambiguous_upload_is_not_replayed(dav, monkeypatch, tmp_path):
    server, adapter, _ = dav
    original = server.handle

    async def handle(request):
        response = await original(request)
        if request.method == "PUT":
            raise httpx.ReadError("response lost after storing content")
        return response

    monkeypatch.setattr(
        adapter, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    source = tmp_path / "file.txt"
    source.write_bytes(b"new")
    with pytest.raises(httpx.ReadError):
        await adapter.upload_conditional(source, "file.txt", overwrite=False)
    assert server.files["file.txt"] == b"new"
    assert sum(request.method == "PUT" for request in server.requests) == 1


@pytest.mark.asyncio
async def test_share_accepts_confirmed_token_and_user_share(dav):
    server, adapter, _ = dav
    server.share_body["ocs"]["data"] = {"token": "synthetic-token"}
    assert await adapter.share("file.txt") == "https://cloud.example.test/cloud/s/synthetic-token"
    server.share_body["ocs"]["data"] = {"file_source": 123}
    assert (
        await adapter.share("file.txt", share_with="synthetic-recipient")
        == "https://cloud.example.test/cloud/index.php/f/123"
    )


@pytest.mark.asyncio
async def test_windows_line_endings_survive_read_edit_and_append(dav):
    server, _, ctx = dav
    server.put("windows.txt", b"one\r\ntwo\r\nthree\r\n")
    read = await files.resource_read(ctx, "nextcloud://windows.txt")
    assert read.content == "one\r\ntwo\r\nthree\r\n"
    await files.resource_edit(
        ctx, read.uri, start_line=2, end_line=2, content="updated", expected_etag=read.etag
    )
    await files.resource_append(ctx, read.uri, "last\r\n")
    assert server.files["windows.txt"] == b"one\r\nupdated\r\nthree\r\nlast\r\n"


@pytest.mark.asyncio
async def test_redirects_and_foreign_download_urls_never_receive_credentials(
    dav, monkeypatch, tmp_path
):
    from bridge.nextcloud import file_share as module

    _, adapter, _ = dav
    real_client = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://other.example.test/file.txt"})

    monkeypatch.delattr(adapter, "_client")
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(RuntimeError, match="302"):
        await adapter.download_to("file.txt", tmp_path / "file")
    with pytest.raises(ValueError, match="outside"):
        await adapter.download_to("https://other.example.test/file.txt", tmp_path / "file")
    assert calls == ["cloud.example.test"]
