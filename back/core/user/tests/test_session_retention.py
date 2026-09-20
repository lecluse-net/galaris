from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from core.user import refresh_session_service as sessions
from core.user.models import User, UserRefreshSession


@pytest.mark.asyncio
async def test_expired_rotation_can_be_pruned_without_losing_live_family_replay_evidence(db):
    user = User(email=f"retention-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user); await db.commit()
    initial = await sessions.create_refresh_session(user.id)
    rotated = await sessions.rotate_refresh_token(initial)
    first = await db.scalar(select(UserRefreshSession).where(UserRefreshSession.token_hash == sessions._hash_token(initial)))
    first.expires_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db.commit()
    assert await sessions.purge_expired_sessions(preview=True) == 1
    assert await sessions.is_family_active(user.id, rotated.family)
    assert await sessions.purge_expired_sessions() == 1
    assert await sessions.purge_expired_sessions() == 0
    assert (await sessions.rotate_refresh_token(rotated.token)).family == rotated.family


@pytest.mark.asyncio
async def test_security_change_can_preserve_current_family_only(db):
    user = User(email=f"security-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user); await db.commit()
    current = await sessions.create_refresh_session(user.id)
    other = await sessions.create_refresh_session(user.id)
    family = await sessions.family_for_token(current)
    await sessions.revoke_all_user_sessions(user.id, preserve_family=family)
    assert await sessions.is_family_active(user.id, family)
    assert not await sessions.is_family_active(user.id, await sessions.family_for_token(other))
