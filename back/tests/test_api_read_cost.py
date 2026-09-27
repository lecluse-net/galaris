"""HTTP read budgets include authentication, authorization and domain projections."""
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import delete, event, insert, select, update
from sqlalchemy.engine import Engine

from core.database import get_db_session
from core.user.models import User
from core.user.user_service import encrypt_password
from core.authorize.models import Assignment, Role, Privilege
from app.agent.models import Agent, Title
from app.memory.models import MemoryItem, MemoryRevision
from app.memory.storage import NativeFileStorage, register_storage, reset_storage_registry
from app.goal.models import Goal, GoalStatus

DESTINATION = Path(__file__).resolve().parents[2] / 'artifacts/api-sql-optimization'


@pytest.mark.asyncio
async def test_http_reads_stay_bounded_and_revocations_remain_visible(client, tmp_path):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    reset_storage_registry()
    storage = NativeFileStorage(tmp_path, max_bytes=1_000_000)
    register_storage(storage)
    reports = []
    try:
        async with get_db_session() as db:
            user = User(email='sql-audit@example.com', hashed_password=encrypt_password('synthetic-audit-password'), is_active=True)
            outsider = User(email='sql-audit-other@example.com', hashed_password='unused', is_active=True)
            rights = list(await db.scalars(select(Privilege).where(Privilege.code.in_([
                'AGENT_ACCESS', 'MEMORY_ACCESS', 'MEMORY_EDIT', 'GOAL_ACCESS', 'GOAL_EDIT', 'TASK_ACCESS',
            ]))))
            assert len(rights) == 6
            role = Role(code='sql-audit-reader', privileges=rights)
            title = Title(label='Audit', gender='M')
            db.add_all([user, outsider, role, title])
            await db.flush()
            db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
            agent = Agent(user_id=user.id, title_id=title.id, code='sql-audit-agent', first_name='Synthetic', last_name='Audit', agent_driver='internal')
            db.add(agent)
            await db.flush()
            content = b'<p>Synthetic audit content.</p>'
            resource = await storage.create(content)
            docs = []
            for name in ('Document', 'Description', 'Tracking', 'Hidden'):
                item = MemoryItem(owner_agent_id=agent.id if name != 'Hidden' else None,
                    owner_user_id=outsider.id if name == 'Hidden' else None,
                    resource_id=resource, title=f'Audit {name}', node_kind='document',
                    memory_type='working', content_type='text', media_type='text/html',
                    content_hash=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                    search_text='Synthetic audit content')
                db.add(item)
                docs.append(item)
            await db.flush()
            item = docs[0]
            revision_template = dict(item_id=item.id, provider_code='native', resource_id=resource,
                content_hash=item.content_hash, content_type='text', media_type='text/html',
                title=item.title, document_content_version=True)
            await db.execute(insert(MemoryRevision), [dict(revision_template, revision=1)])
            goal = Goal(title='Synthetic audit goal', agent_id=agent.id,
                description_document_id=docs[1].id, tracking_document_id=docs[2].id,
                status=GoalStatus.PAUSED, cycle_delay_seconds=0)
            db.add(goal)
            await db.flush()
            doc_id, hidden_id, agent_id, goal_id, user_id = item.id, docs[3].id, agent.id, goal.id, user.id
            outsider_id = outsider.id

        login = await client.post('/api/auth/login-json', json={
            'email': 'sql-audit@example.com', 'password': 'synthetic-audit-password',
        })
        assert login.status_code == 200, login.text
        headers = {'Authorization': f"Bearer {login.json()['access_token']}"}

        async def measure(name, method, path, expected=200, body=None):
            statements = []
            def capture(_conn, cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
                    normalized = re.sub(r'\s+', ' ', statement).strip()
                    tables = sorted(set(re.findall(r'\b(?:FROM|JOIN)\s+([a-z_][a-z_0-9]*)', normalized, re.I)))
                    statements.append({'fingerprint': hashlib.sha256(normalized.encode()).hexdigest()[:12],
                        'tables': tables, 'rows': cursor.rowcount})
            event.listen(Engine, 'after_cursor_execute', capture)
            started = time.perf_counter()
            try:
                response = await client.request(method, path, headers=headers, json=body)
            finally:
                elapsed = time.perf_counter() - started
                event.remove(Engine, 'after_cursor_execute', capture)
            counts = Counter(row['fingerprint'] for row in statements)
            reports.append({'scenario': name, 'status': response.status_code,
                'selects': len(statements), 'elapsed_ms': round(elapsed * 1000, 2),
                'response_bytes': len(response.content),
                'revision_selects': sum('memory_revisions' in row['tables'] for row in statements),
                'revision_rows_returned': sum(max(0, row['rows']) for row in statements if row['tables'] == ['memory_revisions']),
                'repeated_statement_executions': sum(count - 1 for count in counts.values()),
                'statements': statements})
            DESTINATION.joinpath('measurements.json').write_text(json.dumps(reports, indent=2))
            assert response.status_code == expected, f'{name}: {response.status_code} {response.text[:500]}'
            return response

        for repeat in range(2):
            await measure(f'identity_{repeat}', 'GET', '/api/auth/me')
            await measure(f'agents_{repeat}', 'GET', '/api/agents')
            await measure(f'agent_detail_{repeat}', 'GET', f'/api/agents/{agent_id}')
            await measure(f'library_{repeat}', 'POST', '/api/memory/documents/library', body={'limit': 50})
            opened = await measure(f'document_1_revision_{repeat}', 'GET', f'/api/memory/documents/{doc_id}')
            assert opened.json()['item']['payload']['text'] == content.decode()
        await measure('document_denied', 'GET', f'/api/memory/documents/{hidden_id}', expected=403)
        await measure('owner_options', 'GET', '/api/memory/documents/owner-options')
        await measure('goal_detail', 'GET', f'/api/goals/{goal_id}')
        await measure('goal_cycles', 'GET', f'/api/goals/{goal_id}/cycles')
        async with get_db_session() as db:
            await db.execute(insert(MemoryRevision), [dict(revision_template, revision=n) for n in range(2, 1001)])
            current_content = b'<p>Updated synthetic content.</p>'
            current_resource = await storage.create(current_content)
            current_hash = hashlib.sha256(current_content).hexdigest()
            await db.execute(update(MemoryItem).where(MemoryItem.id == doc_id).values(
                revision=1000, resource_id=current_resource, content_hash=current_hash, size_bytes=len(current_content)))
            await db.execute(update(MemoryRevision).where(MemoryRevision.item_id == doc_id, MemoryRevision.revision == 1000)
                             .values(resource_id=current_resource, content_hash=current_hash))
        for repeat in range(2):
            reopened = await measure(f'document_1000_revisions_{repeat}', 'GET', f'/api/memory/documents/{doc_id}')
            assert reopened.json()['item']['payload']['text'] == current_content.decode()
            assert reopened.json()['item']['revision'] == 1000
        history = await measure('revision_page_1000', 'GET', f'/api/memory/documents/{doc_id}/content-revisions')
        assert history.json()['total'] == 1000
        assert [row['revision'] for row in history.json()['items']] == list(range(1000, 950, -1))
        old_version = await measure('old_content_revision', 'GET', f'/api/memory/documents/{doc_id}/content-revisions/1')
        assert old_version.json()['content'] == content.decode()
        assert old_version.json()['revision'] == 1
        await measure('missing_content_revision', 'GET', f'/api/memory/documents/{doc_id}/content-revisions/1001', expected=404)
        async with get_db_session() as db:
            await db.execute(update(Agent).where(Agent.id == agent_id).values(user_id=outsider_id))
        await measure('changed_manager_document', 'GET', f'/api/memory/documents/{doc_id}', expected=403)
        await measure('changed_manager_cycles', 'GET', f'/api/goals/{goal_id}/cycles', expected=404)
        async with get_db_session() as db:
            await db.execute(update(Agent).where(Agent.id == agent_id).values(user_id=user_id))
        await measure('restored_manager_document', 'GET', f'/api/memory/documents/{doc_id}')
        async with get_db_session() as db:
            await db.execute(delete(Assignment).where(Assignment.user_id == user_id))
        await measure('revoked_role_document', 'GET', f'/api/memory/documents/{doc_id}', expected=403)
        by_name = {report['scenario']: report for report in reports}
        for name in ('document_1_revision_0', 'document_1_revision_1',
                     'document_1000_revisions_0', 'document_1000_revisions_1'):
            assert by_name[name]['revision_rows_returned'] == 0, 'Current content must not materialize history'
            assert by_name[name]['selects'] <= 14, 'Document opening must share bounded authorization reads'
        assert by_name['revision_page_1000']['revision_rows_returned'] <= 51
        assert by_name['old_content_revision']['revision_rows_returned'] == 1
        assert by_name['library_1']['selects'] <= 11
        assert by_name['owner_options']['selects'] <= 7
        assert by_name['goal_cycles']['selects'] <= 7
        assert by_name['identity_1']['selects'] == 1
        assert by_name['agents_1']['selects'] <= 5
        assert by_name['agent_detail_1']['selects'] <= 5
    finally:
        reset_storage_registry()
