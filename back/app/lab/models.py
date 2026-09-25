"""Persistent task references and diagnostics for the AI analysis Lab."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from core.database import Base, HistoryMixin


class LabTask(Base):
    """A task selected for analysis.

    The Lab deliberately owns no copy of the task payload or execution trace. PostgreSQL
    keeps those facts in their canonical domains and the analyzer reloads them on demand.
    """

    __tablename__ = "lab_tasks"

    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )


class LabTaskDiagnosis(HistoryMixin, Base):
    """Immutable structured diagnosis generated from live task evidence.

    The evidence dossier, task payload, and optional human context are deliberately not
    persisted as source material. Removing a task from ``lab_tasks`` does not remove its
    diagnosis history.
    """

    __tablename__ = "lab_task_diagnoses"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(500), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    evidence_coverage: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")

    __table_args__ = (
        Index(
            "ix_lab_task_diagnoses_task_created",
            "task_id",
            "created_at",
        ),
    )


class LabEvaluationDataset(HistoryMixin, Base):
    """A versioned collection of cases for one AI mechanism."""

    __tablename__ = "lab_evaluation_datasets"

    purpose: Mapped[Literal["work", "validation", "holdout"]] = mapped_column(
        String(20), nullable=False, default="work", server_default="work"
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    mechanism: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="dispatcher",
        server_default="dispatcher",
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    prompt_suffix: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )

    __mapper_args__ = {"version_id_col": revision}
    __table_args__ = (
        Index(
            "uq_lab_evaluation_datasets_active_name",
            "mechanism",
            "name",
            unique=True,
            postgresql_where=sql_text("deleted_at IS NULL"),
        ),
    )


class LabEvaluationCase(HistoryMixin, Base):
    """A tested value, its context and reference; experiment settings belong to its dataset."""

    __tablename__ = "lab_evaluation_cases"

    categories: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lab_evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    derived_from_case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lab_evaluation_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    source_task_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(400), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    readiness: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ready", server_default="ready", index=True
    )
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {"variable_value": ""},
        server_default=sql_text("""'{"variable_value": ""}'::jsonb"""),
    )

    @validates("input_data")
    def validate_input_data(self, _key: str, value: object) -> dict[str, Any]:
        from .contracts import LabInput

        return LabInput.model_validate(value).model_dump(mode="json")

    expected_output: Mapped[dict[str, Any] | list[Any] | str] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    reference: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    source_capture: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )

    __mapper_args__ = {"version_id_col": revision}
    __table_args__ = (Index("ix_lab_evaluation_cases_dataset_created", "dataset_id", "created_at"),)


class LabEvaluationRun(HistoryMixin, Base):
    """Durable execution of one frozen dataset against one configured LLM."""

    __tablename__ = "lab_evaluation_runs"

    requester_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    requester_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    requester_action: Mapped[str | None] = mapped_column(String(100), nullable=True)

    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default="execution", server_default="execution"
    )
    judged_cases: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    candidate_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    judge_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lab_evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    llm_id: Mapped[int | None] = mapped_column(
        ForeignKey("llms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    judge_llm_id: Mapped[int | None] = mapped_column(
        ForeignKey("llms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )
    score_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="dispatcher-score:v1",
        server_default="dispatcher-score:v1",
    )
    llm_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    judge_llm_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    case_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_cases: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    score_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    structured_score_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    analysis_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_llm_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    analysis_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    analysis_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    analysis_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_lab_evaluation_runs_dataset_created", "dataset_id", "created_at"),)


class LabEvaluationRunCase(HistoryMixin, Base):
    """Checkpointed result for one frozen case within an evaluation run."""

    __tablename__ = "lab_evaluation_run_cases"

    repetition: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lab_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lab_evaluation_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    case_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    actual_output: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(
        JSONB, nullable=True
    )
    score_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    judge_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    score_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    structured_score_percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "case_id", "repetition", name="uq_lab_evaluation_run_case_repetition"
        ),
        Index("ix_lab_evaluation_run_cases_run_created", "run_id", "created_at"),
    )


class LabJudgmentCampaign(HistoryMixin, Base):
    """One independent judgment pass over immutable candidate results."""

    __tablename__ = "lab_judgment_campaigns"

    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    judge_llm_id: Mapped[int | None] = mapped_column(
        ForeignKey("llms.id", ondelete="SET NULL"), nullable=True
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_lab_judgment_campaign_sequence"),
    )


class LabJudgmentResult(HistoryMixin, Base):
    """An immutable judgment attempt; retries create a new campaign."""

    __tablename__ = "lab_judgment_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_judgment_campaigns.id", ondelete="CASCADE"), index=True
    )
    result_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_evaluation_run_cases.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    score_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("campaign_id", "result_id", name="uq_lab_judgment_campaign_result"),
    )


class LabHumanReview(HistoryMixin, Base):
    """An independent human assessment, pinned to a judgment campaign."""

    __tablename__ = "lab_human_reviews"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    result_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_evaluation_run_cases.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_judgment_campaigns.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score_percent: Mapped[float] = mapped_column(Float, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("campaign_id", "result_id", "reviewer_id", name="uq_lab_human_review"),
    )


class LabCommand(HistoryMixin, Base):
    """Atomic command receipt and attributable agent audit, without user impersonation."""

    __tablename__ = "lab_commands"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    invocation_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("agent_id", "action", "invocation_key", name="uq_lab_command"),)


class LabAgentReview(HistoryMixin, Base):
    """Agent assessment, never counted as a human review or automatic judgment."""

    __tablename__ = "lab_agent_reviews"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    result_id: Mapped[UUID] = mapped_column(ForeignKey("lab_evaluation_run_cases.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("lab_judgment_campaigns.id", ondelete="CASCADE"), index=True)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    score_percent: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("agent_id", "campaign_id", "result_id", name="uq_lab_agent_review"),)


class LabOperationResult(HistoryMixin, Base):
    """Full result published atomically with the effects of an integrated Process."""

    __tablename__ = "lab_operation_results"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    process_run_id: Mapped[UUID] = mapped_column(ForeignKey("process_runs.id", ondelete="CASCADE"), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
