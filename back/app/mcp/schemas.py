"""Pydantic schemas for per-agent MCP tokens."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentMcpTokenBase(BaseModel):
    label: str | None = None
    enabled: bool = True


class AgentMcpTokenCreate(AgentMcpTokenBase):
    pass


class AgentMcpTokenUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class AgentMcpTokenResponse(BaseModel):
    id: int
    agent_id: int
    label: str | None
    token: str  # Masked (for example mcp_abc...xyz); plaintext is returned at creation only.
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentMcpTokenCreateResponse(BaseModel):
    """Creation response containing the plaintext token exactly once."""
    id: int
    agent_id: int
    label: str | None
    token: str  # Plaintext token; copy it immediately.
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
