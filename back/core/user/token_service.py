"""
Manage user access tokens.

Tokens are encrypted at rest with ENCRYPTION_MASTER_KEY.
SHA-256 enables token lookup without storing plaintext.

Usage:
    >>> from core.user import token_service
    >>> tokens = await token_service.list_tokens_for_user(1)
    >>> token = await token_service.create_token_for_user(1)
    >>> await token_service.delete_token(1, 1)
"""

import secrets
from typing import List, Optional
from sqlalchemy import select
from loguru import logger

from core.database import get_db
from core.util.encryption import encrypt_value
from core.util.token_hash import hash_token
from .models import UserToken
from .schemas import UserTokenCreate, UserTokenUpdate


_TOKEN_PREFIX = "ut_"
_TOKEN_LENGTH = 48


def _generate_token_value() -> str:
    """Generate a secure, unique token value."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_LENGTH)


async def list_tokens_for_user(user_id: int) -> List[UserToken]:
    """List all tokens for a user."""
    db = get_db()
    result = await db.execute(
        select(UserToken).where(UserToken.user_id == user_id).order_by(UserToken.created_at.desc())
    )
    return list(result.scalars().all())


async def get_token_by_id(token_id: int, user_id: int) -> Optional[UserToken]:
    """Get a token by ID, restricted to its owning user."""
    db = get_db()
    result = await db.execute(
        select(UserToken).where(UserToken.id == token_id, UserToken.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_token_by_value(token_value: str) -> Optional[UserToken]:
    """
    Get a token by plaintext value for authentication. Lookup uses SHA-256
    because plaintext is encrypted at rest.
    """
    db = get_db()
    token_hash = hash_token(token_value)
    result = await db.execute(
        select(UserToken).where(
            UserToken.token_hash == token_hash,
            UserToken.enabled.is_(True)
        )
    )
    return result.scalar_one_or_none()


async def create_token_for_user(user_id: int, data: Optional[UserTokenCreate] = None) -> tuple[UserToken, str]:
    """
    Create a token for a user.

    Returns:
        (user_token_db, plain_token_value)
        The plaintext token is returned only once.
    """
    db = get_db()
    token_value = _generate_token_value()
    new_token = UserToken(
        user_id=user_id,
        label=data.label if data else None,
        token_encrypted=encrypt_value(token_value),
        token_hash=hash_token(token_value),
        enabled=data.enabled if data else True,
    )
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    logger.info("Created token for user {} (id={})", user_id, new_token.id)
    return new_token, token_value


async def update_token(token_id: int, user_id: int, data: UserTokenUpdate) -> Optional[UserToken]:
    """Update an existing token."""
    db = get_db()
    token = await get_token_by_id(token_id, user_id)
    if not token:
        return None

    if data.label is not None:
        token.label = data.label

    if data.enabled is not None:
        token.enabled = data.enabled

    await db.commit()
    await db.refresh(token)
    logger.info("Updated token {} for user {}", token_id, user_id)
    return token


async def delete_token(token_id: int, user_id: int) -> bool:
    """Delete a token."""
    db = get_db()
    token = await get_token_by_id(token_id, user_id)
    if not token:
        return False

    await db.delete(token)
    await db.commit()
    logger.info("Deleted token {} for user {}", token_id, user_id)
    return True
