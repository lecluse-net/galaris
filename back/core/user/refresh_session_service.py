"""Persistent, rotating sessions for browser and PWA clients."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from loguru import logger
from sqlalchemy import delete, select, update

from core import settings
from core.secrets import auth_secret_key
from core.database import get_db

from .models import User, UserRefreshSession


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token cannot open a valid session."""


class RefreshTokenReplayError(InvalidRefreshTokenError):
    """Raised when a rotated token is reused outside the concurrency grace period."""


@dataclass(frozen=True, slots=True)
class RefreshRotation:
    """Result of a successful refresh-token rotation."""

    user: User
    token: str
    family: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _derive_replacement_token(token: str) -> str:
    """Derive a stable replacement so concurrent refreshes receive the same token."""

    digest = hmac.new(
        auth_secret_key().encode("utf-8"),
        f"galaris-refresh:{token}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _normalized_user_agent(user_agent: Optional[str]) -> Optional[str]:
    if not user_agent:
        return None
    return user_agent[:512]


def _new_expiry(now: datetime) -> datetime:
    return now + timedelta(days=settings.AUTH_REFRESH_TOKEN_EXPIRE_DAYS)


async def _active_user(user_id: int) -> Optional[User]:
    db = get_db()
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def _lock_user_sessions(user_id: int) -> User | None:
    """Serialize token creation/rotation/revocation with account changes.

    Lock the stable owner before reading mutable token rows. A lock on just the
    previous token cannot protect a replacement inserted by another transaction.
    The following statements get a fresh READ COMMITTED snapshot after waiting.
    """
    return await get_db().scalar(
        select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True)
    )


async def _lock_token_owner(token: str) -> None:
    user_id = await get_db().scalar(
        select(UserRefreshSession.user_id)
        .where(UserRefreshSession.token_hash == _hash_token(token))
    )
    if user_id is not None:
        await _lock_user_sessions(user_id)


async def _revoke_family(family_id: str, revoked_at: datetime) -> None:
    db = get_db()
    await db.execute(
        update(UserRefreshSession)
        .where(UserRefreshSession.family_id == family_id)
        .where(UserRefreshSession.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )


async def create_refresh_session(
    user_id: int,
    user_agent: Optional[str] = None,
) -> str:
    """Create a new independently revocable browser session."""

    db = get_db()
    user = await _lock_user_sessions(user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshTokenError("Refresh session user is inactive or missing")
    now = _utcnow()
    token = secrets.token_urlsafe(48)
    session = UserRefreshSession(
        user_id=user_id,
        family_id=str(uuid4()),
        token_hash=_hash_token(token),
        expires_at=_new_expiry(now),
        user_agent=_normalized_user_agent(user_agent),
    )
    db.add(session)
    await db.commit()
    logger.info("Created persistent browser session for user {}", user_id)
    return token


async def rotate_refresh_token(
    token: str,
    user_agent: Optional[str] = None,
) -> RefreshRotation:
    """Validate and rotate a refresh token, detecting reuse after a short grace."""

    db = get_db()
    await _lock_token_owner(token)
    now = _utcnow()
    result = await db.execute(
        select(UserRefreshSession)
        .where(UserRefreshSession.token_hash == _hash_token(token))
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise InvalidRefreshTokenError("Unknown refresh token")

    if session.expires_at <= now:
        if session.revoked_at is None:
            session.revoked_at = now
            await db.commit()
        raise InvalidRefreshTokenError("Expired refresh token")

    if session.revoked_at is not None:
        grace = timedelta(seconds=settings.AUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS)
        if now - session.revoked_at <= grace:
            replacement_token = _derive_replacement_token(token)
            replacement_result = await db.execute(
                select(UserRefreshSession)
                .where(UserRefreshSession.family_id == session.family_id)
                .where(UserRefreshSession.token_hash == _hash_token(replacement_token))
                .where(UserRefreshSession.revoked_at.is_(None))
                .where(UserRefreshSession.expires_at > now)
            )
            replacement = replacement_result.scalar_one_or_none()
            user = await _active_user(session.user_id)
            if replacement is not None and user is not None:
                return RefreshRotation(user=user, token=replacement_token, family=session.family_id)

        await _revoke_family(session.family_id, now)
        await db.commit()
        logger.warning(
            "Revoked browser session family after refresh-token replay for user {}",
            session.user_id,
        )
        raise RefreshTokenReplayError("Refresh token replay detected")

    user = await _active_user(session.user_id)
    if user is None:
        await _revoke_family(session.family_id, now)
        await db.commit()
        raise InvalidRefreshTokenError("Refresh session user is inactive or missing")

    replacement_token = _derive_replacement_token(token)
    replacement = UserRefreshSession(
        user_id=session.user_id,
        family_id=session.family_id,
        token_hash=_hash_token(replacement_token),
        expires_at=_new_expiry(now),
        user_agent=_normalized_user_agent(user_agent) or session.user_agent,
    )
    session.last_used_at = now
    session.revoked_at = now
    db.add(replacement)
    await db.commit()
    return RefreshRotation(user=user, token=replacement_token, family=session.family_id)


async def family_for_token(token: str) -> str:
    family = await get_db().scalar(
        select(UserRefreshSession.family_id).where(UserRefreshSession.token_hash == _hash_token(token))
    )
    if family is None:
        raise InvalidRefreshTokenError("Unknown refresh token")
    return family


async def is_family_active(user_id: int, family: str) -> bool:
    return await get_db().scalar(
        select(UserRefreshSession.id).where(
            UserRefreshSession.user_id == user_id,
            UserRefreshSession.family_id == family,
            UserRefreshSession.revoked_at.is_(None),
            UserRefreshSession.expires_at > _utcnow(),
        ).limit(1)
    ) is not None


async def revoke_refresh_token(token: str) -> bool:
    """Revoke the complete session family represented by one refresh token."""

    db = get_db()
    await _lock_token_owner(token)
    result = await db.execute(
        select(UserRefreshSession).where(
            UserRefreshSession.token_hash == _hash_token(token)
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return False

    await _revoke_family(session.family_id, _utcnow())
    await db.commit()
    logger.info("Revoked persistent browser session for user {}", session.user_id)
    return True


async def revoke_all_user_sessions(user_id: int, *, preserve_family: str | None = None) -> None:
    """Revoke every persistent browser session belonging to a user."""

    db = get_db()
    await _lock_user_sessions(user_id)
    statement = (
        update(UserRefreshSession)
        .where(UserRefreshSession.user_id == user_id)
        .where(UserRefreshSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    if preserve_family is not None:
        statement = statement.where(UserRefreshSession.family_id != preserve_family)
    await db.execute(statement)
    await db.commit()
    logger.info("Revoked all persistent browser sessions for user {}", user_id)


async def purge_expired_sessions(*, preview: bool = False, batch_size: int = 500) -> int:
    """Prune tokens seven days after expiry; unexpired replay evidence survives.

    Rotation rejects expiry before replay handling. Keeping expired ancestors
    cannot revoke a family and would make continuously rotated families unbounded.
    """
    db = get_db()
    ids = list(await db.scalars(select(UserRefreshSession.id).where(
        UserRefreshSession.expires_at < _utcnow() - timedelta(days=7),
    ).order_by(UserRefreshSession.expires_at, UserRefreshSession.id).limit(max(1, min(batch_size, 500))).with_for_update(skip_locked=True)))
    if ids and not preview:
        await db.execute(delete(UserRefreshSession).where(UserRefreshSession.id.in_(ids)))
        await db.commit()
    return len(ids)
