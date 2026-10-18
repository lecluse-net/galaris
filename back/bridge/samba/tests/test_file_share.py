"""Synthetic SMB journeys through the canonical facade and a real Samba peer."""
import asyncio
import os
import threading
from contextlib import aclosing, contextmanager
from uuid import uuid4

import pytest

from app.file_share import (
    ResourceContext, ResourceRevisionConflict, ResourceValidationError, available_bridges,
    file_share_service, resource_service as files,
)
from app.tools import FileShareConfig
from app.tools.schemas import Tool
from bridge.samba.file_share import SambaFileClient
from bridge.samba import sdk


def test_bridge_discovery_and_connection_parameter_mapping():
    bridge = next(item for item in available_bridges() if item.service == "samba")
    assert not bridge.supports_share
    assert "recursive" in bridge.indexing_modes
    config = FileShareConfig(service="samba", base_url="smb://files.example.test/shared/team",
                            param_map={"login": "account", "password": "secret", "encrypt": "encrypted"})
    client = file_share_service.build_client(config, {"account": "SYNTHETIC\\writer", "secret": "synthetic", "encrypted": "true"})
    assert isinstance(client, SambaFileClient)
    assert (client.server, client.share, client.folder, client.username, client.encrypt) == (
        "files.example.test", "shared", "team", "SYNTHETIC\\writer", True)
    with pytest.raises(ValueError):
        file_share_service.build_client(config, {"account": "writer"})


@pytest.mark.parametrize("url", [
    "https://files.example.test/shared", "smb://", "smb://u:p@files.example.test/shared",
    "smb://files.example.test/shared/../other", "smb://files.example.test/shared/%2e%2e/other",
    "smb://files.example.test/shared?password=synthetic", "smb://files.example.test:0/shared",
    "smb://files.example.test/shared/%5cother", "smb://files.example.test/shared#other",
])
def test_reject_invalid_external_root_before_network(url):
    with pytest.raises(ResourceValidationError):
        SambaFileClient(url, "writer", "synthetic")


@pytest.mark.asyncio
async def test_invalid_tool_root_keeps_the_canonical_uri_in_error_guidance(monkeypatch):
    from types import SimpleNamespace
    from app.tools.tool_errors import classify_tool_failure

    tool = Tool(code="team-share", label="Synthetic share", file_share_config=FileShareConfig(
        service="samba", base_url="https://files.example.test",
        param_map={"login": "account", "password": "secret"},
    ))

    async def connections(agent_id):
        return [SimpleNamespace(active=True, tool_id=42)]

    async def get_tool(tool_id):
        return tool

    async def params(connection, **kwargs):
        return None, {"account": "writer", "secret": "synthetic"}

    def unexpected_network(*args, **kwargs):
        pytest.fail("Invalid configuration reached the SMB server")

    monkeypatch.setattr(file_share_service.connection_service, "get_connections_by_agent", connections)
    monkeypatch.setattr(file_share_service.tool_service, "get_tool_by_id", get_tool)
    monkeypatch.setattr(file_share_service.connection_service, "get_params_as_dict", params)
    monkeypatch.setattr(sdk, "session", unexpected_network)
    with pytest.raises(ResourceValidationError) as error:
        await files.resource_list(ResourceContext(agent_id=1, runtime="internal"), "team-share://")
    diagnostic = classify_tool_failure(error.value)
    assert diagnostic.kind == "actionable"
    assert "Tool configuration" in diagnostic.detail
    assert "base_url" in diagnostic.detail
    assert "existing share" in diagnostic.detail
    assert "Keep using" in diagnostic.detail and "code://" in diagnostic.detail
    assert "synthetic" not in diagnostic.detail


@pytest.mark.asyncio
async def test_server_root_discovers_shares_and_supports_normal_file_journey(monkeypatch):
    host = os.environ.get("SAMBA_TEST_SERVER")
    if not host:
        pytest.skip("Run make tests-samba for the isolated real SMB peer")
    client = SambaFileClient(f"smb://{host}/", "writer", "synthetic-writer-password", encrypt=True)
    reader = SambaFileClient(f"smb://{host}", "reader", "synthetic-reader-password", encrypt=True)
    async def resolve(agent_id, tool_code, locator="", **kwargs):
        assert tool_code == "team-share"
        return (reader if agent_id == 2 else client), "samba"
    monkeypatch.setattr(files, "resolve_resource_transport_with_service", resolve)
    ctx = ResourceContext(agent_id=1, runtime="internal")
    listing = await files.resource_list(ctx, "team-share://", max_entries=500)
    uris = {entry.uri for entry in listing.entries}
    assert {"team-share://synthetic/", "team-share://secondary/", "team-share://restricted/"} <= uris
    assert len(uris) == 35
    assert "team-share://IPC%24/" not in uris
    assert all(entry.is_collection for entry in listing.entries)
    assert (await files.resource_info(ctx, "team-share://")).is_collection
    reader_listing = await files.resource_list(ResourceContext(agent_id=2, runtime="internal"), "team-share://")
    assert "team-share://restricted/" not in {entry.uri for entry in reader_listing.entries}
    page = await files.resource_list(ctx, "team-share://", max_entries=1)
    assert page.truncated and page.next_cursor
    next_page = await files.resource_list(ctx, "team-share://", max_entries=1, cursor=page.next_cursor)
    assert next_page.entries[0].uri != page.entries[0].uri
    with pytest.raises(ResourceValidationError):
        await files.resource_list(ctx, "team-share://synthetic/", cursor=page.next_cursor)
    name = "server-root-" + uuid4().hex
    created = await files.resource_create(ctx, f"team-share://synthetic/{name}/", b"alpha\nbeta\n", name="résumé.txt")
    assert created.uri.startswith(f"team-share://synthetic/{name}/")
    current = await files.resource_read(ctx, created.uri)
    assert current.content == "alpha\nbeta\n"
    await files.resource_edit(ctx, created.uri, start_line=2, end_line=2, content="BETA", expected_etag=current.etag)
    assert (await files.resource_read(ctx, created.uri)).content == "alpha\nBETA\n"
    recursive = await files.resource_list(ctx, "team-share://synthetic/", recursive=True)
    assert created.uri in {entry.uri for entry in recursive.entries}
    moved = await files.resource_move(ctx, created.uri, f"team-share://secondary/{name}/moved.txt")
    assert (await files.resource_read(ctx, moved.uri)).content == "alpha\nBETA\n"
    with pytest.raises(FileNotFoundError):
        await files.resource_read(ctx, created.uri)
    await files.resource_delete(ctx, moved.uri)
    with pytest.raises(ResourceValidationError):
        await files.resource_create(ctx, "team-share://", b"no share creation", name="new-share")
    with pytest.raises(ResourceValidationError):
        await client.resource_delete("synthetic")
    with pytest.raises(ResourceValidationError):
        await client.resource_move("synthetic", "secondary", overwrite=False)
    read_only_source = await files.resource_create(ctx, f"team-share://secondary/{name}/", b"retained", name="read-only-source.txt")
    alias = f"team-share://volume-00/{name}/read-only-source.txt"
    copy_destination = f"team-share://synthetic/{name}/retained-copy.txt"
    with pytest.raises(ResourceValidationError, match="destination copy succeeded"):
        await files.resource_move(ctx, alias, copy_destination)
    assert (await files.resource_read(ctx, read_only_source.uri)).content == "retained"
    assert (await files.resource_read(ctx, copy_destination)).content == "retained"
    await files.resource_delete(ctx, read_only_source.uri)
    await files.resource_delete(ctx, copy_destination)
    with pytest.raises(PermissionError):
        await files.resource_info(ctx, "team-share://IPC%24/srvsvc")
    wrong = SambaFileClient(f"smb://{host}", "writer", "synthetic-wrong-password")
    with pytest.raises(PermissionError):
        await wrong.resource_list("", recursive=False, limit=50)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../escape", "a/../escape", "/absolute", "\\\\other\\share\\file", "a\\file", "file:stream", "file.", "file ", "a//b", "a/./b", "\x00file"])
async def test_reject_invalid_locator_before_network(path, tmp_path, monkeypatch):
    client = SambaFileClient("smb://files.example.test/shared", "writer", "synthetic")
    async def unexpected(*args):
        pytest.fail("Invalid locator reached the network")
    monkeypatch.setattr(client, "_run", unexpected)
    with pytest.raises(ResourceValidationError):
        await client.download_to(path, tmp_path / "content")


@pytest.mark.asyncio
async def test_stalled_peer_fails_within_budget_and_closes_connection(monkeypatch):
    closed = asyncio.Event()
    async def stalled(reader, writer):
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()
    server = await asyncio.start_server(stalled, "127.0.0.1", 0)
    monkeypatch.setattr(sdk, "_OPERATION_SECONDS", 0.2)
    port = server.sockets[0].getsockname()[1]
    client = SambaFileClient(f"smb://127.0.0.1:{port}/synthetic", "writer", "synthetic")
    async with server:
        with pytest.raises(OSError):
            await asyncio.wait_for(client.resource_info(""), timeout=2)
        await asyncio.wait_for(closed.wait(), timeout=2)


@pytest.fixture
def smb(monkeypatch):
    host = os.environ.get("SAMBA_TEST_SERVER")
    if not host:
        pytest.skip("Run make tests-samba for the isolated real SMB peer")
    client = SambaFileClient(f"smb://{host}/synthetic", "writer", "synthetic-writer-password", encrypt=True)
    reader = SambaFileClient(f"smb://{host}/synthetic", "reader", "synthetic-reader-password", encrypt=True)
    async def resolve(agent_id, tool_code, locator="", **kwargs):
        assert tool_code == "team-share"
        return (reader if agent_id == 2 else client), "samba"
    monkeypatch.setattr(files, "resolve_resource_transport_with_service", resolve)
    return client, reader, ResourceContext(agent_id=1, runtime="internal"), f"journey-{uuid4().hex}"


@pytest.mark.asyncio
async def test_large_video_seeks_to_tail_and_closing_releases_the_smb_handle(smb):
    client, _reader, ctx, folder = smb
    path = f"{folder}/Synthetic.mp4"
    uri = f"team-share://{path}"
    await files.resource_create(ctx, f"team-share://{folder}/", b"head", name="Synthetic.mp4")
    size = 3 * 1024**3

    def sparse_video(active):
        with active.open(client._unc(active, path), "r+b") as handle:
            handle.seek(size - 4)
            handle.write(b"tail")

    await client._run(sparse_video)
    assert (await files.resource_info(ctx, uri)).size == size
    assert b"".join([part async for part in files.resource_byte_range(ctx, uri, offset=size - 4, length=4)]) == b"tail"
    async with aclosing(files.resource_byte_range(ctx, uri, offset=0, length=size)) as chunks:
        assert (await anext(chunks))[:4] == b"head"
    # SMB's read handle denies deletion until its streaming owner closes it.
    await files.resource_delete(ctx, uri)


@pytest.mark.asyncio
async def test_canonical_file_journey_and_stale_versions(smb, tmp_path):
    client, reader, ctx, folder = smb
    root = f"team-share://{folder}/"
    created = await files.resource_create(ctx, root, b"alpha\nbeta\n", name="résumé 100%.txt")
    uri = created.uri
    assert uri == root + "r%C3%A9sum%C3%A9%20100%25.txt"
    with pytest.raises(FileExistsError):
        await files.resource_create(ctx, root, b"duplicate", name="résumé 100%.txt")
    listed = await files.resource_list(ctx, root)
    assert [entry.uri for entry in listed.entries] == [uri]
    assert {"edit", "append", "move", "delete"} <= set(listed.entries[0].capabilities)
    info = await files.resource_info(ctx, uri, include_checksum=True)
    assert info.checksum and info.etag
    read = await files.resource_read(ctx, uri)
    assert read.content == "alpha\nbeta\n" and read.etag == info.etag
    assert b"".join([chunk async for chunk in files.resource_byte_range(ctx, uri, offset=6, length=4)]) == b"beta"
    await files.resource_append(ctx, uri, "gamma\n", expected_etag=read.etag)
    with pytest.raises(ResourceRevisionConflict):
        await files.resource_write(ctx, uri, b"stale", expected_etag=read.etag)
    current = await files.resource_read(ctx, uri)
    with pytest.raises(ResourceRevisionConflict):
        await files.resource_delete(ctx, uri, expected_etag=read.etag)
    await files.resource_edit(ctx, uri, start_line=2, end_line=2, content="BETA", expected_etag=current.etag)
    assert (await files.resource_read(ctx, uri)).content == "alpha\nBETA\ngamma\n"
    found = await files.resource_search(ctx, root, "BETA", mode="text")
    assert [hit.resource.uri for hit in found.hits] == [uri]
    copy = await files.resource_copy(ctx, uri, root + "copy.txt")
    assert (await files.resource_read(ctx, copy.uri)).content == "alpha\nBETA\ngamma\n"
    moved = await files.resource_move(ctx, copy.uri, root + "moved.txt")
    with pytest.raises(FileNotFoundError):
        await files.resource_info(ctx, copy.uri)
    await files.resource_delete(ctx, moved.uri)
    with pytest.raises(FileNotFoundError):
        await files.resource_info(ctx, moved.uri)
    target = tmp_path / "content"
    with pytest.raises(ResourceValidationError):
        await client.download_to(f"{folder}/résumé 100%.txt", target, max_bytes=1)
    assert not target.exists()
    assert (await reader.resource_info(f"{folder}/résumé 100%.txt")).size > 0
    with pytest.raises(PermissionError):
        await files.resource_create(ResourceContext(agent_id=2, runtime="internal"), root, b"denied", name="denied.txt")
    assert (await files.resource_read(ctx, uri)).content == "alpha\nBETA\ngamma\n"
    wrong = SambaFileClient(f"smb://{client.server}/synthetic", "writer", "synthetic-wrong-password")
    with pytest.raises(PermissionError) as error:
        await wrong.resource_info(folder)
    assert "synthetic-wrong-password" not in str(error.value)


@pytest.mark.asyncio
async def test_pagination_scope_concurrent_create_and_subdirectory_root(smb, tmp_path):
    client, _reader, _ctx, folder = smb
    source = tmp_path / "source"
    source.write_bytes(b"synthetic")
    outcomes = await asyncio.gather(*[
        client.upload_conditional(source, "same.txt", target=folder, overwrite=False) for _ in range(2)
    ], return_exceptions=True)
    assert sum(isinstance(item, str) for item in outcomes) == 1, outcomes
    assert sum(isinstance(item, FileExistsError) for item in outcomes) == 1
    for name in ["a.txt", "sub/b.txt", "z.txt"]:
        parent, _, leaf = name.rpartition("/")
        await client.upload_conditional(source, leaf, target=f"{folder}/{parent}".rstrip("/"), overwrite=False)
    paths = []
    cursor = None
    while True:
        page = await client.resource_list_page(folder, recursive=True, limit=2, cursor=cursor)
        paths.extend(item.path for item in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert set(paths) == {f"{folder}/{name}" for name in ["a.txt", "same.txt", "sub", "sub/b.txt", "z.txt"]}
    assert len(paths) == len(set(paths))
    first = await client.resource_list_page(folder, recursive=False, limit=1)
    with pytest.raises(ResourceValidationError):
        await client.resource_list_page("", recursive=False, limit=1, cursor=first.next_cursor)
    await client.upload_conditional(source, "new.txt", target=folder, overwrite=False)
    with pytest.raises(ResourceRevisionConflict):
        await client.resource_list_page(folder, recursive=False, limit=1, cursor=first.next_cursor)
    rooted = SambaFileClient(f"smb://{client.server}/synthetic/{folder}/sub", "writer", "synthetic-writer-password")
    assert [entry.path for entry in (await rooted.resource_list("", recursive=True, limit=50)).entries] == ["b.txt"]
    with pytest.raises(ResourceValidationError):
        await rooted.resource_info("../a.txt")


@pytest.mark.asyncio
async def test_cancelled_download_drains_worker_and_removes_temporary(smb, tmp_path, monkeypatch):
    client, _reader, _ctx, folder = smb
    source = tmp_path / "source"
    source.write_bytes(b"synthetic interruption data")
    await client.upload_conditional(source, "input.txt", target=folder, overwrite=False)
    original_open = sdk.SmbSession.open
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    @contextmanager
    def delayed_open(active, path, mode, **kwargs):
        with original_open(active, path, mode, **kwargs) as handle:
            original_read = handle.read
            def read(count):
                loop.call_soon_threadsafe(started.set)
                assert release.wait(5), "The test did not release the SMB worker"
                return original_read(count)
            monkeypatch.setattr(handle, "read", read)
            yield handle

    monkeypatch.setattr(sdk.SmbSession, "open", delayed_open)
    destination = tmp_path / "download"
    pending = asyncio.create_task(client.download_to(f"{folder}/input.txt", destination))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not destination.exists()
    await client.download_to(f"{folder}/input.txt", destination)
    assert destination.read_bytes() == source.read_bytes()


@pytest.mark.asyncio
async def test_interrupted_creation_does_not_publish_partial_file(smb, tmp_path, monkeypatch):
    client, _reader, _ctx, folder = smb
    source = tmp_path / "source"
    source.write_bytes(b"x" * 100_000)
    original_open = sdk.SmbSession.open
    @contextmanager
    def failed_open(active, path, mode, **kwargs):
        with original_open(active, path, mode, **kwargs) as handle:
            original_write = handle.write
            written = False
            def write(chunk):
                nonlocal written
                if written:
                    raise ConnectionResetError("Synthetic SMB interruption")
                written = True
                return original_write(chunk)
            monkeypatch.setattr(handle, "write", write)
            yield handle
    monkeypatch.setattr(sdk.SmbSession, "open", failed_open)
    with pytest.raises(OSError):
        await client.upload_conditional(source, "partial.txt", target=folder, overwrite=False)
    with pytest.raises(FileNotFoundError):
        await client.resource_info(f"{folder}/partial.txt")
