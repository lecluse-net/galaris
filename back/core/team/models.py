"""Shared teams. The historical table name preserves existing group identities."""

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class Team(HistoryMixin, Base):
    __tablename__ = "agent_groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    order: Mapped[int] = mapped_column(default=0, server_default="0")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")


class TeamUser(Base):
    __tablename__ = "team_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)


class TeamAudit(HistoryMixin, Base):
    __tablename__ = "team_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
