"""Database index and agent assignments for filesystem skills."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from core.database import Base, HistoryMixin

if TYPE_CHECKING:
    from app.agent.models import Agent


class SkillCategory(HistoryMixin, Base):
    """User-managed category shared by zero or more skills."""

    __tablename__ = "skill_categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        back_populates="category",
        passive_deletes=True,
    )
    authorizations: Mapped[list["AgentSkillCategory"]] = relationship(
        "AgentSkillCategory",
        back_populates="category",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Skill(HistoryMixin, Base):
    """Metadata for a user-managed or bundled system skill."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    global_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("skill_categories.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        default=None,
    )

    category: Mapped[Optional[SkillCategory]] = relationship(
        "SkillCategory",
        back_populates="skills",
    )

    assignments: Mapped[list["AgentSkill"]] = relationship(
        "AgentSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentSkill(Base):
    """Activation setting for one library skill and one compatible agent.

    ``active`` is nullable on purpose: ``None`` inherits the agent's category
    override when present, then the skill's global setting. ``True`` and
    ``False`` are explicit agent overrides.
    """

    __tablename__ = "agent_skills"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)

    agent: Mapped["Agent"] = relationship(
        "app.agent.models.Agent", back_populates="skill_assignments"
    )
    skill: Mapped[Skill] = relationship("Skill", back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill"),
    )


class AgentSkillCategory(Base):
    """Activation setting for one skill category and one compatible agent."""

    __tablename__ = "agent_skill_categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("skill_categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)

    category: Mapped[SkillCategory] = relationship(
        "SkillCategory",
        back_populates="authorizations",
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "category_id",
            name="uq_agent_skill_category",
        ),
    )


class LearnedSkill(HistoryMixin, Base):
    """Agent-scoped procedure learned from independently auditable outcomes."""

    __tablename__ = "learned_skills"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    positive_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    negative_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    suspended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_evidence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    evidences: Mapped[list["LearnedSkillEvidence"]] = relationship(
        "LearnedSkillEvidence",
        back_populates="skill",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LearnedSkillEvidence.created_at",
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "code", name="uq_learned_skill_agent_code"),
        CheckConstraint(
            "revision >= 1 AND evidence_count >= 0",
            name="ck_learned_skill_counts",
        ),
        CheckConstraint(
            "positive_weight >= 0 AND negative_weight >= 0 AND score >= 0 AND score <= 1",
            name="ck_learned_skill_score",
        ),
        Index("ix_learned_skill_injection", "agent_id", "suspended", "score"),
    )


class LearnedSkillEvidence(Base):
    """One idempotent positive or negative reinforcement of a learned skill."""

    __tablename__ = "learned_skill_evidences"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    learned_skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("learned_skills.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    polarity: Mapped[str] = mapped_column(String(10), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    skill: Mapped[LearnedSkill] = relationship(
        "LearnedSkill", back_populates="evidences"
    )

    __table_args__ = (
        UniqueConstraint(
            "learned_skill_id",
            "source_fingerprint",
            name="uq_learned_skill_evidence_source",
        ),
        CheckConstraint(
            "operation IN ('CREATE', 'REINFORCE', 'REVISE', 'WEAKEN')",
            name="ck_learned_skill_evidence_operation",
        ),
        CheckConstraint(
            "polarity IN ('positive', 'negative')",
            name="ck_learned_skill_evidence_polarity",
        ),
        CheckConstraint(
            "weight > 0 AND confidence >= 0 AND confidence <= 1",
            name="ck_learned_skill_evidence_weight",
        ),
    )
