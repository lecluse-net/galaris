"""Closed-network fixture for the actual IDE and prepared external SSH transport.

Never included in the production image. Every file, key and repository is synthetic.
"""

import os
from pathlib import Path
import subprocess
import shutil
import signal
from uuid import uuid4

from aiohttp import ClientSession, web
import runtime

HOME = Path('/home/developer')
REPOSITORY = HOME / 'project'
TOKEN = 'synthetic-code-runtime-token-for-qualification-only'
SESSION = str(uuid4())
ssh_server = None


def initialize():
    global ssh_server
    REPOSITORY.mkdir(parents=True, exist_ok=True)
    (REPOSITORY / 'source.txt').write_text('synthetic agent version\n')
    (REPOSITORY / 'README.md').write_text('# Synthetic native preview\n\nSynthetic Markdown webview content.\n')
    for arguments in (["git", "init", "-b", "main", str(REPOSITORY)],
                      ["git", "-C", str(REPOSITORY), "config", "user.name", "Synthetic developer"],
                      ["git", "-C", str(REPOSITORY), "config", "user.email", "developer@example.test"],
                      ["git", "-C", str(REPOSITORY), "add", "."],
                      ["git", "-C", str(REPOSITORY), "commit", "-m", "Synthetic initial"]):
        subprocess.run(arguments, check=True, capture_output=True)
    fixture = Path('/tmp/code-fixture')
    fixture.mkdir()
    for name in ('client', 'host'):
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(fixture / name)], check=True)
    (fixture / 'authorized_keys').write_text((fixture / 'client.pub').read_text())
    for directory, children, files in os.walk(HOME):
        os.chown(directory, 20000, 20000)
        for name in children + files:
            os.chown(Path(directory) / name, 20000, 20000)
    Path('/run/sshd').mkdir(exist_ok=True)
    config = fixture / 'sshd_config'
    config.write_text(f'Port 2222\nHostKey {fixture}/host\nAuthorizedKeysFile {fixture}/authorized_keys\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\nAllowUsers developer\nAllowTcpForwarding local\nPermitOpen 127.0.0.1:8766 127.0.0.1:8767\nSubsystem sftp internal-sftp\n')
    ssh_server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(config)], start_new_session=True)
    Path('/run/galaris-code').mkdir()
    Path('/run/galaris-code/token').write_text(TOKEN)
    runtime.HOME_ROOT = Path('/home')


async def open_session(request):
    async with ClientSession() as client:
        async with client.post('http://127.0.0.1:8766/sessions', headers={'Authorization': 'Bearer ' + TOKEN}, json={
                'session': SESSION, 'home': str(HOME), 'root': str(REPOSITORY),
                'git_paths': [str(REPOSITORY / '.git')], 'mode': 'edit',
                'root_identity': f'{REPOSITORY.stat().st_dev}:{REPOSITORY.stat().st_ino}',
                'git_identities': [f'{(REPOSITORY / ".git").stat().st_dev}:{(REPOSITORY / ".git").stat().st_ino}']}) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(text=await response.text())
    return web.json_response({'session': SESSION, 'url': f'/sessions/{SESSION}/editor/'})


async def mutate(request):
    data = await request.json()
    (REPOSITORY / 'source.txt').write_text(data['text'])
    return web.json_response({'state': 'written'})


async def stage(request):
    subprocess.run(['git', '-c', f'safe.directory={REPOSITORY}', '-C', str(REPOSITORY), 'add', 'source.txt'], check=True, capture_output=True)
    return web.json_response({'state': 'staged'})


async def replace_target(request):
    backup = HOME / 'synthetic-original-checkout'
    if request.query.get('restore') == 'true':
        shutil.rmtree(REPOSITORY)
        backup.rename(REPOSITORY)
    else:
        REPOSITORY.rename(backup)
        shutil.copytree(backup, REPOSITORY)
        for directory, children, files in os.walk(REPOSITORY):
            os.chown(directory, 20000, 20000)
            for name in children + files:
                os.chown(Path(directory) / name, 20000, 20000)
    return web.json_response({'state': 'replaced'})


async def interrupt_ssh(request):
    global ssh_server
    # This container has its own PID namespace and only synthetic SSH connections.
    for process in Path('/proc').iterdir():
        if process.name.isdigit():
            try:
                if (process / 'comm').read_text().strip() in ('sshd', 'sshd-session'):
                    os.kill(int(process.name), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    ssh_server.wait(timeout=5)
    ssh_server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', '/tmp/code-fixture/sshd_config'], start_new_session=True)
    return web.json_response({'state': 'interrupted'})


async def status(request):
    return web.json_response({'text': (REPOSITORY / 'source.txt').read_text(),
        'host_key': Path('/tmp/code-fixture/host.pub').read_text(),
        'transport_key': Path('/tmp/code-fixture/client').read_text(),
        'token': TOKEN, 'session': SESSION})


async def metrics(request):
    # Aggregate fixture measurements only: no identifiers, keys or source content.
    cgroup = Path('/sys/fs/cgroup')
    return web.json_response({'runtime_sessions': len(runtime.editors),
        'memory_bytes': int((cgroup / 'memory.current').read_text()),
        'cpu_microseconds': int(dict(line.split() for line in (cgroup / 'cpu.stat').read_text().splitlines())['usage_usec'])})


@web.middleware
async def synthetic_browser_access(request, handler):
    if request.path.startswith('/test/'):
        return await handler(request)
    headers = dict(request.headers)
    headers['Authorization'] = 'Bearer ' + TOKEN
    headers.setdefault('X-Forwarded-Host', request.host)
    headers.setdefault('X-Forwarded-Proto', 'http')
    return await runtime.authenticate(request.clone(headers=headers), handler)


def main():
    initialize()
    app = web.Application(middlewares=[synthetic_browser_access])
    app.cleanup_ctx.append(runtime.lifetime)
    app.router.add_get('/test/status', status)
    app.router.add_get('/test/metrics', metrics)
    app.router.add_post('/test/open', open_session)
    app.router.add_post('/test/write', mutate)
    app.router.add_post('/test/stage', stage)
    app.router.add_post('/test/replace', replace_target)
    app.router.add_post('/test/interrupt-ssh', interrupt_ssh)
    app.router.add_post('/sessions', runtime.open_editor)
    app.router.add_delete('/sessions/{session}', runtime.close_editor)
    app.router.add_post('/sessions/{session}/touch', runtime.touch_editor)
    app.router.add_post('/sessions/{session}/navigate', runtime.navigate)
    app.router.add_route('*', '/sessions/{session}/editor/{path:.*}', runtime.proxy)
    web.run_app(app, port=8766, access_log=None)


if __name__ == '__main__':
    main()
