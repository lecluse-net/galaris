"""Manage MCP access tokens for agents.

Tokens are encrypted at rest with ``ENCRYPTION_MASTER_KEY``. Their SHA-256 hash
supports lookup without storing a plaintext value, following
``core.user.token_service``.

Usage:
    >>> from app.mcp import mcp_token_service
    >>> tokens = await mcp_token_service.list_tokens_for_agent(1)
    >>> token, plain = await mcp_token_service.create_token_for_agent(1)
    >>> await mcp_token_service.delete_token(token.id, 1)
"""

import secrets
from typing import List, Optional

from sqlalchemy import select
from loguru import logger

from core.database import get_db
from core.util.encryption import encrypt_value
from core.util.token_hash import hash_token

from .models import AgentMcpToken
from .schemas import AgentMcpTokenCreate, AgentMcpTokenUpdate


_TOKEN_PREFIX = "mcp_"
_TOKEN_LENGTH = 48


def _generate_token_value() -> str:
    """Generate a secure, unique token value."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_LENGTH)


async def list_tokens_for_agent(agent_id: int) -> List[AgentMcpToken]:
    """List an agent's visible MCP tokens, excluding hidden system tokens."""
    db = get_db()
    result = await db.execute(
        select(AgentMcpToken)
        .where(
            AgentMcpToken.agent_id == agent_id,
            AgentMcpToken.hidden.is_(False),
        )
        .order_by(AgentMcpToken.created_at.desc())
    )
    return list(result.scalars().all())


async def rotate_system_token(agent_id: int) -> str:
    """Rotate an agent's hidden system MCP token and return its plaintext value.

    A managed external runtime uses this token to authenticate with the agent's
    HTTP MCP endpoint.
    The token is omitted from user-facing lists, and rotation removes every old
    system token so that only one remains.
    """
    db = get_db()
    result = await db.execute(
        select(AgentMcpToken).where(
            AgentMcpToken.agent_id == agent_id,
            AgentMcpToken.hidden.is_(True),
        )
    )
    for old in result.scalars().all():
        await db.delete(old)

    token_value = _generate_token_value()
    new_token = AgentMcpToken(
        agent_id=agent_id,
        label="managed runtime (system)",
        token_encrypted=encrypt_value(token_value),
        token_hash=hash_token(token_value),
        enabled=True,
        hidden=True,
    )
    db.add(new_token)
    await db.commit()
    logger.info("Rotated managed-runtime MCP token for agent {}", agent_id)
    return token_value


async def revoke_system_tokens(agent_id: int) -> int:
    """Revoke every hidden token after the owning managed runtime is destroyed."""

    db = get_db()
    result = await db.execute(
        select(AgentMcpToken).where(
            AgentMcpToken.agent_id == agent_id,
            AgentMcpToken.hidden.is_(True),
        )
    )
    tokens = list(result.scalars().all())
    for token in tokens:
        await db.delete(token)
    await db.commit()
    logger.info(
        "Revoked managed-runtime MCP tokens for agent {} (count={})",
        agent_id,
        len(tokens),
    )
    return len(tokens)


async def get_token_by_id(token_id: int, agent_id: int) -> Optional[AgentMcpToken]:
    """Get a token by ID, restricted to its owning agent."""
    db = get_db()
    result = await db.execute(
        select(AgentMcpToken).where(
            AgentMcpToken.id == token_id, AgentMcpToken.agent_id == agent_id
        )
    )
    return result.scalar_one_or_none()


async def get_enabled_token_by_value(agent_id: int, token_value: str) -> Optional[AgentMcpToken]:
    """Get an enabled agent token by plaintext value for authentication.

    Lookup uses SHA-256 because the plaintext value is encrypted at rest.
    """
    db = get_db()
    token_hash = hash_token(token_value)
    result = await db.execute(
        select(AgentMcpToken).where(
            AgentMcpToken.agent_id == agent_id,
            AgentMcpToken.token_hash == token_hash,
            AgentMcpToken.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_enabled_system_token_by_value(token_value: str) -> Optional[AgentMcpToken]:
    """Resolve an enabled managed-runtime token without knowing its agent first."""
    db = get_db()
    token_hash = hash_token(token_value)
    result = await db.execute(
        select(AgentMcpToken).where(
            AgentMcpToken.token_hash == token_hash,
            AgentMcpToken.enabled.is_(True),
            AgentMcpToken.hidden.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def create_token_for_agent(
    agent_id: int, data: Optional[AgentMcpTokenCreate] = None
) -> tuple[AgentMcpToken, str]:
    """Create a new MCP token for an agent.

    Returns:
        The database record and plaintext token. Plaintext is returned only here.
    """
    db = get_db()
    token_value = _generate_token_value()
    new_token = AgentMcpToken(
        agent_id=agent_id,
        label=data.label if data else None,
        token_encrypted=encrypt_value(token_value),
        token_hash=hash_token(token_value),
        enabled=data.enabled if data else True,
    )
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    logger.info("Created MCP token for agent {} (id={})", agent_id, new_token.id)
    return new_token, token_value


async def update_token(
    token_id: int, agent_id: int, data: AgentMcpTokenUpdate
) -> Optional[AgentMcpToken]:
    """Update an existing token's label or enabled state."""
    db = get_db()
    token = await get_token_by_id(token_id, agent_id)
    if not token:
        return None

    if data.label is not None:
        token.label = data.label
    if data.enabled is not None:
        token.enabled = data.enabled

    await db.commit()
    await db.refresh(token)
    logger.info("Updated MCP token {} for agent {}", token_id, agent_id)
    return token


async def delete_token(token_id: int, agent_id: int) -> bool:
    """Delete an MCP token."""
    db = get_db()
    token = await get_token_by_id(token_id, agent_id)
    if not token:
        return False

    await db.delete(token)
    await db.commit()
    logger.info("Deleted MCP token {} for agent {}", token_id, agent_id)
    return True
