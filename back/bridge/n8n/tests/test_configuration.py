"""Preference administrators diagnose n8n without process permissions or execution."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from bridge.n8n import engine
from bridge.n8n.client import N8NClient
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.params import params_service, runtime_settings
from core.user import token_service
from core.user.models import User


@pytest.mark.asyncio
async def test_preferences_diagnostics_enforce_rights_and_never_execute_or_reveal_remote_secrets(client, monkeypatch):
    original = runtime_settings.model_dump()
    headers = {}
    async with get_db_session() as db:
        for name, permission in [('editor', 'PARAMS_EDIT'), ('reader', 'PARAMS_ACCESS'), ('outsider', None)]:
            user = User(email=f'n8n-{uuid4().hex}@example.test', hashed_password='unused')
            db.add(user)
            await db.flush()
            if permission:
                privilege = await db.scalar(select(Privilege).where(Privilege.code == permission))
                role = Role(code=f'n8n-{uuid4().hex}', privileges=[privilege])
                db.add(role)
                await db.flush()
                db.add(Assignment(user_id=user.id, role_id=role.id))
            _, token = await token_service.create_token_for_user(user.id)
            headers[name] = {'Authorization': f'Bearer {token}'}
    status = 200
    body = {'data': []}
    requests = []

    async def remote(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(engine, 'N8NClient', lambda *args, **kwargs: N8NClient(*args, **kwargs, transport=httpx.MockTransport(remote)))
    try:
        assert (await client.get('/api/n8n/settings')).status_code == 401
        assert (await client.post('/api/n8n/test')).status_code == 401
        for role in ['reader', 'outsider']:
            assert (await client.post('/api/n8n/test', headers=headers[role])).status_code == 403
        assert (await client.get('/api/n8n/settings', headers=headers['outsider'])).status_code == 403
        defaults = await client.get('/api/n8n/settings', headers=headers['reader'])
        assert defaults.status_code == 200
        assert set(defaults.json()) == {'galaris_base_url'}
        for name, value in [('PROCESS_N8N_BASE_URL', ''), ('PROCESS_N8N_API_TOKEN', '')]:
            assert (await client.put(f'/api/params/{name}', json={'value': value, 'clear_secret': True}, headers=headers['editor'])).status_code == 200
        assert (await client.post('/api/n8n/test', headers=headers['editor'])).json()['code'] == 'missing_url'
        assert (await client.put('/api/params/PROCESS_N8N_BASE_URL', json={'value': 'https://n8n.example.test'}, headers=headers['editor'])).status_code == 200
        assert (await client.post('/api/n8n/test', headers=headers['editor'])).json()['code'] == 'missing_api_key'
        assert not requests
        assert (await client.put('/api/params/PROCESS_N8N_API_TOKEN', json={'value': 'api-secret'}, headers=headers['editor'])).status_code == 200
        response = await client.post('/api/n8n/test', headers=headers['editor'])
        assert response.status_code == 200
        assert response.json()['ok'] is True  # No workflows yet is a valid connection.
        for status, body, code in [
            (401, {'detail': 'remote echo: api-secret'}, 'unauthorized'),
            (403, {'detail': 'api-secret'}, 'unauthorized'),
            (404, {}, 'not_found'), (429, {}, 'rate_limited'), (503, {}, 'engine_unreachable'),
            (200, {'text': '<html>Proxy login</html>'}, 'invalid_response'),
        ]:
            response = await client.post('/api/n8n/test', headers=headers['editor'])
            assert response.json() == {'ok': False, 'code': code, 'message': ''}
            assert 'api-secret' not in response.text
        assert all(request.method == 'GET' and request.url.path == '/api/v1/workflows' for request in requests)
        assert all(request.headers['X-N8N-API-KEY'] == 'api-secret' for request in requests)
    finally:
        for name, value in original.items():
            setattr(runtime_settings, name, value)
        monkeypatch.setattr(params_service, '_cache_loaded', False)
