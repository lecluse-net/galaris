"""Lab-owned real-process campaigns; execution state stays in app.process."""

from typing import Any
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, CheckConstraint, text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class LabProcessCampaign(HistoryMixin, Base):
    __tablename__ = "lab_process_campaigns"
    __table_args__ = (UniqueConstraint("owner_agent_id", "invocation_key"),
        CheckConstraint("num_nonnulls(dataset_id, dataset_document_id) = 1", name="ck_lab_process_campaign_dataset_source"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    dataset_id: Mapped[UUID | None] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"))
    # Existing campaigns retain their original FK during the additive transition.
    # New campaigns exclusively reference the native Dataset column above.
    dataset_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    process_code: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(300))
    invocation_key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="running", server_default="running")
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LabProcessCase(HistoryMixin, Base):
    __tablename__ = "lab_process_cases"
    __table_args__ = (UniqueConstraint("campaign_id", "position"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("lab_process_campaigns.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column()
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("process_runs.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
