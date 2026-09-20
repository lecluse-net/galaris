"""Temporary audit counterexamples; not permanent regression assertions."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from core.database.database import db_session_ctx
from core.user.models import User
from core.user import refresh_session_service as sessions


@pytest.mark.asyncio
async def test_logout_racing_with_rotation_leaves_active_family(committed_database, monkeypatch):
    factory = committed_database
    async with factory() as db:
        context = db_session_ctx.set(db)
        user = User(email=f'audit-{uuid4()}@example.test', hashed_password='unused', is_active=True)
        db.add(user)
        await db.commit()
        user_id = user.id
        token = await sessions.create_refresh_session(user_id)
        family = await sessions.family_for_token(token)
        db_session_ctx.reset(context)

    locked = asyncio.Event()
    release = asyncio.Event()
    revoke_started = asyncio.Event()
    revoke_pid = None
    original_active = sessions._active_user

    async def paused_active(user_id):
        locked.set()
        await release.wait()
        return await original_active(user_id)

    monkeypatch.setattr(sessions, '_active_user', paused_active)

    async def rotate():
        async with factory() as db:
            context = db_session_ctx.set(db)
            try:
                return await sessions.rotate_refresh_token(token)
            finally:
                db_session_ctx.reset(context)

    async def revoke():
        nonlocal revoke_pid
        async with factory() as db:
            context = db_session_ctx.set(db)
            try:
                revoke_pid = await db.scalar(text('select pg_backend_pid()'))
                revoke_started.set()
                return await sessions.revoke_refresh_token(token)
            finally:
                db_session_ctx.reset(context)

    rotation = asyncio.create_task(rotate())
    await asyncio.wait_for(locked.wait(), 5)
    revocation = asyncio.create_task(revoke())
    try:
        await asyncio.wait_for(revoke_started.wait(), 5)
        async with asyncio.timeout(5), factory() as observer:
            while not await observer.scalar(text(
                "select wait_event_type = 'Lock' from pg_stat_activity where pid = :pid"
            ), {'pid': revoke_pid}):
                await observer.commit()
                await asyncio.sleep(0.01)
    finally:
        release.set()
    result, revoked = await asyncio.gather(rotation, revocation)
    assert revoked is True
    async with factory() as db:
        context = db_session_ctx.set(db)
        try:
            active = await sessions.is_family_active(user_id, family)
            assert active is True
            assert (await sessions.rotate_refresh_token(result.token)).family == family
            print('CONFIRMED: logout returned success but concurrent replacement remains refreshable')
        finally:
            db_session_ctx.reset(context)


@pytest.mark.asyncio
async def test_telegram_repeats_a_send_after_lost_response(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from telegram.error import TimedOut
    from bridge.telegram.client import TelegramClient

    effects = []
    async def send_message(**kwargs):
        effects.append(kwargs)
        if len(effects) == 1:
            raise TimedOut('response lost after remote acceptance')
        return SimpleNamespace(message_id=2)
    monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
    client = TelegramClient('unused', bot=SimpleNamespace(send_message=send_message))
    await client.send_text('1234', 'audit canary')
    assert len(effects) == 2
    print('CONFIRMED: Telegram repeats non-idempotent send after lost response')


@pytest.mark.asyncio
async def test_whatsapp_repeats_a_send_after_lost_response(monkeypatch):
    from unittest.mock import AsyncMock
    import httpx
    from bridge.whatsapp.client import WhatsAppClient

    effects = []
    async def request(req):
        effects.append(req.content)
        if len(effects) == 1:
            raise httpx.ReadTimeout('response lost after remote acceptance', request=req)
        return httpx.Response(200, json={'messages': [{'id': 'second'}]})
    monkeypatch.setattr(asyncio, 'sleep', AsyncMock())
    async with httpx.AsyncClient(base_url='https://example.test', transport=httpx.MockTransport(request)) as http:
        client = WhatsAppClient(access_token='unused', phone_number_id='1234',
            graph_url='https://example.test', graph_version='v1', timeout=1, http=http)
        await client.send_text('4567', 'audit canary')
    assert len(effects) == 2
    print('CONFIRMED: WhatsApp repeats non-idempotent send after lost response')


@pytest.mark.asyncio
async def test_optional_dbadmin_action_correction_is_fatal(db):
    from core.dbadmin.actions import validate_open_actions
    from core.dbadmin.contracts import DbAdminFatalError, DbAdminPhase
    from core.dbadmin.models import DbAdminActionRecord
    from core.dbadmin.registry import DbAdminAction, DbAdminRegistry
    from unittest.mock import AsyncMock

    key = 'audit.optional_action'
    db.add(DbAdminActionRecord(key=key, phase='after_expand', checksum='v1', status='failed'))
    await db.commit()
    registry = DbAdminRegistry()
    condition = AsyncMock(return_value=True)
    registry.register_action(DbAdminAction(key=key, phase=DbAdminPhase.AFTER_EXPAND,
        checksum='v2', required=False, predicate=lambda _: False,
        handler=AsyncMock(), postcondition=condition))
    with pytest.raises(DbAdminFatalError, match='checksum'):
        await validate_open_actions(registry)
    assert condition.await_count == 0
    print('CONFIRMED: corrected optional unfinished DbAdmin action blocks before postcondition check')


@pytest.mark.asyncio
async def test_retention_removes_run_before_await_reconciliation(db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.process.tests.test_recovery import waiting_run
    from app.process import process_service as service
    from app.process.models import ProcessRun
    from app.task.models import TaskStatus

    run, parent, child = await waiting_run.__wrapped__(db, monkeypatch)
    run.status = 'success'
    run.finished_at = datetime.now(timezone.utc) - timedelta(days=3)
    run.output = {'useful_result': 'canary'}
    await db.commit()
    monkeypatch.setattr(service.runtime_settings, 'PROCESS_RETENTION_RUN_DAYS', 1)
    assert run.await_resolved_at is None
    assert child.status not in (TaskStatus.SUCCESS, TaskStatus.ERROR)
    result = await service.purge_retention()
    assert result['runs'] == 1
    assert await db.scalar(select(ProcessRun.id).where(ProcessRun.id == run.id)) is None
    assert parent.paused
    print('CONFIRMED: enabled Process retention deletes terminal run with unresolved dependent Task')


@pytest.mark.asyncio
async def test_materialization_limit_is_checked_after_complete_download(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.file_share import resource_service as resources
    from app.file_share.resource_contracts import ResourceContext

    downloaded = []
    async def download(remote, destination, *, target):
        destination.write_bytes(b'x' * 1000)
        downloaded.append(destination.stat().st_size)
        return 1000
    monkeypatch.setattr(resources, 'resource_info', AsyncMock(return_value=SimpleNamespace(
        size=0, is_collection=False, name='canary.bin', media_type='application/octet-stream')))
    monkeypatch.setattr(resources, '_connected_transport', AsyncMock(return_value=(
        SimpleNamespace(download_to=download), 'https', 'https://example.test/canary', '')))
    destination = tmp_path / 'canary'
    with pytest.raises(ValueError, match='10-byte'):
        await resources.materialize_resource(ResourceContext(1, 'internal'),
            'https://example.test/canary', destination, max_bytes=10)
    assert downloaded == [1000]
    assert not destination.exists()
    print('CONFIRMED: 1000 bytes fully downloaded before enforcing max_bytes=10; cleanup happens afterwards')
