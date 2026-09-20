from typing import Optional
from sqlalchemy import ForeignKey, UniqueConstraint, Index, String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tool_id: Mapped[int] = mapped_column(ForeignKey("tools.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    active: Mapped[bool] = mapped_column(default=True)

    params: Mapped[list["ConnectionParam"]] = relationship(
        "ConnectionParam",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    function_states: Mapped[list["ConnectionFunctionState"]] = relationship(
        "ConnectionFunctionState",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("tool_id", "agent_id", name="uq_connection_agent_tool"),
    )


class ConnectionParam(Base):
    __tablename__ = "connection_params"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"),
        index=True
    )
    param_name: Mapped[str] = mapped_column(String(100), index=True)
    param_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    connection: Mapped["Connection"] = relationship("Connection", back_populates="params")

    __table_args__ = (
        UniqueConstraint("connection_id", "param_name", name="uq_connection_param"),
        Index("idx_conn_param_lookup", "param_name", "param_value"),
    )


class ConnectionFunctionState(Base):
    """Connection-level MCP function exposure override.

    This is the highest-priority authorization level. Missing rows inherit the tool-level state
    rather than denying access.
    """

    __tablename__ = "connection_function_state"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"),
        index=True
    )
    function_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    connection: Mapped["Connection"] = relationship("Connection", back_populates="function_states")

    __table_args__ = (
        UniqueConstraint("connection_id", "function_name", name="uq_connection_function"),
    )


class ToolFunctionState(Base):
    """Tool-level global MCP function exposure override.

    This state applies to every connection unless a connection-level override exists. Missing
    rows leave the function enabled by default.
    """

    __tablename__ = "tool_function_state"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"),
        index=True
    )
    function_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("tool_id", "function_name", name="uq_tool_function"),
    )
