"""Async-safe correlation scope for persisted LLM call traces."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


_correlation_ref: ContextVar[str | None] = ContextVar(
    "llm_call_correlation_ref",
    default=None,
)
_deep_session: ContextVar[UUID | None] = ContextVar("llm_deep_session", default=None)


def current_deep_session() -> UUID | None:
    return _deep_session.get()


@contextmanager
def deep_inference_scope(session_id: UUID) -> Generator[None]:
    token = _deep_session.set(session_id)
    try:
        yield
    finally:
        _deep_session.reset(token)


def current_llm_correlation_ref() -> str | None:
    """Return the application work reference attached to the current inference."""

    return _correlation_ref.get()


@contextmanager
def llm_correlation_scope(correlation_ref: str) -> Generator[None]:
    """Attach a stable application work reference to nested LLM calls."""

    normalized = correlation_ref.strip()
    if not normalized:
        raise ValueError("LLM correlation reference cannot be empty.")
    token = _correlation_ref.set(normalized)
    try:
        yield
    finally:
        _correlation_ref.reset(token)


__all__ = ["current_llm_correlation_ref", "llm_correlation_scope"]
