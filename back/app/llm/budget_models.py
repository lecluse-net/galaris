"""Per-account spending policy and auditable credit requests and grants."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class InferenceBudget(Base):
    __tablename__ = "llm_user_budgets"
    __table_args__ = (
        CheckConstraint("referrer_user_id <> user_id", name="ck_llm_budget_other_referrer"),
        CheckConstraint("session_limit >= 0 AND weekly_limit >= 0 AND monthly_limit >= 0",
                        name="ck_llm_budget_nonnegative"),
        CheckConstraint("weekly_reset_hour BETWEEN 0 AND 167", name="ck_llm_budget_reset_hour"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Retain historical assignments during upgrade. Permissions now come from teams.
    referrer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    weekly_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    weekly_reset_hour: Mapped[int] = mapped_column(default=0, server_default="0")
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InferenceCreditRequest(Base):
    __tablename__ = "llm_credit_requests"
    __table_args__ = (
        CheckConstraint("period IN ('session', 'weekly', 'monthly')", name="ck_llm_credit_request_period"),
        CheckConstraint("amount > 0", name="ck_llm_credit_request_amount"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_llm_credit_request_status"),
        Index("uq_llm_credit_pending", "user_id", "period", unique=True,
              postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    period: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InferenceCreditGrant(Base):
    __tablename__ = "llm_credit_grants"
    __table_args__ = (
        CheckConstraint("period IN ('session', 'weekly', 'monthly')", name="ck_llm_credit_grant_period"),
        CheckConstraint("amount > 0", name="ck_llm_credit_grant_amount"),
        Index("ix_llm_credit_grant_window", "user_id", "period", "window_start"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_credit_requests.id", ondelete="SET NULL"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    granted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    period: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
