"""Small durable progress snapshots, fenced by the synchronization lease."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import UUID

from sqlalchemy import select, update

from core.database import get_db
from app.connection import Connection
from .contracts import CalendarSyncProgress, StaleSyncError
from .models import CalendarFeed, CalendarSyncRun
from .schemas import CalendarSyncProgressRead, CalendarSyncStepRead


def historical_progress(snapshot: dict[str, object]) -> dict[str, object]:
    """Keep the result counters, without the temporary execution timeline."""
    transient = {"steps", "network_phase", "transfer_completed", "transfer_total"}
    return {key: value for key, value in snapshot.items() if key not in transient}


class SyncProgressReporter:
    def __init__(self, calendar_id: int, run_id: UUID, token: UUID, revision: int, initial: dict[str, object]) -> None:
        self.calendar_id, self.run_id, self.token, self.revision = calendar_id, run_id, token, revision
        self.data = CalendarSyncProgressRead.model_validate(initial)
        self._received = self._sent = 0
        self._last_save = 0.0

    async def save(self, *, stage: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        lease = await get_db().scalar(update(CalendarFeed).where(CalendarFeed.id == self.calendar_id,
            CalendarFeed.lease_token == self.token, CalendarFeed.source_revision == self.revision,
            CalendarFeed.active.is_(True), CalendarFeed.lease_expires_at > now,
            CalendarFeed.connection_id.in_(select(Connection.id).where(Connection.active.is_(True))))
            .values(lease_expires_at=now + timedelta(minutes=5)).returning(CalendarFeed.id))
        if lease is None:
            raise StaleSyncError("Calendar synchronization progress lost its lease")
        values: dict[str, object] = {"progress": self.data.model_dump(mode="json")}
        if stage is not None:
            values["stage"] = stage
        await get_db().execute(update(CalendarSyncRun).where(CalendarSyncRun.id == self.run_id,
            CalendarSyncRun.state == "running").values(**values))
        await get_db().commit()
        self._last_save = monotonic()

    async def stage(self, stage: str) -> None:
        now = datetime.now(timezone.utc)
        if self.data.steps and self.data.steps[-1].finished_at is None:
            self.data.steps[-1].finished_at = now
        self.data.steps.append(CalendarSyncStepRead(stage=stage, started_at=now))
        self.data.steps = self.data.steps[-16:]
        self.data.network_phase = None
        await self.save(stage=stage)

    async def on_progress(self, event: CalendarSyncProgress) -> None:
        if event.phase == "connecting":
            self._received = self._sent = 0
            self.data.http_requests += 1
            self.data.transfer_completed, self.data.transfer_total = 0, None
        elif event.phase == "server_reached":
            self.data.server_reached = True
            self.data.last_http_status = event.http_status
        elif event.phase == "receiving":
            self.data.bytes_received += max(0, event.completed - self._received)
            self._received = event.completed
            self.data.transfer_completed, self.data.transfer_total = event.completed, event.total
        elif event.phase == "transmitting":
            self.data.bytes_sent += max(0, event.completed - self._sent)
            self._sent = event.completed
            self.data.transfer_completed, self.data.transfer_total = event.completed, event.total
        elif event.phase == "download":
            self.data.downloaded, self.data.download_total = event.completed, event.total
        elif event.phase == "discover":
            self.data.calendars = event.completed
        self.data.network_phase = event.phase
        if event.phase not in ("receiving", "transmitting") or monotonic() - self._last_save >= .25 or event.completed == event.total:
            await self.save()

    async def finish(self) -> None:
        await self.stage("complete")
        self.data.steps[-1].finished_at = datetime.now(timezone.utc)
        await self.save()
