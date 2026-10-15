"""Exercise the public Console transport and code-server adapter on a prepared target."""

import asyncio
from uuid import uuid4

import asyncssh
import httpx
from pydantic import SecretStr

import main as application_bootstrap  # noqa: F401 -- use the application's module composition

from app.console import SshConnectionConfig, code_runtime_tunnel, discover_repository
from bridge.code_server.adapter import CodeServerRuntime


async def main():
    async with httpx.AsyncClient(trust_env=False) as client:
        data = (await client.get('http://fixture:8766/test/status')).json()
    config = SshConnectionConfig(connection_id=1, host='fixture', port=2222,
        username='developer', private_key=SecretStr(data['transport_key']),
        known_host_key=data['host_key'], code_runtime_port=8766,
        code_runtime_token=SecretStr(data['token']))
    target = await discover_repository(config, 'project')
    assert target.root == '/home/developer/project'
    assert target.branch == 'main' and target.root_identity
    async def configuration(connection_id: int) -> SshConnectionConfig:
        assert connection_id == config.connection_id
        return config
    adapter = CodeServerRuntime(configuration)
    reference = await adapter.connection(config.connection_id)
    validated = await adapter.discover(reference, 'project')
    for mode in ('edit', 'read'):
        identifier = uuid4()
        try:
            await adapter.open(reference, validated, identifier, mode)
            async with adapter.endpoint(reference) as endpoint:
                assert endpoint.url.startswith('http://127.0.0.1:')
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(endpoint.url + f'/sessions/{identifier}/editor/healthz',
                        headers={'Authorization': 'Bearer ' + endpoint.credential})
                    assert response.status_code == 200
            await adapter.touch(reference, identifier)
        finally:
            await adapter.close(reference, identifier, discard=True)
    wrong_key = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode()
    wrong = config.model_copy(update={'known_host_key': wrong_key})
    try:
        await discover_repository(wrong, 'project')
    except asyncssh.HostKeyNotVerifiable:
        pass
    else:
        raise AssertionError('A changed SSH host key was accepted')
    unprepared = config.model_copy(update={'code_runtime_port': None})
    try:
        async with code_runtime_tunnel(unprepared):
            raise AssertionError('An unprepared Console was accepted')
    except RuntimeError:
        pass
    for port in (8767, 8768):
        # 8767 is permitted but has no IDE; 8768 is rejected by PermitOpen.
        unavailable = config.model_copy(update={'code_runtime_port': port})
        try:
            async with code_runtime_tunnel(unavailable) as url:
                async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
                    await client.get(url + '/sessions/unavailable/editor/')
        except (httpx.HTTPError, asyncssh.Error, OSError):
            pass
        else:
            raise AssertionError(f'An unavailable external IDE was accepted on port {port}')
    async with code_runtime_tunnel(config) as url:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            assert (await client.get(url + '/test/status')).status_code == 200
            await client.post('http://fixture:8766/test/interrupt-ssh')
            try:
                await client.get(url + '/test/status')
            except (httpx.HTTPError, asyncssh.Error, OSError):
                pass
            else:
                raise AssertionError('A cut tunnel continued accepting requests')
    identifier = uuid4()
    async with httpx.AsyncClient(trust_env=False) as client:
        await client.post('http://fixture:8766/test/replace')
        try:
            replacement = await discover_repository(config, 'project')
            assert replacement.generation != target.generation
            try:
                await adapter.open(reference, validated, identifier, 'edit')
            except RuntimeError:
                pass
            else:
                raise AssertionError('A replaced checkout was mounted with a stale identity')
        finally:
            await client.post('http://fixture:8766/test/replace?restore=true')
            await adapter.close(reference, identifier, discard=True)
    print('Prepared external Console: pinned SSH, shared edit/read checkout, changed target, absent IDE and refused forwarding passed')


if __name__ == '__main__':
    asyncio.run(main())
