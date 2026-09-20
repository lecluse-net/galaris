"""Classify n8n HTTP errors for the outbox retry policy."""

from __future__ import annotations

from app.process import ProcessEngineError


class N8NError(ProcessEngineError):
    pass


def from_http_status(status_code: int, message: str) -> N8NError:
    if status_code == 429:
        return N8NError("rate_limited", message, retryable=True)
    if status_code in {502, 503, 504}:
        return N8NError("engine_unreachable", message, retryable=True)
    if status_code in {401, 403}:
        return N8NError("unauthorized", message, retryable=False)
    if status_code == 404:
        return N8NError("not_found", message, retryable=False)
    if status_code in {400, 409, 422}:
        return N8NError("invalid_request", message, retryable=False)
    return N8NError("n8n_http_error", message, retryable=status_code >= 500)


def network_error(error: Exception) -> N8NError:
    return N8NError("engine_unreachable", str(error), retryable=True)
