"""Shared failure semantics for drivers, persistence and retry admission."""

import asyncio
import httpx

from .contracts import AgentDriverError, HarnessFailure


class HarnessExecutionError(AgentDriverError):
    def __init__(self, failure: HarnessFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


class HarnessProtocolError(HarnessExecutionError, ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(HarnessFailure(code="protocol", message=message, retry="never"))


class HarnessCheckpointError(HarnessExecutionError, ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(HarnessFailure(code="effect_unknown", message=message, retry="never"))


def classify_execution_error(exc: BaseException) -> HarnessFailure:
    if isinstance(exc, HarnessExecutionError):
        return exc.failure
    message = f"{type(exc).__name__}: {exc}"[:4000]
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        code = "quota" if status == 429 else "configuration" if status in {400, 401, 403, 404, 422} else "unavailable"
        return HarnessFailure(
            code=code, message=f"Harness HTTP request failed ({status}).",
            retry="never" if code == "configuration" else "reconcile",
        )
    if isinstance(exc, httpx.TimeoutException):
        return HarnessFailure(code="timeout", message="Harness transport timed out.", retry="reconcile")
    if isinstance(exc, httpx.TransportError):
        return HarnessFailure(code="unavailable", message="Harness transport failed.", retry="reconcile")
    if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
        return HarnessFailure(code="cancelled", message=message)
    if isinstance(exc, TimeoutError):
        return HarnessFailure(code="timeout", message=message, retry="reconcile")
    if isinstance(exc, ConnectionError):
        return HarnessFailure(code="unavailable", message=message, retry="reconcile")
    if isinstance(exc, AgentDriverError):
        return HarnessFailure(code="configuration", message=message, effects="none")
    return HarnessFailure(code="runtime", message=message, retry="reconcile")
