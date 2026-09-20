from io import BytesIO, StringIO
import json
import time
from zipfile import ZipFile

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from bridge.harness import distribution
from core.params import runtime_settings
from bridge.harness.tests.test_configuration import administrator  # noqa: F401 -- authenticated integration fixture


def test_distribution_is_deterministic_and_excludes_local_files(tmp_path):
    for name in distribution.FILES:
        (tmp_path / name).write_text('[project]\nversion = "1.1.0"\n' if name == 'pyproject.toml' else name)
    (tmp_path / '.env').write_text('SECRET=must-not-ship')
    (tmp_path / '.local').mkdir()
    (tmp_path / '.local/private').write_text('private')
    release = distribution.build_release(source=tmp_path)
    assert release == distribution.build_release(source=tmp_path)
    with ZipFile(BytesIO(release.content)) as archive:
        assert set(archive.namelist()) == {f'harness_manager/{name}' for name in distribution.FILES}
        assert b'must-not-ship' not in b''.join(archive.read(name) for name in archive.namelist())
    (tmp_path / 'main.py').unlink()
    (tmp_path / 'main.py').symlink_to(tmp_path / '.env')
    with pytest.raises(ValueError):
        distribution.build_release(source=tmp_path)


@pytest.mark.asyncio
async def test_installation_zip_contains_saved_configuration_while_source_and_updates_never_do(client, administrator, monkeypatch):
    secret = Fernet.generate_key().decode()
    monkeypatch.setattr(runtime_settings, 'HARNESS_MANAGER_SECRET', secret)
    cipher = Fernet(secret.encode())
    manifest = await client.get('/api/harness-manager/release', headers=administrator)
    assert manifest.status_code == 200
    assert manifest.json()['version'] == distribution.source_version()
    source = await client.get('/api/harness-manager/release.zip', headers=administrator)
    assert source.status_code == 200
    installation = await client.post('/api/harness-manager/installation.zip', headers=administrator, json={
        'base_dir': '/srv/agent instances', 'api_port': 9090,
        'update_url': 'https://galaris.private/api/harness-manager/updates',
    })
    assert installation.status_code == 200
    assert installation.headers['cache-control'] == 'no-store'
    assert 'attachment;' in installation.headers['content-disposition']
    with ZipFile(BytesIO(installation.content)) as archive:
        env = dotenv_values(stream=StringIO(archive.read('harness_manager/.env').decode()))
        assert env['HARNESS_MANAGER_SECRET'] == secret
        assert env['BASE_DIR'] == '/srv/agent instances'
        assert env['API_PORT'] == '9090'
        assert env['GALARIS_UPDATE_URL'] == 'https://galaris.private/api/harness-manager/updates'
        assert archive.getinfo('harness_manager/.env').external_attr >> 16 & 0o777 == 0o600
    headers = {'X-Harness-Token': cipher.encrypt(b'galaris-harness-update').decode()}
    signed = await client.get('/api/harness-manager/updates/manifest', headers=headers)
    assert signed.status_code == 200
    decoded = json.loads(cipher.decrypt(signed.content, ttl=300))
    assert decoded == manifest.json()
    update = await client.get(f"/api/harness-manager/updates/archive/{decoded['sha256']}.zip", headers=headers)
    assert update.content == source.content
    with ZipFile(BytesIO(update.content)) as archive:
        assert 'harness_manager/.env' not in archive.namelist()
        assert secret.encode() not in b''.join(archive.read(name) for name in archive.namelist())
    assert (await client.get('/api/harness-manager/updates/archive/obsolete.zip', headers=headers)).status_code == 409


@pytest.mark.asyncio
async def test_update_machine_auth_is_scoped_time_limited_and_never_replaced_by_user_auth(client, administrator, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setattr(runtime_settings, 'HARNESS_MANAGER_SECRET', key.decode())
    cipher = Fernet(key)
    tokens = ['', 'garbage', cipher.encrypt(b'auth').decode(),
              cipher.encrypt_at_time(b'galaris-harness-update', int(time.time()) - 120).decode(),
              Fernet(Fernet.generate_key()).encrypt(b'galaris-harness-update').decode()]
    for token in tokens:
        for path in ['manifest', 'archive/anything.zip']:
            response = await client.get('/api/harness-manager/updates/' + path,
                headers={**administrator, 'X-Harness-Token': token})
            assert response.status_code == 401
            assert key.decode() not in response.text
