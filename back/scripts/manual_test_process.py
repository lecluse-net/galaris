"""Self-cleaning process lifecycle scenario using FakeProcessEngine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import delete as sa_delete, select

from core.database import get_db, get_db_session
from core.database.model_loader import load_models
from app.agent.models import Agent
from app.process import ProcessEngineError, process_service, registry
from app.process.models import (
    ProcessDefinition,
    ProcessRun,
    ProcessRunEvent,
    ProcessStartJob,
)
from app.process.schemas import (
    ProcessCallbackEvent,
    ProcessDefinitionCreate,
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessEngineHealth,
    ProcessStartPayload,
)
from app.tools import ToolModel


class FlakyFakeEngine:
    code = "fake"
    supports_cancel = True
    cancel_mode = "supported"

    def __init__(self) -> None:
        self.attempts = 0

    async def health(self) -> ProcessEngineHealth:
        return ProcessEngineHealth(
            tool_code=self.code,
            status="healthy",
            reachable=True,
            authenticated=True,
            supports_cancel=True,
            cancel_mode="supported",
            message="Flaky test engine",
            checked_at=datetime.now(timezone.utc),
        )

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return []

    async def start_run(
        self,
        engine_process_id: str,
        run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult:
        self.attempts += 1
        if self.attempts == 1:
            raise ProcessEngineError("temporary_failure", "Temporary failure", retryable=True)
        return EngineStartResult(accepted=True, engine_run_id=f"flaky-{run.id}")

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        return EngineRunSnapshot(status="running", engine_run_id=run.engine_run_id)

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        return EngineRunSnapshot(status="cancelled", engine_run_id=run.engine_run_id)


async def main() -> None:
    workflow_id = f"manual-workflow-{uuid4().hex[:8]}"
    process_id: int | None = None
    tool_id: int | None = None
    created_tool = False
    run_id: UUID | None = None
    extra_run_ids: list[UUID] = []
    original_fake_engine = registry.get("fake")
    db = get_db()
    agent = (await db.execute(select(Agent).limit(1))).scalar_one_or_none()
    if agent is None:
        raise RuntimeError("The scenario requires at least one existing agent.")
    try:
        tool = (await db.execute(select(ToolModel).where(ToolModel.code == "fake"))).scalar_one_or_none()
        if tool is None:
            tool = ToolModel(code="fake", label="Fake", description="Internal test engine")
            db.add(tool)
            await db.flush()
            created_tool = True
        tool_id = tool.id
        registry.get(tool.code)
        process = await process_service.create_definition(ProcessDefinitionCreate(
            agent_id=agent.id,
            tool_id=tool.id,
            engine_process_id=workflow_id,
            label="Manual fake process",
        ))
        process_id = process.id
        first = await process_service.start_process(
            agent_id=agent.id,
            workflow_id=workflow_id,
            input_data={"value": "demo"},
            idempotency_key="manual-idempotency",
        )
        run_id = first.run_id
        page_rows, page_total = await process_service.paginate_runs(
            workflow_id=workflow_id,
            search=str(first.run_id)[:8],
            page=1,
            page_size=1,
        )
        assert page_total == 1
        assert [row.id for row in page_rows] == [first.run_id]
        empty_page, same_total = await process_service.paginate_runs(
            workflow_id=workflow_id,
            page=2,
            page_size=1,
        )
        assert same_total == 1 and empty_page == []
        second = await process_service.start_process(
            agent_id=agent.id,
            workflow_id=workflow_id,
            input_data={"value": "demo"},
            idempotency_key="manual-idempotency",
        )
        assert second.run_id == first.run_id and second.deduplicated
        await process_service.process_start_jobs()
        started = await process_service.get_run(first.run_id)
        assert started is not None and started.status == "running"
        try:
            await process_service.delete_run(started.id)
            raise AssertionError("An active run must not be deletable.")
        except ValueError:
            pass
        try:
            await process_service.receive_callback(
                started.id,
                "invalid-token",
                ProcessCallbackEvent(event_id="invalid", status="running"),
            )
            raise AssertionError("An unauthenticated callback must be rejected.")
        except PermissionError:
            pass
        completed, duplicate = await process_service.receive_callback(
            started.id,
            started.callback_token,
            ProcessCallbackEvent(
                event_id="manual-success",
                status="success",
                engine_run_id=started.engine_run_id,
                output={"result": "ok"},
            ),
        )
        assert completed.status == "success" and not duplicate
        same, duplicate = await process_service.receive_callback(
            started.id,
            started.callback_token,
            ProcessCallbackEvent(
                event_id="manual-success",
                status="success",
                engine_run_id=started.engine_run_id,
                output={"result": "ok"},
            ),
        )
        assert same.status == "success" and duplicate
        late, duplicate = await process_service.receive_callback(
            started.id,
            started.callback_token,
            ProcessCallbackEvent(event_id="manual-late", status="running"),
        )
        assert late.status == "success" and not duplicate
        detail = await process_service.get_run_detail(started.id)
        analysis = await process_service.analyze_run(started.id)
        assert detail is not None and detail.status == "success"
        assert detail.output == {"result": "ok"}
        assert analysis.success
        assert await process_service.delete_run(started.id)
        assert await process_service.get_run(started.id) is None
        run_id = None

        cancelled_response = await process_service.start_process(
            agent_id=agent.id,
            workflow_id=workflow_id,
            input_data={"value": "retry"},
            idempotency_key="manual-cancel",
        )
        extra_run_ids.append(cancelled_response.run_id)
        cancelled = await process_service.cancel_run(cancelled_response.run_id)
        assert cancelled.status == "cancelled"
        retried = await process_service.retry_run(cancelled.id)
        assert retried.run_id != cancelled.id
        extra_run_ids.append(retried.run_id)
        await process_service.process_start_jobs()
        retried_run = await process_service.get_run(retried.run_id)
        assert retried_run is not None and retried_run.status == "running"
        await process_service.receive_callback(
            retried_run.id,
            retried_run.callback_token,
            ProcessCallbackEvent(event_id="manual-retry-success", status="success"),
        )
        for extra_run_id in list(extra_run_ids):
            assert await process_service.delete_run(extra_run_id)
            extra_run_ids.remove(extra_run_id)

        flaky = FlakyFakeEngine()
        registry.register(flaky)
        flaky_response = await process_service.start_process(
            agent_id=agent.id,
            workflow_id=workflow_id,
            input_data={"value": "flaky"},
            idempotency_key="manual-flaky",
        )
        extra_run_ids.append(flaky_response.run_id)
        await process_service.process_start_jobs()
        flaky_run = await process_service.get_run(flaky_response.run_id)
        assert flaky_run is not None and flaky_run.status == "queued"
        flaky_job = (
            await db.execute(
                select(ProcessStartJob).where(ProcessStartJob.run_id == flaky_response.run_id)
            )
        ).scalar_one()
        assert flaky_job.attempts == 1 and flaky_job.status == "pending"
        flaky_job.available_at = datetime.now(timezone.utc)
        await db.commit()
        await process_service.process_start_jobs()
        flaky_run = await process_service.get_run(flaky_response.run_id)
        assert flaky_run is not None and flaky_run.status == "running" and flaky.attempts == 2
        await process_service.receive_callback(
            flaky_run.id,
            flaky_run.callback_token,
            ProcessCallbackEvent(event_id="manual-flaky-success", status="success"),
        )
        assert await process_service.delete_run(flaky_run.id)
        extra_run_ids.remove(flaky_run.id)
        registry.register(original_fake_engine)
        logger.success(
            "Process scenario validated and run deleted run={} events={}",
            started.id,
            len(detail.events),
        )
    finally:
        registry.register(original_fake_engine)
        for extra_run_id in extra_run_ids:
            await db.execute(sa_delete(ProcessRunEvent).where(ProcessRunEvent.run_id == extra_run_id))
            await db.execute(sa_delete(ProcessStartJob).where(ProcessStartJob.run_id == extra_run_id))
            await db.execute(sa_delete(ProcessRun).where(ProcessRun.id == extra_run_id))
        if run_id is not None:
            await db.execute(sa_delete(ProcessRunEvent).where(ProcessRunEvent.run_id == run_id))
            await db.execute(sa_delete(ProcessStartJob).where(ProcessStartJob.run_id == run_id))
            await db.execute(sa_delete(ProcessRun).where(ProcessRun.id == run_id))
        if process_id is not None:
            await db.execute(sa_delete(ProcessDefinition).where(ProcessDefinition.id == process_id))
        if created_tool and tool_id is not None:
            await db.execute(sa_delete(ToolModel).where(ToolModel.id == tool_id))
        await db.commit()


if __name__ == "__main__":
    async def _standalone() -> None:
        load_models()
        async with get_db_session():
            await main()

    asyncio.run(_standalone())
