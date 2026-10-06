"""Catalogue workflows through production adapters and isolated protocol peers."""

from datetime import datetime, timezone
import asyncssh
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.connection import Connection
from app.tools import ToolModel
from app.console.contracts import SshConnectionConfig
from app.console.ssh_client import SshExecutionTransport
from app.console.file_transport import SshAgentFileTransport
from app.file_share import resource_service, file_share_service, catalogue
from app.file_share.resource_contracts import ResourceContext
from app.file_share.models import FileCatalogEntry
from app.file_share.indexing import start_index_run, indexing_tick, refresh_known_tick
from bridge.nextcloud.file_share import NextcloudFileClient
from bridge.nextcloud.tests.test_file_share import DavServer
from .test_file_catalogue import hits


@pytest.mark.asyncio
async def test_console_catalogue_over_real_ssh_sftp(db, agents, memory_storage, tmp_path, monkeypatch):
    owner, peer = agents
    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False
    host_key = asyncssh.generate_private_key('ssh-ed25519')
    client_key = asyncssh.generate_private_key('ssh-ed25519')
    remote_home = tmp_path / 'home'
    remote_home.mkdir()
    async def home(process):
        assert process.command == 'printf \'%s\' "$HOME"'
        process.stdout.write('/home')
        process.exit(0)
    listener = await asyncssh.create_server(Server, '127.0.0.1', 0,
        server_host_keys=[host_key], process_factory=home,
        sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(tmp_path)))
    execution = SshExecutionTransport(SshConnectionConfig(connection_id=1, host='127.0.0.1',
        port=listener.get_port(), username='synthetic', private_key=SecretStr(client_key.export_private_key().decode()),
        known_host_key=host_key.export_public_key().decode().strip()))
    transport = SshAgentFileTransport(execution)
    async def resolve(_ctx):
        return transport
    monkeypatch.setattr(resource_service, '_console_transport', resolve)
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'console'))
    tool.global_params = {'tools.fileindexing': {'value': 'known_uris', 'forced': False}}
    db.add(Connection(agent_id=owner.id, tool_id=tool.id))
    await db.commit()
    ctx = ResourceContext(agent_id=owner.id, runtime='internal', console_resource=object())
    try:
        result = await resource_service.resource_write_text(ctx, 'console://qualification.txt', 'Synthetic SFTP data')
        assert result.indexing_status == 'indexed'
        assert len(await hits(owner.id, 'qualification')) == 1
        assert await hits(peer.id, 'qualification') == []
        (remote_home / 'qualification.txt').write_text('Synthetic externally changed content')
        await refresh_known_tick()
        entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == result.uri))
        assert entry.descriptor['size'] == len('Synthetic externally changed content')
        (remote_home / 'qualification.txt').unlink()
        assert await hits(owner.id, 'qualification') == []
    finally:
        await execution.close()
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("response_encoding", [None, "gzip", "deflate"])
async def test_nextcloud_catalogue_pagination_recovery_and_permission_revocation(db, agents, memory_storage, monkeypatch, response_encoding):
    owner, peer = agents
    server = DavServer()
    server.response_encoding = response_encoding
    for index in range(503):
        server.put(f'item-{index:04d}.txt', b'Synthetic DAV data')
    adapter = NextcloudFileClient('https://cloud.example.test/cloud', 'synthetic', 'synthetic')
    monkeypatch.setattr(adapter, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
    resolutions = 0
    async def resolve(*_args, **_kwargs):
        nonlocal resolutions
        resolutions += 1
        return adapter, 'nextcloud'
    monkeypatch.setattr(resource_service, 'resolve_resource_transport_with_service', resolve)
    monkeypatch.setattr(file_share_service, 'resolve_resource_transport_with_service', resolve)
    monkeypatch.setattr(catalogue, 'resolve_resource_transport_with_service', resolve)
    tool = ToolModel(code='dav-proof', label='Synthetic DAV', file_share_config={'service': 'nextcloud', 'base_url': 'https://cloud.example.test/cloud'},
        messenger_config={'service': 'nextcloud_talk'},
        global_params={'tools.fileindexing': {'value': 'recursive', 'forced': False}})
    db.add(tool)
    await db.flush()
    db.add(Connection(agent_id=owner.id, tool_id=tool.id))
    await db.commit()
    ctx = ResourceContext(agent_id=owner.id, runtime='internal')
    run = await start_index_run(ctx, 'dav-proof://')
    await db.commit()
    await indexing_tick()
    await db.refresh(run)
    assert run.scanned == 500 and run.status == 'running'
    server.forced_status = 503
    await indexing_tick()
    await db.refresh(run)
    assert run.status == 'retry'
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))
    server.forced_status = None
    run.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()
    await indexing_tick()
    await db.refresh(run)
    assert run.status == 'success' and run.scanned == 503
    assert len(await hits(owner.id, 'item-0000')) == 1
    assert await hits(peer.id, 'item-0000') == []
    from app.memory import service
    from app.memory.schemas import MemoryGraphRootsRequest
    request = MemoryGraphRootsRequest(agent_id=owner.id, limit=100)
    resolutions = 0
    page = await service.list_graph_roots(request)
    assert len(page.nodes) == 100 and page.has_more
    assert resolutions <= 2
    assert not (await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=peer.id))).nodes
    server.forced_status = 403
    assert await hits(owner.id, 'item-0000') == []
    assert not (await service.list_graph_roots(request)).nodes
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))


@pytest.mark.asyncio
async def test_hybrid_graph_keeps_room_authorization_separate_from_file_batches(db, agents, memory_storage, monkeypatch):
    from app.file_share.resource_contracts import ResourceDescriptor
    from app.messenger import messenger_known_room_locators
    from app.messenger.models import Room
    owner, peer = agents
    tool = ToolModel(code='hybrid-proof', label='Synthetic hybrid',
        file_share_config={'service': 'nextcloud', 'base_url': 'https://cloud.example.test/cloud'},
        messenger_config={'service': 'nextcloud_talk'})
    db.add(tool)
    await db.flush()
    connection = Connection(agent_id=owner.id, tool_id=tool.id)
    other = Connection(agent_id=peer.id, tool_id=tool.id)
    db.add_all([connection, other])
    await db.flush()
    db.add_all([
        Room(connection_id=connection.id, external_id='talk-token', label='Synthetic room', conversation_type='text'),
        Room(connection_id=other.id, external_id='files', label='Other synthetic room', conversation_type='text'),
        Room(connection_id=connection.id, external_id='removed-room', label='Removed synthetic room',
            conversation_type='text', deleted_at=datetime.now(timezone.utc)),
    ])
    await db.commit()
    assert await messenger_known_room_locators(connection.id, [' talk-token ', 'files', 'removed-room', '']) == {'talk-token'}
    assert await messenger_known_room_locators(other.id, ['talk-token', 'files']) == {'files'}
    server = DavServer()
    paths = ['files/a.txt', 'files/b.txt', 'talk-token/a.txt', 'talk-token/b.txt', 'talk-token /c.txt']
    for path in paths:
        server.put(path, b'Synthetic bytes')
    adapter = NextcloudFileClient('https://cloud.example.test/cloud', 'synthetic', 'synthetic')
    monkeypatch.setattr(adapter, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
    checked = []
    class DeniedRoom:
        async def resource_info(self, path, **_kwargs):
            checked.append(path)
            raise PermissionError('Synthetic room access revoked')
    async def resolve(_agent, _scheme, locator, **_kwargs):
        return (DeniedRoom(), 'messenger') if locator.split('/', 1)[0].strip() == 'talk-token' else (adapter, 'nextcloud')
    monkeypatch.setattr(catalogue, 'resolve_resource_transport_with_service', resolve)
    monkeypatch.setattr(resource_service, 'resolve_resource_transport_with_service', resolve)
    ctx = ResourceContext(agent_id=owner.id, runtime='internal')
    scope = await catalogue.observation_scope(ctx, 'hybrid-proof://files/a.txt')
    assert scope is not None
    await catalogue.observe_descriptors(scope, [ResourceDescriptor(uri=f'hybrid-proof://{path}', name=path.rsplit('/', 1)[-1]) for path in paths])
    await db.commit()
    entries = list(await db.scalars(select(FileCatalogEntry)))
    readable = await catalogue.catalogue_sources_readable([entry.memory_node_id for entry in entries], owner.id)
    assert readable == {entry.memory_node_id for entry in entries if entry.uri.startswith('hybrid-proof://files/')}
    assert set(checked) == {'talk-token/a.txt', 'talk-token/b.txt', 'talk-token /c.txt'}
