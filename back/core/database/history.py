from typing import Optional, Any, TYPE_CHECKING
from datetime import datetime
from sqlalchemy.orm import relationship, declared_attr, with_loader_criteria, Session
from sqlalchemy import DateTime, Integer, ForeignKey, event
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

if TYPE_CHECKING:
    from sqlalchemy.orm import Mapper


# HistoryMixin: table history management

from sqlalchemy.orm import declarative_mixin

@declarative_mixin
class HistoryMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    @declared_attr
    def creator(cls) -> Mapped[Any]:
        # Delay __table__ access with a lambda.
        return relationship("User", foreign_keys=lambda: [cls.__table__.c.created_by])  # type: ignore[attr-defined]

    @declared_attr
    def updater(cls) -> Mapped[Any]:
        # Delay __table__ access with a lambda.
        return relationship("User", foreign_keys=lambda: [cls.__table__.c.updated_by])  # type: ignore[attr-defined]

    @classmethod
    def histo_filter(cls, query: Any) -> Any:
        """Filter query to exclude soft-deleted records."""
        return query.where(cls.deleted_at.is_(None))

    def soft_delete(self) -> None:
        """Mark record as deleted."""
        self.deleted_at = func.now()  # type: ignore[assignment]
        self.deleted_by = HistoryMixin._get_current_user_id()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None
        self.deleted_by = None

    @property
    def is_historized(self) -> bool:
        """Check if record is soft-deleted (historized)."""
        return self.deleted_at is not None

    @staticmethod
    def _get_current_user_id() -> Optional[int]:
        from core.user import user_service
        return user_service.get_current_user_id()

    @staticmethod
    def _before_insert(mapper: "Mapper[Any]", connection: Any, target: Any) -> None:
        user_id = HistoryMixin._get_current_user_id()
        if user_id:
            target.created_by = user_id
            target.updated_by = user_id

    @staticmethod
    def _before_update(mapper: "Mapper[Any]", connection: Any, target: Any) -> None:
        # Prevent updating 'updated_at'/'updated_by' if we are soft-deleting
        from sqlalchemy.orm import attributes
        hist = attributes.get_history(target, "deleted_at")
        
        # If deleted_at is changing and becoming Non-Null (Deletion)
        if hist.has_changes() and hist.added and hist.added[0] is not None:
             # Force updated_at to stay as is (suppress onupdate)
             if target.updated_at is not None:
                 target.updated_at = target.updated_at
                 attributes.flag_modified(target, "updated_at")
             return

        user_id = HistoryMixin._get_current_user_id()
        if user_id:
            target.updated_by = user_id

event.listen(HistoryMixin, 'before_insert', HistoryMixin._before_insert, propagate=True)  # type: ignore[attr-defined]
event.listen(HistoryMixin, 'before_update', HistoryMixin._before_update, propagate=True)  # type: ignore[attr-defined]

# Automatically filter soft-deleted records from all ORM queries. do_orm_execute
# is a synchronous Session event but also applies to ORM queries via AsyncSession.
@event.listens_for(Session, "do_orm_execute")  
def _auto_filter_historized(execute_state: Any) -> None: # type: ignore[unused-function]
    """
    Filter soft-deleted records from SELECT queries involving HistoryMixin models.
    
    This applies only to ORM queries, not Core SQL. Use
    ``execution_options(include_historized=True)`` to include deleted rows.
    """
    # Skip when explicitly disabled.
    if execute_state.execution_options.get("include_historized", False):
        return
    
    # Skip aggregation and mutation queries.
    if not execute_state.is_select:
        return
    
    # Skip Core SQL queries.
    if execute_state.is_from_statement:
        return
    
    # Add deleted_at IS NULL for every HistoryMixin model.
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            HistoryMixin,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True
        )
    )
