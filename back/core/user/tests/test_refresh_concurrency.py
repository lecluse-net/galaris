"""Refresh/revocation races with committed, independent PostgreSQL sessions."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from core.database.database import db_session_ctx
from core.user import refresh_session_service as sessions
from core.user.models import User


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_first", [False, True])
@pytest.mark.parametrize("operation", ["logout", "all", "deactivate", "password", "mfa"])
async def test_revocation_serializes_with_rotation(
    committed_database, monkeypatch, revoke_first, operation,
):
    factory = committed_database
    async with factory() as db:
        context = db_session_ctx.set(db)
        try:
            user = User(email=f"race-{uuid4()}@example.test", hashed_password="unused", is_active=True)
            if operation == "mfa":
                from core.util import encrypt_value
                user.totp_secret_encrypted = encrypt_value("JBSWY3DPEHPK3PXP")
            db.add(user)
            await db.commit()
            user_id = user.id
            token = await sessions.create_refresh_session(user_id)
            family = await sessions.family_for_token(token)
        finally:
            db_session_ctx.reset(context)

    locked, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_lock = sessions._lock_user_sessions
    first_task = None
    waiting_pid = None

    async def paused_lock(owner):
        result = await original_lock(owner)
        if asyncio.current_task() is first_task:
            locked.set()
            await release.wait()
        return result

    monkeypatch.setattr(sessions, "_lock_user_sessions", paused_lock)

    async def perform(revoke):
        nonlocal waiting_pid
        async with factory() as db:
            context = db_session_ctx.set(db)
            try:
                if asyncio.current_task() is not first_task:
                    waiting_pid = await db.scalar(text("select pg_backend_pid()"))
                    waiting.set()
                if not revoke:
                    try:
                        return await sessions.rotate_refresh_token(token)
                    except sessions.InvalidRefreshTokenError:
                        return None
                if operation == "logout":
                    assert await sessions.revoke_refresh_token(token)
                elif operation == "all":
                    await sessions.revoke_all_user_sessions(user_id)
                elif operation == "mfa":
                    from core.user import mfa_service
                    import time
                    await sessions._lock_user_sessions(user_id)
                    await mfa_service.confirm_setup(user_id, mfa_service._totp("JBSWY3DPEHPK3PXP", int(time.time()) // 30))
                else:
                    from core.user.schemas import UserUpdate
                    from core.user.user_service import update

                    change = UserUpdate(is_active=False) if operation == "deactivate" else UserUpdate(password="a-new-password")
                    # Match the account writer's row lock before pausing it.
                    await sessions._lock_user_sessions(user_id)
                    await update(user_id, change)
                return None
            finally:
                db_session_ctx.reset(context)

    first_task = asyncio.create_task(perform(revoke_first))
    second_task = None
    try:
        await asyncio.wait_for(locked.wait(), 10)
        second_task = asyncio.create_task(perform(not revoke_first))
        await asyncio.wait_for(waiting.wait(), 10)
        async with asyncio.timeout(10), factory() as observer:
            while not await observer.scalar(text(
                "select wait_event_type = 'Lock' from pg_stat_activity where pid = :pid"
            ), {"pid": waiting_pid}):
                await observer.commit()
                await asyncio.sleep(0.01)
    finally:
        release.set()
        results = await asyncio.gather(first_task, *([second_task] if second_task else []))

    async with factory() as db:
        context = db_session_ctx.set(db)
        try:
            assert not await sessions.is_family_active(user_id, family)
            for result in results:
                if result is not None:
                    with pytest.raises(sessions.InvalidRefreshTokenError):
                        await sessions.rotate_refresh_token(result.token)
        finally:
            db_session_ctx.reset(context)
