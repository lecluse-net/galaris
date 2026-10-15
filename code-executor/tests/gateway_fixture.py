"""Closed-network qualification: actual Galaris gateway, PostgreSQL and external IDE.

The tiny parent page tests origin, cookies, subpaths and native IDE loading. The
discussion components have their own browser suite. No production lifespan or agents
are started; the only replaced boundary is the synthetic Console configuration.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from starlette.responses import HTMLResponse, JSONResponse, Response
import uvicorn

from main import app
from app.agent import Agent, Title
from app.code import register_runtime
from app.code.models import CodeGrant, CodeSession, CodeWorkspace
from app.console import SshConnectionConfig
from app.connection import Connection
from app.tools import ToolModel
from bridge.code_server.adapter import CodeServerRuntime
from core.authorize import Assignment, Privilege, Role, RolePrivilege, public
from core.database import get_db_session
from core.params.params_service import load_params
from core.secrets import load_auth_secret_key
from core.user import UserModel
from core.user.auth_service import create_access_token_for_user
from core.user.refresh_session_service import create_refresh_session, family_for_token

api = app.other_asgi_app
browser_tokens = {}

async def main():
    async with httpx.AsyncClient(trust_env=False) as client:
        fixture = (await client.get('http://fixture:8766/test/status')).json()
    async with get_db_session() as db:
        await load_params()
        load_auth_secret_key('synthetic-code-signing-secret-00000001')
        user = UserModel(email='synthetic-gateway@example.test', hashed_password='synthetic')
        title = Title(label='Synthetic gateway developer', gender='X')
        db.add_all([user, title])
        await db.flush()
        agent = Agent(title_id=title.id, user_id=user.id, first_name='Synthetic', last_name='Developer',
                      code='synthetic-gateway-developer', agent_driver='internal')
        role = Role(code='synthetic-gateway-human')
        db.add_all([agent, role])
        await db.flush()
        privilege = await db.scalar(select(Privilege).where(Privilege.code == 'CODE_ACCESS'))
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'console'))
        db.add_all([RolePrivilege(role_id=role.id, privilege_id=privilege.id),
                    Assignment(user_id=user.id, role_id=role.id, is_default=True)])
        connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        config = SshConnectionConfig(connection_id=connection.id, host='fixture', port=2222,
            username='developer', private_key=SecretStr(fixture['transport_key']), known_host_key=fixture['host_key'],
            code_runtime_port=8766, code_runtime_token=SecretStr(fixture['token']))
        async def configuration(connection_id):
            assert connection_id == config.connection_id
            return config
        adapter = CodeServerRuntime(configuration)
        register_runtime(adapter)
        reference = await adapter.connection(connection.id)
        target = await adapter.discover(reference, 'project')
        workspace = CodeWorkspace(id=uuid4(), connection_id=connection.id, agent_id=agent.id,
            owner_user_id=user.id, label='Synthetic gateway repository', root=target.root, home=target.home,
            git_paths=list(target.git_paths), generation=target.generation, connection_fingerprint=reference.fingerprint,
            branch=target.branch, head=target.head)
        db.add(workspace)
        await db.flush()
        db.add_all([CodeGrant(workspace_id=workspace.id, user_id=user.id, mode='edit'),
                    CodeGrant(workspace_id=workspace.id, agent_id=agent.id, mode='edit')])

    @api.post('/api/code/qualification/open')
    @public('Synthetic isolated IDE qualification only')
    async def open_editor():
        async with get_db_session() as db:
            current = await db.get(UserModel, user.id)
            refresh = await create_refresh_session(user.id)
            token = await create_access_token_for_user(current, db, session_family=await family_for_token(refresh))
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            response = await client.post(f'http://127.0.0.1:8000/api/code/workspaces/{workspace.id}/sessions',
                headers={'Host': 'localhost:8484', 'Authorization': 'Bearer ' + token}, json={'view': 'changes'})
            if response.status_code != 200:
                return Response(response.text, status_code=502)
            browser_tokens[response.json()['id']] = token
            return JSONResponse(response.json())

    @api.post('/api/code/qualification/{identifier}/expire')
    @public('Synthetic isolated IDE expiry only')
    async def expire(identifier: str, stop: bool = False):
        async with get_db_session() as db:
            from uuid import UUID
            session = await db.get(CodeSession, UUID(identifier))
            session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if stop:
            await adapter.close(reference, session.id)
        return {'state': 'expired'}

    @api.post('/api/code/qualification/{identifier}/resume')
    @public('Synthetic isolated IDE recovery only')
    async def resume(identifier: str):
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            response = await client.post(f'http://127.0.0.1:8000/api/code/sessions/{identifier}/resume',
                headers={'Host': 'localhost:8484', 'Authorization': 'Bearer ' + browser_tokens[identifier]})
        headers = {'set-cookie': response.headers['set-cookie']} if 'set-cookie' in response.headers else {}
        return JSONResponse(response.json(), status_code=response.status_code, headers=headers)

    @api.post('/api/code/qualification/{identifier}/close')
    @public('Synthetic isolated IDE teardown only')
    async def close(identifier: str):
        from uuid import UUID
        async with get_db_session() as db:
            session = await db.get(CodeSession, UUID(identifier))
            await adapter.close(reference, session.id)
            session.state, session.cookie_digest = 'closed', None
        return {'state': 'closed'}

    @api.get('/api/code/qualification/parent')
    @public('Synthetic isolated IDE parent page only')
    async def parent():
        return HTMLResponse('''<!doctype html><meta charset="utf-8">
<button id="open">Open synthetic repository</button><span id="ready"></span>
<iframe title="Synthetic IDE" style="width:95vw;height:85vh;border:0"></iframe>
<script src="/api/code/qualification/parent.js"></script>''')

    @api.get('/api/code/qualification/parent.js')
    @public('Synthetic isolated IDE parent script only')
    async def parent_script():
        return Response('''
let session;
document.querySelector('button').onclick = async () => {
 const data = await (await fetch('/api/code/qualification/open', {method:'POST'})).json();
 session = data.id; document.querySelector('iframe').src = data.url;
};
addEventListener('message', event => {
 if (event.origin === location.origin && event.source === document.querySelector('iframe').contentWindow
     && event.data.session === session) document.querySelector('#ready').textContent = event.data.type;
});
''', media_type='application/javascript')

    @api.get('/api/code/qualification/status')
    @public('Synthetic isolated IDE readiness only')
    async def status():
        return {'state': 'ready'}

    server = uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=8000, lifespan='off', access_log=False))
    await server.serve()


if __name__ == '__main__':
    asyncio.run(main())
