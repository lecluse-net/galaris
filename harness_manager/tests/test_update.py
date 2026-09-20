from __future__ import annotations

import fcntl
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import stat
import subprocess
from zipfile import ZipFile, ZipInfo

from cryptography.fernet import Fernet, InvalidToken
import pytest

spec = importlib.util.spec_from_file_location('manager_updater', Path(__file__).parents[1] / 'update.py')
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def archive(version='1.1.0', extra=None, symlink=False):
    result = BytesIO()
    with ZipFile(result, 'w') as zipped:
        for name in updater.FILES:
            content = (Path(__file__).parents[1] / name).read_bytes()
            if name == 'pyproject.toml':
                content = f'[project]\nversion = "{version}"\n'.encode()
            info = ZipInfo(f'harness_manager/{name}')
            info.external_attr = ((stat.S_IFLNK if symlink and name == 'main.py' else stat.S_IFREG) | 0o644) << 16
            zipped.writestr(info, content)
        if extra:
            zipped.writestr(extra, b'private')
    return result.getvalue()


@pytest.mark.parametrize('extra,symlink', [('../outside', False), ('harness_manager/.env', False),
    ('harness_manager/main.py', False), (None, True)])
def test_archive_rejects_paths_credentials_duplicates_and_symlinks(tmp_path, extra, symlink):
    with pytest.raises(updater.UpdateError):
        updater.unpack(archive(extra=extra, symlink=symlink), '1.1.0', tmp_path)
    assert not (tmp_path / '.env').exists()


def test_archive_checks_declared_version_before_installing(tmp_path):
    with pytest.raises(updater.UpdateError, match='version'):
        updater.unpack(archive('1.0.0'), '1.1.0', tmp_path)


def test_download_requires_signed_manifest_and_matching_content(monkeypatch):
    cipher = Fernet(Fernet.generate_key())
    content = archive()
    manifest = cipher.encrypt(json.dumps({'version': '1.1.0', 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}).encode())
    requests = []
    def fetch(url, _cipher, limit):
        requests.append((url, limit))
        return manifest if url.endswith('/manifest') else content
    monkeypatch.setattr(updater, 'fetch', fetch)
    assert updater.download('https://galaris.test/api/harness-manager/updates', cipher) == ('1.1.0', content)
    assert requests[1][0].endswith(f'/archive/{hashlib.sha256(content).hexdigest()}.zip')
    content += b'tampered'
    with pytest.raises(updater.UpdateError, match='checksum'):
        updater.download('https://galaris.test/api/harness-manager/updates', cipher)
    with pytest.raises(InvalidToken):
        updater.download('https://galaris.test/api/harness-manager/updates', Fernet(Fernet.generate_key()))
    with pytest.raises(updater.UpdateError):
        updater.download('https://user:secret@galaris.test/updates', cipher)


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / 'manager'
    root.mkdir()
    (root / '.local').mkdir()
    updater.unpack(archive('1.0.0'), '1.0.0', root)
    (root / '.env').write_text('HARNESS_MANAGER_SECRET=private\nBASE_DIR=/srv/instances\n')
    (root / '.env').chmod(0o600)
    (root / '.local/untouched').write_text('local environment')
    (root / 'instances/agent').mkdir(parents=True)
    (root / 'instances/agent/data').write_text('agent data')
    staged = tmp_path / 'staged'
    staged.mkdir()
    updater.unpack(archive(), '1.1.0', staged)
    return root, staged


@pytest.mark.parametrize('mode', [None, 'background', 'systemd'])
def test_update_preserves_configuration_instances_and_local_state_and_restarts_only_running_service(installation, monkeypatch, mode):
    root, staged = installation
    commands = []
    monkeypatch.setattr(updater, 'running_mode', lambda _: mode)
    monkeypatch.setattr(updater, 'command', lambda _root, *args, **kw: commands.append(args))
    checked = []
    monkeypatch.setattr(updater, 'verify_running', lambda _root, version, cipher: checked.append(version))
    backup = updater.apply(root, staged, '1.1.0', Fernet(Fernet.generate_key()))
    assert updater.installed_version(root) == '1.1.0'
    assert updater.installed_version(backup) == '1.0.0'
    assert (root / '.env').read_text().startswith('HARNESS_MANAGER_SECRET=private')
    assert stat.S_IMODE((root / '.env').stat().st_mode) == 0o600
    assert (root / '.local/untouched').read_text() == 'local environment'
    assert (root / 'instances/agent/data').read_text() == 'agent data'
    assert ('make', 'install') in commands
    assert checked == (['1.1.0'] if mode else [])
    assert len(commands) == (3 if mode else 1)


@pytest.mark.parametrize('failure', ['install', 'health'])
def test_failed_update_restores_code_and_reinstalls_old_environment(installation, monkeypatch, failure):
    root, staged = installation
    old = {name: (root / name).read_bytes() for name in updater.FILES}
    monkeypatch.setattr(updater, 'running_mode', lambda _: 'background')
    installs = []
    def command(_root, *args, **kw):
        if args == ('make', 'install'):
            installs.append(updater.installed_version(root))
            if failure == 'install' and len(installs) == 1:
                raise subprocess.CalledProcessError(1, args)
    def health(_root, version, cipher):
        if failure == 'health' and version == '1.1.0':
            raise updater.UpdateError('Unhealthy')
    monkeypatch.setattr(updater, 'command', command)
    monkeypatch.setattr(updater, 'verify_running', health)
    with pytest.raises(updater.UpdateError, match='previous version restored'):
        updater.apply(root, staged, '1.1.0', Fernet(Fernet.generate_key()))
    assert installs == ['1.1.0', '1.0.0']
    assert {name: (root / name).read_bytes() for name in updater.FILES} == old
    assert (root / 'instances/agent/data').read_text() == 'agent data'
    assert (root / '.env').read_text().startswith('HARNESS_MANAGER_SECRET=private')


def test_same_version_and_downgrade_never_change_files_and_concurrent_updates_are_rejected(installation, monkeypatch):
    root, _ = installation
    monkeypatch.setattr(updater, '__file__', str(root / 'update.py'))
    monkeypatch.setenv('HARNESS_MANAGER_SECRET', Fernet.generate_key().decode())
    monkeypatch.setenv('GALARIS_UPDATE_URL', 'https://galaris.test/api/harness-manager/updates')
    monkeypatch.setattr(updater, 'download', lambda *_: ('1.0.0', archive('1.0.0')))
    assert updater.main() == 0
    monkeypatch.setattr(updater, 'download', lambda *_: ('0.9.0', archive('0.9.0')))
    with pytest.raises(updater.UpdateError, match='downgrade'):
        updater.main()
    assert updater.installed_version(root) == '1.0.0'
    with (root / '.local/update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(updater.UpdateError, match='Another manager update'):
            updater.main()
