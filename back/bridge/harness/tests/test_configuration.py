from io import StringIO
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy import select

from core.database import get_db_session
from core.params import Params, params_service, runtime_settings
from core.params.models import Param
from bridge.harness.manager import HarnessManager


@pytest_asyncio.fixture
async def administrator(client, monkeypatch):
    original = runtime_settings.model_dump()
    monkeypatch.setattr(params_service, "_cache_loaded", False)
    monkeypatch.setattr(params_service, "_params_cache", {})
    credentials = {"email": f"manager-{uuid4().hex}@example.com", "password": "Manager-test-password-123"}
    assert (await client.post('/api/auth/register', json=credentials)).status_code == 201
    login = await client.post('/api/auth/login-json', json=credentials)
    yield {"Authorization": f"Bearer {login.json()['access_token']}"}
    for name, value in original.items():
        setattr(runtime_settings, name, value)


@pytest.mark.asyncio
async def test_save_reload_preserve_secret_and_export_real_manager_environment(client, administrator):
    path = '/api/harness-manager'
    generated = await client.post(f'{path}/generate-secret', headers=administrator)
    assert generated.headers['cache-control'] == 'no-store'
    secret = generated.json()['secret']
    Fernet(secret.encode())
    manager = HarnessManager()
    response = await client.put(f'{path}/configuration', headers=administrator, json={
        'manager_url': 'https://manager.example.test/',
        'galaris_api_url': 'https://internal.example.test/api/', 'secret': secret,
    })
    assert response.status_code == 200
    assert secret not in response.text
    assert manager.base_url == 'https://manager.example.test'
    assert Fernet(secret.encode()).decrypt(manager._auth_headers()['X-Harness-Token'].encode()) == b'auth'
    async with get_db_session() as db:
        stored = await db.scalar(select(Param.value).where(Param.name == Params.HARNESS_MANAGER_SECRET))
        assert stored and stored != secret
        await params_service.refresh()
    assert runtime_settings.HARNESS_API_URL == 'https://internal.example.test/api'
    response = await client.put(f'{path}/configuration', headers=administrator, json={
        'manager_url': 'http://host.docker.internal:8485', 'galaris_api_url': '',
    })
    assert response.status_code == 200
    assert runtime_settings.HARNESS_MANAGER_SECRET == secret
    assert secret not in (await client.get(f'{path}/configuration', headers=administrator)).text
    assert secret not in (await client.get('/api/params', headers=administrator)).text
    exported = await client.post(f'{path}/environment', headers=administrator, json={
        'api_host': '192.0.2.5', 'api_port': 9000, 'allowed_ip': '192.0.2.10',
        'base_dir': '/srv/manager instances', 'ignore_dirs': 'backup,private',
    })
    assert exported.status_code == 200
    assert exported.headers['cache-control'] == 'no-store'
    parsed = dotenv_values(stream=StringIO(exported.text))
    assert parsed['HARNESS_MANAGER_SECRET'] == secret
    assert parsed['BASE_DIR'] == '/srv/manager instances'
    assert parsed['API_HOST'] == '192.0.2.5'
    assert parsed['API_PORT'] == '9000'
    assert parsed['ALLOWED_IP'] == '192.0.2.10'
    assert float(parsed['MAX_FILE_SIZE_MB']) * 1_048_576 == 1_000_000
    assert float(parsed['MAX_RAW_FILE_SIZE_MB']) * 1_048_576 == 512_000_000


@pytest.mark.asyncio
async def test_invalid_save_is_atomic_and_does_not_echo_secret(client, administrator):
    before = runtime_settings.model_dump()
    secret = 'invalid-private-value'
    response = await client.put('/api/harness-manager/configuration', headers=administrator, json={
        'manager_url': 'https://new.example.test', 'secret': secret,
    })
    assert response.status_code == 422
    assert secret not in response.text
    assert runtime_settings.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'base_dir': '/srv/data\nHARNESS_MANAGER_SECRET=injected'},
    {'base_dir': '/srv/${PRIVATE}'}, {'base_dir': 'relative'},
    {'update_url': 'https://galaris.test/${PRIVATE}'},
    {'update_url': 'https://galaris.test/`command`'},
    {'allowed_ip': '0.0.0.0/0'}, {'api_port': 0}, {'max_raw_file_size_mb': -1},
])
async def test_environment_refuses_invalid_or_injectable_fields(client, administrator, payload):
    for endpoint in ['environment', 'installation.zip']:
        response = await client.post(f'/api/harness-manager/{endpoint}', headers=administrator, json=payload)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_manager_configuration_and_secret_exports_require_privileges(client, administrator):
    from core.user import token_service
    from core.user.models import User

    async with get_db_session() as db:
        outsider = User(email=f'outsider-{uuid4().hex}@example.com', hashed_password='unused')
        db.add(outsider)
        await db.flush()
        _, token = await token_service.create_token_for_user(outsider.id)
    for headers, expected in [({}, 401), ({'Authorization': f'Bearer {token}'}, 403)]:
        for method, suffix, data in [
            ('GET', 'configuration', None), ('POST', 'generate-secret', None),
            ('POST', 'environment', {}), ('PUT', 'configuration', {'manager_url': 'https://host.test'}),
            ('GET', 'release', None), ('GET', 'release.zip', None), ('POST', 'installation.zip', {}),
        ]:
            response = await client.request(method, f'/api/harness-manager/{suffix}', headers=headers, json=data)
            assert response.status_code == expected
