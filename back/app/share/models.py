"""Exclusive resource policies and their common grant storage."""

from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from core.database import Base, HistoryMixin


class ShareConfig(HistoryMixin, Base):
    __tablename__ = "share_configs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_kind: Mapped[str] = mapped_column(String(30))
    global_access: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Preserved live owner-group semantics for older policies. New forms use
    # explicit team grants, whose memberships remain live as well.
    group_access: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    legacy_acl_hash: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("id", "resource_kind"),
        CheckConstraint(
            "resource_kind IN ('document','dataset','process')",
            name="ck_share_configs_kind",
        ),
        CheckConstraint(
            "global_access IN (0,1,2) AND group_access IN (0,1,2)", name="ck_share_configs_access"
        ),
        CheckConstraint("revision > 0", name="ck_share_configs_revision"),
    )


class ShareGrant(Base):
    __tablename__ = "share_grants"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    share_id: Mapped[UUID] = mapped_column(
        ForeignKey("share_configs.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True
    )
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(agent_id,user_id,team_id) = 1", name="ck_share_grants_principal"
        ),
        UniqueConstraint("share_id", "agent_id"),
        UniqueConstraint("share_id", "user_id"),
        UniqueConstraint("share_id", "team_id"),
    )


class ShareReference:
    """Typed, exclusive policy reference; business ownership stays in its domain."""

    __share_kind__: ClassVar[str]
    id: Mapped[Any]

    share_id: Mapped[UUID] = mapped_column(
        ForeignKey("share_configs.id", ondelete="RESTRICT"), unique=True
    )
    share_kind: Mapped[str] = mapped_column(String(30))

    @declared_attr
    @classmethod
    def share(cls) -> Mapped[ShareConfig]:
        return relationship(
            ShareConfig, foreign_keys=f"{cls.__name__}.share_id", lazy="joined", innerjoin=True
        )

    @classmethod
    def share_for(cls, identity: object) -> ColumnElement[UUID]:
        """Public SQL projection for resource-scoped joins and bulk mutations."""
        return select(cls.share_id).where(cls.id == identity).scalar_subquery()

    @staticmethod
    def share_constraints(table: str, kind: str) -> tuple[ForeignKeyConstraint, CheckConstraint]:
        return (
            ForeignKeyConstraint(
                ["share_id", "share_kind"],
                ["share_configs.id", "share_configs.resource_kind"],
                name=f"fk_{table}_share_kind",
                deferrable=True,
                initially="DEFERRED",
            ),
            CheckConstraint(f"share_kind = '{kind}'", name=f"ck_{table}_share_kind"),
        )

    @hybrid_property
    def global_access(self) -> int:
        return self.share.global_access

    @global_access.inplace.setter
    def _global_access_set(self, value: int) -> None:
        self.share.global_access = value

    @global_access.inplace.expression
    @classmethod
    def _global_access_expression(cls) -> ColumnElement[int]:
        return (
            select(ShareConfig.global_access)
            .where(ShareConfig.id == cls.share_id)
            .scalar_subquery()
        )

    @hybrid_property
    def group_access(self) -> int:
        return self.share.group_access

    @group_access.inplace.setter
    def _group_access_set(self, value: int) -> None:
        self.share.group_access = value

    @group_access.inplace.expression
    @classmethod
    def _group_access_expression(cls) -> ColumnElement[int]:
        return (
            select(ShareConfig.group_access).where(ShareConfig.id == cls.share_id).scalar_subquery()
        )


class Shareable(ShareReference):
    def __init__(self, **kwargs: Any) -> None:
        kind = kwargs.pop("share_kind", self.__share_kind__)
        config = kwargs.pop("share", None)
        if config is None:
            config = ShareConfig(
                id=kwargs.pop("share_id", None) or uuid4(),
                resource_kind=kind,
                global_access=0,
                group_access=0,
                revision=1,
            )
        # SQLAlchemy supplies the final mapped constructor through this mixin.
        super().__init__(share=config, share_id=config.id, share_kind=kind, **kwargs)  # pyright: ignore[reportCallIssue]
