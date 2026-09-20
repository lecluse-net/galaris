"""Persistent models for long-running agent goals and their execution cycles."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.connection.models import Connection
from core.database import Base, HistoryMixin

if TYPE_CHECKING:
    from app.agent.models import Agent
    from app.llm.provider_models import LLM
    from app.task.models import Task


class GoalStatus(str, enum.Enum):
    """Operational lifecycle of a long-running goal."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class GoalCycleStatus(str, enum.Enum):
    """Durable state of one task-and-judgement goal cycle."""

    RUNNING = "RUNNING"
    JUDGING = "JUDGING"
    DECIDED = "DECIDED"
    ERROR = "ERROR"


class GoalVerdict(str, enum.Enum):
    """The only two semantic outcomes of a post-task goal judgement."""

    CONTINUE = "CONTINUE"
    STOP = "STOP"


class GoalCycleTriggerKind(str, enum.Enum):
    """Durable provenance of a Goal cycle."""

    TEMPORAL = "TEMPORAL"
    RELATIONAL = "RELATIONAL"
    MANUAL = "MANUAL"


class GoalReferrerType(str, enum.Enum):
    """Identity family of the person who assigned a Goal."""

    AGENT = "AGENT"
    MESSENGER = "MESSENGER"


class Goal(HistoryMixin, Base):
    """A durable objective repeatedly advanced by ordinary agent tasks."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(
            "cycle_delay_seconds IS NULL OR cycle_delay_seconds >= 0",
            name="ck_goals_cycle_delay_non_negative",
        ),
        CheckConstraint(
            "referrer_max_reminders >= 0",
            name="ck_goals_referrer_max_reminders_non_negative",
        ),
        CheckConstraint(
            "description_document_id <> tracking_document_id",
            name="ck_goals_distinct_markdown_documents",
        ),
        CheckConstraint(
            "(referrer_type IS NULL AND referrer_agent_id IS NULL "
            "AND referrer_connection_id IS NULL AND referrer_user_id IS NULL) OR "
            "(referrer_type = 'AGENT' AND referrer_agent_id IS NOT NULL "
            "AND referrer_connection_id IS NULL AND referrer_user_id IS NULL) OR "
            "(referrer_type = 'MESSENGER' AND referrer_agent_id IS NULL "
            "AND referrer_user_id IS NOT NULL)",
            name="ck_goals_referrer_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4, index=True
    )
    memory_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "memory_items.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_goals_memory_item_id",
        ),
        nullable=True,
        unique=True,
        index=True,
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_goal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    requester_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    referrer_type: Mapped[GoalReferrerType | None] = mapped_column(
        SQLEnum(GoalReferrerType), nullable=True, index=True
    )
    referrer_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    referrer_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    referrer_user_id: Mapped[str | None] = mapped_column(String(400), nullable=True)
    referrer_display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    referrer_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    description_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "memory_items.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_goals_description_document_id",
        ),
        nullable=False,
        unique=True,
        index=True,
    )
    tracking_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "memory_items.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_goals_tracking_document_id",
        ),
        nullable=False,
        unique=True,
        index=True,
    )
    cycle_delay_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=3600, server_default="3600"
    )
    schedule_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=sql_text("false")
    )
    schedule: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    referrer_max_reminders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[GoalStatus] = mapped_column(
        SQLEnum(GoalStatus),
        nullable=False,
        default=GoalStatus.ACTIVE,
        server_default=GoalStatus.ACTIVE.value,
        index=True,
    )
    next_cycle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    manual_run_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pause_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A soft-deleted owner is hidden by the global history filter. Keep the runtime type honest
    # so Goal supervision can remain readable and stop future cycles cleanly.
    agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[agent_id])
    parent: Mapped["Goal | None"] = relationship(
        "Goal",
        remote_side="Goal.id",
        back_populates="children",
        foreign_keys=[parent_goal_id],
    )
    children: Mapped[list["Goal"]] = relationship(
        "Goal",
        back_populates="parent",
        foreign_keys="Goal.parent_goal_id",
    )
    referrer_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[referrer_agent_id]
    )
    referrer_connection: Mapped["Connection | None"] = relationship(
        Connection, foreign_keys=[referrer_connection_id]
    )
    cycles: Mapped[list["GoalCycle"]] = relationship(
        "GoalCycle",
        back_populates="goal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __mapper_args__ = {"version_id_col": revision}


class GoalCycle(Base):
    """One task created for a goal followed by a CONTINUE/STOP judgement."""

    __tablename__ = "goal_cycles"
    __table_args__ = (
        UniqueConstraint("goal_id", "sequence", name="uq_goal_cycle_sequence"),
        UniqueConstraint(
            "goal_id", "source_cycle_id", name="uq_goal_cycle_relational_source"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    memory_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "memory_items.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_goal_cycles_memory_item_id",
        ),
        nullable=True,
        unique=True,
        index=True,
    )
    goal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_kind: Mapped[GoalCycleTriggerKind] = mapped_column(
        SQLEnum(GoalCycleTriggerKind),
        nullable=False,
        default=GoalCycleTriggerKind.TEMPORAL,
        server_default=GoalCycleTriggerKind.TEMPORAL.value,
        index=True,
    )
    source_cycle_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goal_cycles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    status: Mapped[GoalCycleStatus] = mapped_column(
        SQLEnum(GoalCycleStatus),
        nullable=False,
        default=GoalCycleStatus.RUNNING,
        server_default=GoalCycleStatus.RUNNING.value,
        index=True,
    )
    verdict: Mapped[GoalVerdict | None] = mapped_column(
        SQLEnum(GoalVerdict), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_changed: Mapped[bool | None] = mapped_column(nullable=True)
    progress_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    continuation_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    task_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    judge_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    judge_llm_id: Mapped[int | None] = mapped_column(
        ForeignKey("llms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    judge_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    judge_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    judge_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    goal: Mapped[Goal] = relationship("Goal", back_populates="cycles")
    task: Mapped["Task | None"] = relationship("Task", foreign_keys=[task_id])
    judge_llm: Mapped["LLM | None"] = relationship("LLM", foreign_keys=[judge_llm_id])

    def clear_lease(self) -> None:
        """Release the durable judge claim after a terminal outcome."""

        self.lease_token = None
        self.lease_owner = None
        self.lease_expires_at = None


class GoalCycleTrigger(Base):
    """One idempotent wake-up produced by a completed parent Goal cycle."""

    __tablename__ = "goal_cycle_triggers"
    __table_args__ = (
        UniqueConstraint(
            "goal_id", "source_cycle_id", name="uq_goal_cycle_trigger_source"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    goal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_cycle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goal_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consumed_cycle_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goal_cycles.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
