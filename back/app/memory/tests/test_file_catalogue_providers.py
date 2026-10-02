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
async def test_nextcloud_catalogue_pagination_recovery_and_permission_revocation(db, agents, memory_storage, monkeypatch):
    owner, peer = agents
    server = DavServer()
    for index in range(503):
        server.put(f'item-{index:04d}.txt', b'Synthetic DAV data')
    adapter = NextcloudFileClient('https://cloud.example.test/cloud', 'synthetic', 'synthetic')
    monkeypatch.setattr(adapter, '_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
    async def resolve(*_args, **_kwargs):
        return adapter, 'nextcloud'
    monkeypatch.setattr(resource_service, 'resolve_resource_transport_with_service', resolve)
    monkeypatch.setattr(file_share_service, 'resolve_resource_transport_with_service', resolve)
    monkeypatch.setattr(catalogue, 'resolve_resource_transport_with_service', resolve)
    tool = ToolModel(code='dav-proof', label='Synthetic DAV', file_share_config={'service': 'nextcloud', 'base_url': 'https://cloud.example.test/cloud'},
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
    server.forced_status = 403
    assert await hits(owner.id, 'item-0000') == []
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))
