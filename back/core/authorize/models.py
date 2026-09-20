from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base, HistoryMixin

if TYPE_CHECKING:
    from core.user.models import User


class RolePrivilege(Base):
    __tablename__ = "role_privileges"

    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    privilege_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("privileges.id", ondelete="CASCADE"), primary_key=True
    )


class Privilege(Base):
    __tablename__ = "privileges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    privilege_list_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("privilege_lists.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships use __table__ for the SQLAlchemy Table object.
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary=RolePrivilege.__table__, back_populates="privileges"
    )
    privilege_list: Mapped[Optional["PrivilegeList"]] = relationship(
        "PrivilegeList", back_populates="privileges"
    )


class PrivilegeList(Base):
    __tablename__ = "privilege_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Relationships
    privileges: Mapped[List["Privilege"]] = relationship(
        "Privilege", back_populates="privilege_list"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # Relationships use __table__ for the SQLAlchemy Table object.
    privileges: Mapped[List["Privilege"]] = relationship(
        "Privilege", secondary=RolePrivilege.__table__, back_populates="roles"
    )
    assignments: Mapped[List["Assignment"]] = relationship(
        "Assignment", back_populates="role"
    )


class Assignment(HistoryMixin, Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Unique constraint: user can only have each role once
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="assignments")
    user: Mapped["User"] = relationship(
        "core.user.models.User", foreign_keys=[user_id]
    )
