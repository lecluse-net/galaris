"""SQLAlchemy model for per-agent MCP access tokens.

Each agent exposes a unified Streamable HTTP MCP server and may own several
tokens for rotation or distinct clients. Tokens are encrypted at rest; a
SHA-256 hash enables authentication lookup without storing plaintext.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Boolean, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AgentMcpToken(Base):
    __tablename__ = "agent_mcp_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    # Hidden system token used by a managed runtime to authenticate with agent MCP.
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def token(self) -> str:
        """Return a masked display value; the actual token stays encrypted."""
        from core.util.encryption import decrypt_value
        try:
            plain = decrypt_value(self.token_encrypted)
            if len(plain) <= 20:
                return plain
            return f"{plain[:8]}...{plain[-8:]}"
        except Exception:
            return "mcp_***...***"
