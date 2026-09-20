"""Administrators change operation limits durably without restarting services."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.database import get_db_session
from core.params import params_service, runtime_settings
from core.rate_limit import limiter


@pytest_asyncio.fixture
async def administrator(client, monkeypatch):
    original = runtime_settings.model_dump()
    monkeypatch.setattr(params_service, "_cache_loaded", False)
    monkeypatch.setattr(params_service, "_params_cache", {})
    async with get_db_session():
        await params_service.refresh()
    email = f"preferences-{uuid4().hex}@example.com"
    credentials = {"email": email, "password": "Preferences-test-password-123"}
    assert (await client.post('/api/auth/register', json=credentials)).status_code == 201
    login = await client.post('/api/auth/login-json', json=credentials)
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    yield headers
    for name, value in original.items():
        setattr(runtime_settings, name, value)
    limiter.reset()


@pytest.mark.asyncio
async def test_public_registration_can_be_opened_and_closed_without_granting_privileges(client, administrator):
    from httpx import ASGITransport, AsyncClient
    from main import app

    path = '/api/params/ALLOW_USER_REGISTRATION'
    assert (await client.get('/api/auth/registration-status')).json() == {'registration_open': False, 'initial_admin_required': False}
    assert (await client.put(path, json={'value': 'true'})).status_code == 401
    assert (await client.put(path, json={'value': 'true'}, headers=administrator)).status_code == 200
    async with get_db_session():
        await params_service.refresh()
    assert runtime_settings.ALLOW_USER_REGISTRATION is True
    assert (await client.get('/api/auth/registration-status')).json() == {'registration_open': True, 'initial_admin_required': False}

    # Visitors use a separate browser: changing accounts in the administrator's
    # browser intentionally revokes its previous session.
    async with AsyncClient(transport=ASGITransport(app=app), base_url=client.base_url) as visitor:
        credentials = {'email': 'public-user@example.com', 'password': 'Public-user-password-123'}
        registered = await visitor.post('/api/auth/register', json={**credentials, 'is_active': False, 'role_code': 'admin'})
        assert registered.status_code == 201
        assert registered.json()['is_active'] is True
        assert (await visitor.post('/api/auth/register', json=credentials)).status_code == 400
        login = await visitor.post('/api/auth/login-json', json=credentials)
        assert login.status_code == 200
        headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
        assert (await visitor.get('/api/authorize/my-privileges', headers=headers)).json() == []
        assert (await visitor.put(path, json={'value': 'false'}, headers=headers)).status_code == 403

        assert (await client.put(path, json={'value': 'false'}, headers=administrator)).status_code == 200
        assert (await visitor.get('/api/auth/registration-status')).json() == {'registration_open': False, 'initial_admin_required': False}
        assert (await visitor.post('/api/auth/register', json={**credentials, 'email': 'blocked@example.com'})).status_code == 403
        # Closing registration does not disable accounts already created.
        assert (await visitor.post('/api/auth/login-json', json=credentials)).status_code == 200


@pytest.mark.asyncio
async def test_internal_signing_secret_is_absent_and_immutable_even_for_admin(client, administrator):
    from core.params.consts import INTERNAL_PARAMS
    from core.params import web_push_keys
    from core.secrets import auth_secret_key

    before = auth_secret_key()
    response = await client.get('/api/params', headers=administrator)
    assert response.status_code == 200
    assert INTERNAL_PARAMS.isdisjoint({row['name'] for row in response.json()['params']})
    assert before not in response.text
    keys = web_push_keys()
    assert keys is not None and keys.private_key not in response.text
    for name in INTERNAL_PARAMS:
        for body in ({'value': 'a' * 64}, {'clear_secret': True, 'value': None}):
            response = await client.put(f'/api/params/{name}', json=body, headers=administrator)
            assert response.status_code == 404
    configuration = await client.get('/api/chat/push/configuration', headers=administrator)
    assert configuration.status_code == 200
    assert keys.public_key in configuration.text and keys.private_key not in configuration.text
    assert web_push_keys() == keys
    assert auth_secret_key() == before
    assert (await client.get('/api/auth/me', headers=administrator)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('name,value,invalid', [
    ('DEFAULT_LANGUAGE', '', ['de', 'invalid']),
    ('DEFAULT_LANGUAGE', 'zh', ['de', 'invalid']),
    ('LOCALIZATION', '', []),
    ('WEB_PUSH_VAPID_SUBJECT', 'mailto:push@example.test', ['http://example.test', 'mailto:', 'mailto:a@', 'bad']),
    ('WEB_PUSH_DELAY_SECONDS', '4.5', ['0', '31', 'nan']),
    ('BROWSER_SESSION_TTL_SECONDS', '180', ['9', '3601', '12.5']),
    ('BROWSER_MAX_SESSIONS', '48', ['0', '257', '1.5']),
    ('MESSENGER_MAX_INLINE_MB', '3.814697265625', ['0', '1001', 'nan']),
    ('PYDANTIC_AI_BINARY_INPUT_MAX_BYTES', '41943040', ['1023', '1048576001', '1.5']),
])
async def test_operation_preferences_are_validated_and_persist_without_restart(client, administrator, name, value, invalid):
    path = f'/api/params/{name}'
    assert (await client.put(path, json={'value': value})).status_code == 401
    for bad in invalid:
        assert (await client.put(path, json={'value': bad}, headers=administrator)).status_code == 422
    assert (await client.put(path, json={'value': value}, headers=administrator)).status_code == 200
    async with get_db_session():
        await params_service.refresh()
    assert str(getattr(runtime_settings, name)) == value


@pytest.mark.asyncio
async def test_language_and_location_can_be_cleared_and_stay_empty(client, administrator):
    for name, custom in [('DEFAULT_LANGUAGE', 'fr'), ('LOCALIZATION', 'Lyon, France')]:
        path = f'/api/params/{name}'
        assert (await client.put(path, json={'value': custom}, headers=administrator)).status_code == 200
        cleared = await client.put(path, json={'value': None}, headers=administrator)
        assert cleared.status_code == 200
        async with get_db_session():
            await params_service.refresh()
        assert getattr(runtime_settings, name) == ''


@pytest.mark.asyncio
async def test_logfire_token_is_private_durable_and_controls_export_live(client, administrator, monkeypatch):
    from unittest.mock import Mock
    from core import observability
    from core.params.models import Param
    from core.user.models import User
    from core.user import token_service
    from core.util import decrypt_value

    configure = Mock()
    monkeypatch.setattr(observability.logfire, 'configure', configure)
    # The actual application instruments once before loading its preferences.
    monkeypatch.setattr(observability, '_configured', True)
    monkeypatch.setattr(observability, '_configured_token', '')
    monkeypatch.setattr(params_service, '_change_listeners', [])
    await observability.configure_runtime_observability()
    path = '/api/params/LOGFIRE_TOKEN'
    secret = 'external-logfire-token-entered-by-admin'
    assert (await client.put(path, json={'value': secret})).status_code == 401
    async with get_db_session() as db:
        outsider = User(email=f'logfire-{uuid4().hex}@example.test', hashed_password='unused', is_active=True)
        db.add(outsider)
        await db.flush()
        _, token = await token_service.create_token_for_user(outsider.id)
    assert (await client.put(path, json={'value': secret}, headers={'Authorization': f'Bearer {token}'})).status_code == 403
    invalid = await client.put(path, json={'value': secret + '\ninvalid'}, headers=administrator)
    assert invalid.status_code == 422 and secret not in invalid.text
    saved = await client.put(path, json={'value': secret}, headers=administrator)
    assert saved.status_code == 200 and secret not in saved.text
    assert saved.json()['configured'] is True
    assert configure.call_args.kwargs['token'] == secret
    assert configure.call_args.kwargs['send_to_logfire'] is True
    listed = await client.get('/api/params', headers=administrator)
    item = next(row for row in listed.json()['params'] if row['name'] == 'LOGFIRE_TOKEN')
    assert item['value'] is None and item['secret'] and item['configured']
    assert secret not in listed.text
    async with get_db_session() as db:
        stored = await db.scalar(select(Param.value).where(Param.name == 'LOGFIRE_TOKEN'))
        assert stored != secret and decrypt_value(stored) == secret
        await params_service.refresh()
    assert runtime_settings.LOGFIRE_TOKEN == secret
    assert (await client.put(path, json={'value': None}, headers=administrator)).json()['configured'] is True
    cleared = await client.put(path, json={'value': None, 'clear_secret': True}, headers=administrator)
    assert cleared.status_code == 200 and cleared.json()['configured'] is False
    assert runtime_settings.LOGFIRE_TOKEN == ''
    assert configure.call_args.kwargs['send_to_logfire'] is False


@pytest.mark.asyncio
async def test_http_limit_can_be_saved_and_applied_without_restarting(client, administrator, monkeypatch):
    path = '/api/params/HTTP_RATE_LIMIT_PER_MINUTE'
    assert (await client.put(path, json={"value": "0"}, headers=administrator)).status_code == 422
    assert (await client.put(path, json={"value": "3"})).status_code == 401
    assert (await client.put(path, json={"value": "3"}, headers=administrator)).status_code == 200
    limiter.reset()
    monkeypatch.setattr(limiter, 'enabled', True)
    for _ in range(3):
        assert (await client.get('/api/auth/me')).status_code == 401
    assert (await client.get('/api/auth/me')).status_code == 429
    assert (await client.put(path, json={"value": "1000"}, headers=administrator)).status_code == 200
    for _ in range(110):
        assert (await client.get('/api/auth/me')).status_code == 401
    async with get_db_session():
        await params_service.refresh()
    assert runtime_settings.HTTP_RATE_LIMIT_PER_MINUTE == 1000


@pytest.mark.asyncio
async def test_browser_preferences_follow_active_usage_and_parameter_rights(client, administrator):
    from app.agent.models import Agent, Title
    from app.connection import Connection
    from app.tools import ToolModel
    from core.user import token_service
    from core.user.models import User

    path = '/api/browser/status'
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=administrator)).json() == {"enabled": False}
    user_id = (await client.get('/api/auth/me', headers=administrator)).json()['id']
    async with get_db_session() as db:
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'browser'))
        title = Title(label='Browser test', gender='X')
        db.add(title)
        await db.flush()
        agent = Agent(user_id=user_id, title_id=title.id, code=f'browser-{uuid4().hex}', first_name='Browser', last_name='Tester')
        db.add(agent)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=False)
        db.add(connection)
        await db.flush()
        connection_id = connection.id
        outsider = User(email=f'outsider-{uuid4().hex}@example.test', hashed_password='unused')
        db.add(outsider)
        await db.flush()
        _, token = await token_service.create_token_for_user(outsider.id)
    denied = {"Authorization": f"Bearer {token}"}
    assert (await client.get(path, headers=denied)).status_code == 403
    assert (await client.put('/api/params/BROWSER_VIEWPORT_WIDTH', json={"value": "800"}, headers=denied)).status_code == 403
    assert (await client.get(path, headers=administrator)).json() == {"enabled": False}
    async with get_db_session() as db:
        connection = await db.get(Connection, connection_id)
        connection.active = True
    assert (await client.get(path, headers=administrator)).json() == {"enabled": True}
    async with get_db_session() as db:
        await db.delete(await db.get(Connection, connection_id))
    assert (await client.get(path, headers=administrator)).json() == {"enabled": False}
