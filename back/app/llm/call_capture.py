"""Opt-in inference capture, bound to the gateway's existing call identity."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from .embedded_runtime import EmbeddedInferenceOrigin


@dataclass(frozen=True)
class InferenceOwner:
    inference_id: UUID
    attempt_id: UUID
    token: UUID


inference_owner: ContextVar[InferenceOwner | None] = ContextVar("inference_owner", default=None)


@dataclass
class TextCallCapture:
    request: dict[str, Any]
    publish: Callable[[dict[str, Any]], Awaitable[None]]
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])
    call_id: UUID | None = None
    results: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    durable: bool = False
    structured: bool = False
    call_limit: int | None = None
    calls_started: int = 0
    call_ids: list[UUID] = field(default_factory=list[UUID])
    embedded_origin: EmbeddedInferenceOrigin | None = None


text_call_capture: ContextVar[TextCallCapture | None] = ContextVar(
    "text_call_capture", default=None
)
