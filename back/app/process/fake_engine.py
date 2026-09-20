"""Deterministic in-memory engine for tests and core development."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.i18n import tr

from .schemas import (
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessStartPayload,
    ProcessEngineHealth,
)


class FakeProcessEngine:
    code = "fake"
    supports_cancel = True
    cancel_mode = "supported"

    def __init__(self) -> None:
        self.snapshots: dict[str, EngineRunSnapshot] = {}

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return []

    async def health(self) -> ProcessEngineHealth:
        return ProcessEngineHealth(
            tool_code=self.code,
            status="healthy",
            reachable=True,
            authenticated=True,
            supports_cancel=True,
            cancel_mode="supported",
            message=await tr("process.fake_engine_available"),
            checked_at=datetime.now(timezone.utc),
        )

    async def start_run(
        self,
        engine_process_id: str,
        run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult:
        engine_run_id = f"fake-{uuid4().hex[:12]}"
        self.snapshots[str(run.id)] = EngineRunSnapshot(
            status="running", engine_run_id=engine_run_id, raw={"accepted": True}
        )
        return EngineStartResult(accepted=True, engine_run_id=engine_run_id)

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        return self.snapshots.get(
            str(run.id),
            EngineRunSnapshot(status="unknown", engine_run_id=run.engine_run_id),
        )

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        snapshot = EngineRunSnapshot(status="cancelled", engine_run_id=run.engine_run_id)
        self.snapshots[str(run.id)] = snapshot
        return snapshot
