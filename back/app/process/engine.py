"""Stable process-engine interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .schemas import (
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessStartPayload,
    ProcessEngineHealth,
)


class ProcessEngineError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ProcessEngine(Protocol):
    code: str
    supports_cancel: bool
    cancel_mode: str

    async def health(self) -> ProcessEngineHealth: ...

    async def sync_definitions(self) -> list[EngineProcessDefinition]: ...

    async def start_run(
        self,
        engine_process_id: str,
        run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult: ...

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot: ...

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot: ...


@runtime_checkable
class IntegratedProcessEngine(Protocol):
    """Optional admission contract for built-in operations with model configuration."""

    start_timeout_seconds: float
    refresh_timeout_seconds: float

    async def prepare_input(
        self, agent_id: int, workflow_id: str, input_data: dict[str, Any],
    ) -> dict[str, Any]: ...
