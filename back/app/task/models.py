from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column, validates
from core.util import normalize_html
from sqlalchemy.sql import func
from core.database import Base, HistoryMixin
from app.agent.contracts import TaskMessage
import enum


class MessageListType(TypeDecorator[list[TaskMessage]]):
    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        if value is None:
            return None
        return [
            msg.model_dump(mode="json") if hasattr(msg, "model_dump") else msg
            for msg in value
        ]

    def process_result_value(self, value: Any, dialect: Any) -> list[TaskMessage] | None:  # noqa: ARG002
        if value is None:
            return None
        return [TaskMessage.model_validate(msg) for msg in value]

if TYPE_CHECKING:
    from app.agent.contracts import BriefingResult, DispatchResult, ExecutionResult
    from app.agent.models import Agent
    from app.goal.models import Goal



class TaskStatus(str, enum.Enum):
    """Possible task statuses, representing lifecycle phases only.

    ``status`` no longer means “suspended”: suspension is stored in ``Task.paused`` and
    ``data['pause_reasons']``. The status remains the **resume phase**. ``PAUSE`` is kept as
    a dead enum value so the PostgreSQL enum needs no destructive migration. Do not reuse it.
    """
    CREATE = "CREATE"
    PAUSE = "PAUSE"  # Deprecated; do not use. See Task.paused.

    DISPATCH = "DISPATCH"
    BRIEFING = "BRIEFING"
    EXEC = "EXEC"
    PLAN = "PLAN"

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class TaskAttemptStatus(str, enum.Enum):
    """Durable result of one scheduler action."""

    CLAIMED = "CLAIMED"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    RETRY = "RETRY"
    CANCELLED = "CANCELLED"
    WAITING_CHILDREN = "WAITING_CHILDREN"


class Task(HistoryMixin, Base):
    """Versioned task table."""
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    label: Mapped[str] = mapped_column(String(400), nullable=False)
    objective_media_type: Mapped[str] = mapped_column(String(40), default="text/html", server_default="text/markdown")
    objective_legacy_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    @validates("objective")
    def validate_objective_html(self, key: str, value: str | None) -> str | None:
        self.objective_media_type = "text/html"
        return normalize_html(value) if value is not None else None

    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), nullable=False, default=TaskStatus.CREATE, server_default=TaskStatus.CREATE.value)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    effort: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    # Overrides set at creation time: NULL means automatic dispatcher/profile choice.
    # forced_route ∈ {EXEC, PLAN} ; forced_effort ∈ {standard, high}.
    # reasoning_effort_override uses the canonical LLM reasoning-effort values.
    # The dispatcher honors an explicit choice without reassessing it.
    forced_route: Mapped[str | None] = mapped_column(String(10), nullable=True)
    forced_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reasoning_effort_override: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    # Automatically approve executor approval requests (for example Hermes) for this task
    # and its descendants, resolved by walking ancestors. The default is False, so requests
    # are sent through the messaging interaction flow.
    auto_approve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    goal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    topic_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_memory_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    requester_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    messenger_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Durable idempotency key for the canonical inbound Messenger admission that created this
    # Task.  A provider may redeliver the same remote event after any process restart; the
    # database, rather than a process-local cache, guarantees that such a redelivery cannot
    # create a second Task.
    messenger_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    message_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_group_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dispatch_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    briefing_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Server-owned observations. Keep Task.data=None semantics and client input intact.
    lifecycle_timing: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    messages: Mapped[list[TaskMessage] | None] = mapped_column(MessageListType, nullable=True)

    # Planning: a task may be the child of a planned task and carry its own plan, represented
    # as an ordered step tree plus a cursor. A step may contain nested steps or be a leaf.
    # plan = {"steps": [{"objective": str, "label": str, "steps": [...]}, ...], "cursor": int}
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True, index=True
    )
    # Continuation trace: task from which this task originates, such as delegation to a peer
    # or a messaging reply that extends an exchange. Unlike the planning hierarchy in
    # ``parent_id``, this is a causal link, often across different agents. Propagating the
    # parent through this link keeps the objective within one subtree.
    source_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True, index=True
    )
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Durable scheduler claim. An expired lease can be recovered after a crash without relying
    # on the in-memory registry of the process that started the action.
    lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Relationships
    agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[agent_id])
    goal: Mapped["Goal | None"] = relationship("Goal", foreign_keys=[goal_id])
    requester_agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[requester_agent_id])
    parent: Mapped["Task | None"] = relationship(
        "Task", remote_side=[id], foreign_keys=[parent_id], back_populates="children"
    )
    children: Mapped[list["Task"]] = relationship(
        "Task", foreign_keys=[parent_id], back_populates="parent"
    )
    attempts: Mapped[list["TaskAttempt"]] = relationship(
        "TaskAttempt", back_populates="task", cascade="all, delete-orphan"
    )

    # Optimistic ORM write-conflict detection. HTTP commands also compare the revision supplied
    # by the client so they can report an explicit 409 conflict.
    __mapper_args__ = {"version_id_col": revision}

    def get_dispatch_result(self) -> "DispatchResult | None":
        """Return ``dispatch_result`` as a Pydantic object."""
        if self.dispatch_result is None:
            return None
        from app.agent.contracts import DispatchResult
        return DispatchResult.model_validate(self.dispatch_result)

    def set_dispatch_result(self, result: "DispatchResult") -> None:
        """Store ``dispatch_result`` from a Pydantic object."""
        self.dispatch_result = result.model_dump()

    def get_briefing_result(self) -> "BriefingResult | None":
        """Return the latest briefing result as a Pydantic object."""
        if self.briefing_result is None:
            return None
        from app.agent.contracts import BriefingResult
        return BriefingResult.model_validate(self.briefing_result)

    def set_briefing_result(self, result: "BriefingResult") -> None:
        """Store the briefing result."""
        self.briefing_result = result.model_dump()

    def get_execution_result(self) -> "ExecutionResult | None":
        """Return ``execution_result`` as a Pydantic object."""
        if self.execution_result is None:
            return None
        from app.agent.contracts import ExecutionResult
        return ExecutionResult.model_validate(self.execution_result)

    def set_execution_result(self, result: "ExecutionResult") -> None:
        """Store ``execution_result`` from a Pydantic object."""
        self.execution_result = result.model_dump()


class TaskAmendment(Base):
    """Immutable audit record for an instruction merged into an existing Task."""

    __tablename__ = "task_amendments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_task_amendments_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    disposition: Mapped[str] = mapped_column(String(30), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped["Task"] = relationship("Task")


class TaskAttempt(Base):
    """Audit record for one scheduler action on a task."""

    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaskAttemptStatus.CLAIMED.value
    )
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    task: Mapped[Task] = relationship("Task", back_populates="attempts")
