"""Durable checkpoints for business-process engines."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.database import get_db
from . import process_service
from .models import ProcessRun


async def engine_checkpoint(
    run_id: UUID, engine_code: str, values: dict[str, Any] | None = None,
    *, claim: str | None = None, immutable_values: dict[str, Any] | None = None,
    preserve_if: dict[str, Any] | None = None,
    expected_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = (await get_db().execute(select(ProcessRun).where(
        ProcessRun.id == run_id, ProcessRun.engine_code == engine_code,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    preserved = bool(preserve_if) and any(
        run.engine_metadata.get(key) == value for key, value in (preserve_if or {}).items()
    )
    if expected_values is not None and any(
        run.engine_metadata.get(key) != value for key, value in expected_values.items()
    ):
        preserved = True
    # Identity validation still applies when a duplicate observation is ignored.
    if immutable_values and run.status not in process_service.TERMINAL_STATUSES:
        for key, value in immutable_values.items():
            if key in run.engine_metadata and run.engine_metadata[key] != value:
                raise ValueError(f"The durable checkpoint field {key} cannot change")
    if preserved:
        values = None
        immutable_values = None
        claim = None
    if immutable_values and run.status not in process_service.TERMINAL_STATUSES:
        run.engine_metadata = {**run.engine_metadata, **immutable_values}
    claimed = claim is not None and not run.engine_metadata.get(claim) and run.status not in process_service.TERMINAL_STATUSES
    if claimed and claim is not None:
        run.engine_metadata = {**run.engine_metadata, claim: "started"}
    if values is not None and run.status not in process_service.TERMINAL_STATUSES:
        run.engine_metadata = {**run.engine_metadata, **values}
    result: dict[str, Any] = {
        "agent_id": run.launcher_agent_id, "task_id": run.task_id,
        "input": dict(run.input), "metadata": dict(run.engine_metadata),
        "terminal": run.status in process_service.TERMINAL_STATUSES,
        "claimed": claimed,
        "applied": not preserved and run.status not in process_service.TERMINAL_STATUSES,
    }
    await get_db().commit()
    return result
