"""Async-safe correlation scope for persisted LLM call traces."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar


_correlation_ref: ContextVar[str | None] = ContextVar(
    "llm_call_correlation_ref",
    default=None,
)


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
