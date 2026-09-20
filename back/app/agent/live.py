"""Ephemeral live-run fanout independent from durable Task persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from loguru import logger

from .contracts import AIMessage, ExecutionResult


class AgentLiveEvent(BaseModel):
    """Bounded event for monitoring; token deltas are intentionally not persisted."""

    task_id: UUID
    run_id: UUID
    attempt_id: UUID | None = None
    sequence: int = Field(ge=0)
    kind: Literal["started", "message", "result", "failed", "cancelled"]
    message: AIMessage | None = None
    result: ExecutionResult | None = None

    @model_validator(mode="after")
    def canonical_payload_matches_kind(self) -> "AgentLiveEvent":
        if self.kind == "message" and self.message is None:
            raise ValueError("A live message event must contain an AIMessage.")
        if self.kind != "message" and self.message is not None:
            raise ValueError("Only a live message event may contain an AIMessage.")
        terminal = self.kind in {"result", "failed", "cancelled"}
        if terminal and self.result is None:
            raise ValueError("A terminal live event must contain an ExecutionResult.")
        if not terminal and self.result is not None:
            raise ValueError("Only a terminal live event may contain an ExecutionResult.")
        return self


type AgentLiveListener = Callable[[AgentLiveEvent], Awaitable[None]]

_listeners: list[AgentLiveListener] = []


def register_live_listener(listener: AgentLiveListener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


async def publish_live_event(event: AgentLiveEvent) -> None:
    for listener in tuple(_listeners):
        try:
            await listener(event)
        except Exception:
            logger.exception(
                "Agent live listener failed: task={} run={} sequence={}",
                event.task_id,
                event.run_id,
                event.sequence,
            )


__all__ = ["AgentLiveEvent", "publish_live_event", "register_live_listener"]
