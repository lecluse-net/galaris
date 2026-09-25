from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import String, Text, ForeignKey, CHAR, LargeBinary, Boolean, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from core.util import normalize_html
from core.database import Base, HistoryMixin
from core.team import TeamModel as AgentGroup

if TYPE_CHECKING:
    from app.llm.profile_models import LlmProfile
    from app.skill.models import AgentSkill
    from core.user import UserModel as User


class AgentTeam(Base):
    """Agent membership in a shared team."""

    __tablename__ = "agent_teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("agent_id", "team_id"),)


class Title(Base):
    __tablename__ = "titles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    gender: Mapped[str] = mapped_column(CHAR(1), nullable=False)

    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="title")


class Agent(HistoryMixin, Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_agents_user_id"),
        nullable=False,
        index=True,
    )
    memory_item_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "memory_items.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_agents_memory_item_id",
        ),
        nullable=True,
        unique=True,
        index=True,
    )
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id"), nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_groups.id"), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    profile_media_type: Mapped[str] = mapped_column(String(40), default="text/html", server_default="text/markdown")
    profile_legacy_source: Mapped[dict[str, str | None] | None] = mapped_column(JSONB, nullable=True)

    @validates("personality", "job_description")
    def validate_profile_html(self, key: str, value: str | None) -> str | None:
        self.profile_media_type = "text/html"
        return normalize_html(value) if value is not None else None

    personality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    agent_driver: Mapped[str] = mapped_column(String(50), nullable=False, default="internal", server_default="internal")
    # Only an OpenAI Messages selection references the reusable ``harnesses`` table.
    # Bridge selections and the local Pydantic AI Harness keep this column NULL;
    # ``agent_harnesses`` carries the bridge provider code and runtime state.
    task_harness_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "harnesses.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_agents_task_harness_id",
        ),
        nullable=True,
        index=True,
    )
    avatar: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    # Transient API flag populated without loading avatar bytes.
    has_avatar: bool = False
    team_ids: list[int] = []
    # Transient API flag evaluated against the authenticated human manager.
    is_owner: bool = False
    # ``None`` means that the agent follows the current shared profile.
    profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("llm_profiles.id", ondelete="SET NULL", name="fk_agents_profile_id"),
        nullable=True,
        index=True,
    )
    # Exact value emitted by the single Voice/TTS picker.
    voice: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True, unique=True)
    # Internal seed identity, deliberately absent from editable API schemas.
    # HistoryMixin retains it after deletion so defaults are never recreated.
    initialization_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
    # Contraction-only compatibility columns. No Agent API or service reads or writes
    # these values; bridge.hermes imports them only when a driver-owned row is missing.
    hermes_url: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    hermes_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hermes_model: Mapped[str] = mapped_column(String, nullable=False, default="hermes-agent", server_default="hermes-agent")
    hermes_use_galaris_llm: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    hermes_api_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    hermes_dashboard_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    hermes_dashboard_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    hermes_dashboard_username: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    hermes_dashboard_password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hermes_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hermes_compose: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hermes_mcp_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hermes_data_env: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    title: Mapped["Title"] = relationship("Title", back_populates="agents")
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
    )
    group: Mapped[Optional[AgentGroup]] = relationship(AgentGroup)
    skill_assignments: Mapped[list["AgentSkill"]] = relationship(
        "AgentSkill",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profile: Mapped[Optional["LlmProfile"]] = relationship("LlmProfile")
