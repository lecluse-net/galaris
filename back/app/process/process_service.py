"""Business-process logic independent from concrete process engines."""

from __future__ import annotations

from collections.abc import Collection
import asyncio
import hashlib
import json
import mimetypes
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence, cast
from uuid import UUID, uuid4

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import DateTime, String, case, cast as sa_cast, func, or_, select, true
from sqlalchemy.exc import IntegrityError

from core import settings, websocket
from core.database import get_db
from core.util import BufferedAdmissionDeferred
from core.i18n import render_prompt, tr
from core.params import runtime_settings
from app.tools import ToolModel

from . import metrics, registry
from .checkpoints import LaunchSnapshot
from .engine import IntegratedProcessEngine, ProcessEngineError
from .models import (
    ProcessDefinition,
    ProcessRun,
    ProcessRunEvent,
    ProcessStartJob,
)
from .sanitizer import sanitize
from .schemas import (
    EngineRunSnapshot,
    EngineRunReference,
    ProcessAnalysis,
    ProcessCallbackEvent,
    ProcessDefinitionCreate,
    ProcessDefinitionUpdate,
    ProcessFileInput,
    ProcessFileRef,
    ProcessRunDetail,
    ProcessRunEventRead,
    ProcessRunRead,
    ProcessStartPayload,
    ProcessStartResponse,
    ProcessEngineHealth,
    ProcessLLMCallRead,
    ProcessOperationsRead,
)

TERMINAL_STATUSES = frozenset({"success", "error", "cancelled"})
PROCESS_FILE_MAX_BYTES = 512 * 1024 * 1024
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "waiting", "success", "error", "cancelled"}),
    "running": frozenset({"waiting", "success", "error", "cancelling", "cancelled", "unknown"}),
    "waiting": frozenset({"running", "success", "error", "cancelling", "cancelled", "unknown"}),
    "unknown": frozenset({"running", "waiting", "success", "error", "cancelling", "cancelled"}),
    "cancelling": frozenset({"cancelled", "success", "error"}),
    "success": frozenset(),
    "error": frozenset(),
    "cancelled": frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return current == target or target in TRANSITIONS.get(current, frozenset())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_fingerprint(process_id: int, input_data: dict[str, Any], files: list[dict[str, Any]]) -> str:
    stable_files = [
        {"uri": item.get("uri"), "runtime": item.get("runtime"), "size": item.get("size")}
        for item in files
    ]
    raw = json.dumps(
        {"process_id": process_id, "input": input_data, "files": stable_files},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _sanitize(value: Any) -> Any:
    return sanitize(value, max_bytes=runtime_settings.PROCESS_SANITIZE_MAX_BYTES)


async def _append_event(
    run: ProcessRun,
    event_type: str,
    *,
    source: str = "galaris",
    event_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ProcessRunEvent:
    event = ProcessRunEvent(
        run_id=run.id,
        event_id=event_id,
        source=source,
        event_type=event_type,
        payload=cast(dict[str, Any], await _sanitize(payload or {})),
    )
    get_db().add(event)
    return event


async def _transition(
    run: ProcessRun,
    target: str,
    *,
    event_type: str,
    source: str = "galaris",
    payload: dict[str, Any] | None = None,
) -> bool:
    accepted = run.status not in TERMINAL_STATUSES and can_transition(run.status, target)
    await _append_event(
        run,
        event_type,
        source=source,
        payload={**(payload or {}), "from": run.status, "to": target, "accepted": accepted},
    )
    if not accepted or target == run.status:
        return accepted
    previous = run.status
    run.status = target
    now = _utcnow()
    run.engine_metadata = {**(run.engine_metadata or {}), "last_state_change_at": now.isoformat()}
    if target in {"running", "waiting"} and run.started_at is None:
        run.started_at = now
    if target in TERMINAL_STATUSES:
        run.finished_at = now
        if run.started_at is not None:
            metrics.observe(
                "process_run_duration_seconds",
                max(0.0, (now - run.started_at).total_seconds()),
                process_code=str(run.launch_snapshot.get("workflow_id") or run.process_id),
            )
    logger.bind(
        run_id=str(run.id), engine_code=run.engine_code,
        engine_run_id=run.engine_run_id, launcher_agent_id=run.launcher_agent_id,
        correlation_id=run.correlation_id,
    ).info("Process transition {} -> {} accepted={}", previous, target, accepted)
    return True


async def get_definition(process_id: int) -> Optional[ProcessDefinition]:
    return await get_db().get(ProcessDefinition, process_id)


async def get_definition_by_workflow_id(
    workflow_id: str,
    *,
    agent_ids: Collection[int] | None = None,
) -> Optional[ProcessDefinition]:
    query = select(ProcessDefinition).where(
        ProcessDefinition.engine_process_id == workflow_id
    )
    if agent_ids is not None:
        query = query.where(ProcessDefinition.agent_id.in_(agent_ids))
    result = await get_db().execute(query)
    return result.scalar_one_or_none()


async def list_definitions(
    *,
    agent_id: int | None = None,
    limit: int = 500,
    agent_ids: Collection[int] | None = None,
) -> list[ProcessDefinition]:
    query = select(ProcessDefinition)
    if agent_id is not None:
        query = query.where(ProcessDefinition.agent_id == agent_id)
    if agent_ids is not None:
        query = query.where(
            or_(
                ProcessDefinition.agent_id.is_(None),
                ProcessDefinition.agent_id.in_(agent_ids),
            )
        )
    query = query.order_by(ProcessDefinition.label).limit(max(1, min(limit, 500)))
    return list((await get_db().execute(query)).scalars().all())


async def has_process_definitions(
    *, agent_ids: Collection[int] | None = None
) -> bool:
    """Return whether at least one active process definition is in scope."""
    query = ProcessDefinition.histo_filter(select(ProcessDefinition.id))
    if agent_ids is not None:
        query = query.where(
            or_(
                ProcessDefinition.agent_id.is_(None),
                ProcessDefinition.agent_id.in_(agent_ids),
            )
        )
    result = await get_db().execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def list_process_tools() -> list[ToolModel]:
    query = select(ToolModel).where(ToolModel.code.in_(registry.codes())).order_by(ToolModel.label)
    return list((await get_db().execute(query)).scalars().all())


async def get_process_tool_by_code(tool_code: str) -> ToolModel:
    """Resolve one configured process engine from its stable tool code."""
    code = tool_code.strip()
    if not code:
        raise ValueError(await tr("process.errors.engine_code_required"))
    tool = (
        await get_db().execute(select(ToolModel).where(ToolModel.code == code))
    ).scalar_one_or_none()
    if tool is None:
        raise LookupError(await tr("process.errors.tool_not_found"))
    registry.get(tool.code)
    return tool


async def get_tool_health(tool_code: str) -> ProcessEngineHealth:
    return await registry.get(tool_code).health()


async def get_operations(
    *, agent_ids: Collection[int] | None = None
) -> ProcessOperationsRead:
    db = get_db()
    now = _utcnow()
    status_query = select(
        ProcessRun.status, func.count(ProcessRun.id)
    ).group_by(ProcessRun.status)
    if agent_ids is not None:
        status_query = status_query.where(ProcessRun.launcher_agent_id.in_(agent_ids))
    status_rows = (await db.execute(status_query)).all()
    pending_query = (
        select(func.count(ProcessStartJob.id), func.min(ProcessStartJob.created_at))
        .join(ProcessRun, ProcessRun.id == ProcessStartJob.run_id)
        .where(ProcessStartJob.status == "pending")
    )
    if agent_ids is not None:
        pending_query = pending_query.where(ProcessRun.launcher_agent_id.in_(agent_ids))
    pending_row = (
        await db.execute(pending_query)
    ).one()
    stale_cutoff = now - timedelta(
        seconds=max(
            runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS * 3,
            runtime_settings.PROCESS_START_TIMEOUT_SECONDS * 2,
            60,
        )
    )
    stale_query = select(func.count(ProcessRun.id)).where(
                ProcessRun.status.in_({"running", "waiting", "unknown", "cancelling"}),
                func.coalesce(ProcessRun.updated_at, ProcessRun.created_at) <= stale_cutoff,
            )
    if agent_ids is not None:
        stale_query = stale_query.where(ProcessRun.launcher_agent_id.in_(agent_ids))
    stale_active = int((await db.execute(stale_query)).scalar_one())
    failed_query = select(func.count(ProcessRun.id)).where(
                ProcessRun.status == "error",
                ProcessRun.created_at >= now - timedelta(days=1),
            )
    if agent_ids is not None:
        failed_query = failed_query.where(ProcessRun.launcher_agent_id.in_(agent_ids))
    failed_last_24h = int((await db.execute(failed_query)).scalar_one())
    oldest = pending_row[1]
    oldest_seconds = max(0.0, (now - oldest).total_seconds()) if oldest else None
    return ProcessOperationsRead(
        status_counts={str(status): int(count) for status, count in status_rows},
        pending_start_jobs=int(pending_row[0] or 0),
        stale_active_runs=stale_active,
        failed_last_24h=failed_last_24h,
        oldest_pending_job_seconds=oldest_seconds,
        checked_at=now,
    )


async def _validate_agent(agent_id: int | None) -> None:
    if agent_id is None:
        return
    from app.agent import Agent

    if await get_db().get(Agent, agent_id) is None:
        raise LookupError(await tr("process.errors.agent_not_found"))


async def _process_tool(tool_id: int) -> ToolModel:
    tool = await get_db().get(ToolModel, tool_id)
    if tool is None:
        raise LookupError(await tr("process.errors.tool_not_found"))
    registry.get(tool.code)
    return tool


async def create_definition(data: ProcessDefinitionCreate) -> ProcessDefinition:
    await _process_tool(data.tool_id)
    await _validate_agent(data.agent_id)
    existing_engine_process = (
        await get_db().execute(
            select(ProcessDefinition.id).where(
                ProcessDefinition.tool_id == data.tool_id,
                ProcessDefinition.engine_process_id == data.engine_process_id,
            )
        )
    ).scalar_one_or_none()
    if existing_engine_process is not None:
        raise ValueError(await tr("process.errors.already_linked"))
    record = ProcessDefinition(**data.model_dump())
    db = get_db()
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def update_definition(
    process_id: int, data: ProcessDefinitionUpdate
) -> Optional[ProcessDefinition]:
    record = await get_definition(process_id)
    if record is None:
        return None
    changes = data.model_dump(exclude_unset=True)
    for required_field in ("tool_id", "engine_process_id", "label"):
        if required_field in changes and changes[required_field] is None:
            raise ValueError(f"{required_field} cannot be null")
    if "tool_id" in changes:
        await _process_tool(cast(int, changes["tool_id"]))
    if "agent_id" in changes:
        await _validate_agent(cast(int | None, changes["agent_id"]))

    tool_id = cast(int, changes.get("tool_id", record.tool_id))
    engine_process_id = cast(
        str,
        changes.get("engine_process_id", record.engine_process_id),
    )
    duplicate_id = (
        await get_db().execute(
            select(ProcessDefinition.id).where(
                ProcessDefinition.tool_id == tool_id,
                ProcessDefinition.engine_process_id == engine_process_id,
                ProcessDefinition.id != process_id,
            )
        )
    ).scalar_one_or_none()
    if duplicate_id is not None:
        raise ValueError(await tr("process.errors.already_linked"))

    for key, value in changes.items():
        setattr(record, key, value)
    await get_db().commit()
    await get_db().refresh(record)
    return record


async def delete_definition(process_id: int) -> bool:
    record = await get_definition(process_id)
    if record is None:
        return False
    record.soft_delete()
    await get_db().commit()
    return True


async def list_for_agent(agent_id: int) -> list[dict[str, Any]]:
    query = (
        select(ProcessDefinition)
        .where(
            ProcessDefinition.agent_id == agent_id,
            ~ProcessDefinition.engine_process_id.startswith("multimedia:"),
            ~ProcessDefinition.engine_process_id.startswith("lab:"),
        )
        .order_by(ProcessDefinition.label)
    )
    rows = (await get_db().execute(query)).scalars().all()
    return [
        {
            "workflow_id": process.engine_process_id,
            "label": process.label,
            "description": process.description,
            "tool_id": process.tool_id,
        }
        for process in rows
    ]


async def list_resource_definitions_for_agent(
    agent_id: int,
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[ProcessDefinition]:
    """Return one bounded page of definitions visible to an agent."""

    statement = select(ProcessDefinition).where(
        ProcessDefinition.agent_id == agent_id,
        ~ProcessDefinition.engine_process_id.startswith("multimedia:"),
        ~ProcessDefinition.engine_process_id.startswith("lab:"),
    )
    normalized_query = query.strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                ProcessDefinition.engine_process_id.ilike(pattern),
                ProcessDefinition.label.ilike(pattern),
                ProcessDefinition.description.ilike(pattern),
            )
        )
    statement = (
        statement.order_by(
            ProcessDefinition.label,
            ProcessDefinition.engine_process_id,
        )
        .offset(max(0, offset))
        .limit(max(1, min(limit, 501)))
    )
    return list((await get_db().execute(statement)).scalars().all())


async def get_for_agent(agent_id: int, workflow_id: str) -> Optional[ProcessDefinition]:
    result = await get_db().execute(
        select(ProcessDefinition).where(
            ProcessDefinition.agent_id == agent_id,
            ProcessDefinition.engine_process_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def resolve_engine_run(
    workflow_id: str,
    engine_run_id: str,
    *,
    agent_ids: Collection[int] | None = None,
) -> ProcessRun:
    process = await get_definition_by_workflow_id(
        workflow_id,
        agent_ids=agent_ids,
    )
    if process is None or process.agent_id is None:
        raise LookupError(await tr("process.errors.workflow_without_agent"))
    tool = await _process_tool(process.tool_id)

    existing = (
        await get_db().execute(
            select(ProcessRun).where(
                ProcessRun.engine_code == tool.code,
                ProcessRun.engine_run_id == engine_run_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.process_id != process.id:
            raise PermissionError(await tr("process.errors.wrong_workflow"))
        return existing

    correlation_id = f"{tool.code}:{workflow_id}:{engine_run_id}"
    snapshot = await registry.get(tool.code).get_run(EngineRunReference(
        id=uuid4(),
        engine_run_id=engine_run_id,
        correlation_id=correlation_id,
    ))
    raw_workflow_id = snapshot.raw.get("workflowId")
    if raw_workflow_id is not None and str(raw_workflow_id) != workflow_id:
        raise PermissionError(await tr("process.errors.wrong_workflow"))

    run = ProcessRun(
        process_id=process.id,
        launcher_agent_id=process.agent_id,
        launch_snapshot={
            "version": 1,
            "workflow_id": workflow_id,
            "process_label": process.label,
            "tool_code": tool.code,
        },
        engine_code=tool.code,
        engine_run_id=engine_run_id,
        correlation_id=correlation_id,
        callback_token=secrets.token_urlsafe(42)[:64],
        status=snapshot.status,
        input={},
        output=cast(Optional[dict[str, Any]], await _sanitize(snapshot.output)),
        raw_snapshot=cast(Optional[dict[str, Any]], await _sanitize(snapshot.raw)),
        error_code=snapshot.error.code if snapshot.error else None,
        error_message=(
            str(await _sanitize(snapshot.error.message))
            if snapshot.error
            else None
        ),
    )
    get_db().add(run)
    # Rollback expires ORM attributes; retain the ownership values needed to
    # resolve a concurrent insertion without triggering implicit async I/O.
    process_id, engine_code = process.id, tool.code
    try:
        await get_db().commit()
    except IntegrityError:
        await get_db().rollback()
        concurrent = (
            await get_db().execute(
                select(ProcessRun).where(
                    ProcessRun.engine_code == engine_code,
                    ProcessRun.engine_run_id == engine_run_id,
                )
            )
        ).scalar_one()
        if concurrent.process_id != process_id:
            raise PermissionError(await tr("process.errors.wrong_workflow"))
        return concurrent
    await get_db().refresh(run)
    return run


async def _resolve_files(
    agent_id: int,
    runtime: str,
    files: Sequence[ProcessFileInput],
    *,
    run_id: UUID,
    task_id: UUID | None = None,
) -> list[ProcessFileRef]:
    from app.file_share import (
        ResourceContext,
        parse_resource_uri,
        resource_info,
    )

    expires_at = _utcnow() + timedelta(seconds=runtime_settings.PROCESS_FILE_REF_TTL_SECONDS)
    base_url = (runtime_settings.PROCESS_GALARIS_BASE_URL or settings.APP_HOST).rstrip("/")
    result: list[ProcessFileRef] = []
    for request_file in files:
        raw_uri = request_file.uri.strip()
        if "://" not in raw_uri:
            raise ValueError(
                render_prompt(await tr("process.errors.resource_uri_invalid"), uri=raw_uri)
            )
        try:
            resource_uri = str(parse_resource_uri(raw_uri))
        except ValueError as exc:
            raise ValueError(
                render_prompt(await tr("process.errors.resource_uri_invalid"), uri=raw_uri)
            ) from exc
        resource_ctx = ResourceContext(
            agent_id=agent_id,
            runtime=cast(Any, runtime),
            task_id=task_id,
        )
        console_resource = None
        try:
            if parse_resource_uri(resource_uri).scheme == "console":
                from app.console import build_run_resource

                console_resource = await build_run_resource(agent_id)
                resource_ctx = ResourceContext(
                    agent_id=agent_id,
                    runtime=cast(Any, runtime),
                    task_id=task_id,
                    console_resource=console_resource,
                )
            descriptor = await resource_info(resource_ctx, resource_uri)
            if descriptor.is_collection:
                raise IsADirectoryError(resource_uri)
            size = descriptor.size
            if size is None:
                from tempfile import TemporaryDirectory

                from app.file_share import materialize_resource

                with TemporaryDirectory(prefix="galaris_process_probe_") as directory:
                    materialized = await materialize_resource(
                        resource_ctx,
                        resource_uri,
                        Path(directory) / "source",
                        max_bytes=PROCESS_FILE_MAX_BYTES,
                    )
                    size = materialized.size
            if size > PROCESS_FILE_MAX_BYTES:
                raise ValueError(
                    render_prompt(
                        await tr("process.errors.resource_too_large"),
                        uri=resource_uri,
                        max_bytes=PROCESS_FILE_MAX_BYTES,
                    )
                )
        finally:
            if console_resource is not None:
                await console_resource.close()
        filename = descriptor.name or Path(parse_resource_uri(resource_uri).decoded_locator).name
        content_type = (
            descriptor.media_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        file_id = uuid4().hex
        result.append(ProcessFileRef(
            id=file_id,
            uri=resource_uri,
            runtime=cast(Any, runtime),
            task_id=task_id,
            filename=filename,
            content_type=content_type,
            size=size,
            description=request_file.description,
            download_url=f"{base_url}/api/processes/runs/{run_id}/files/{file_id}",
            expires_at=expires_at,
        ))
    return result


async def _tracking_message(run_id: UUID) -> str:
    return render_prompt(await tr("process.tracking"), run_id=run_id)


async def _start_response(
    run: ProcessRun, process: ProcessDefinition, *, deduplicated: bool
) -> ProcessStartResponse:
    return ProcessStartResponse(
        run_id=run.id,
        status=cast(Any, run.status),
        workflow_id=process.engine_process_id,
        tool=run.engine_code,
        engine_run_id=run.engine_run_id,
        deduplicated=deduplicated,
        tracking_message=await _tracking_message(run.id),
    )


async def _ensure_process_wait(run: ProcessRun, process: ProcessDefinition) -> None:
    current = await get_run(run.id)
    if current is None or current.await_task_id is not None or current.task_id is None:
        return
    from app.task import collab, task_service

    parent = await task_service.get_by_id(current.task_id)
    if parent is None:
        return
    wait_task = await collab.dispatch_process_wait(
        parent=parent,
        run_id=current.id,
        process_label=process.label,
        timeout_seconds=runtime_settings.PROCESS_WAIT_MAX_SECONDS,
    )
    locked = await _locked_run(current.id)
    if locked is None:
        return
    locked.await_task_id = wait_task.id
    await get_db().commit()
    # A very fast run may finish before its wait link is persisted. Resolving it
    # here keeps the outcome monotonic and idempotent.
    if locked.status in TERMINAL_STATUSES:
        await collab.resolve_process_await(
            await_task_id=wait_task.id,
            process_label=process.label,
            run_id=locked.id,
            status=locked.status,
            output=locked.output,
            error=locked.error_message,
        )


async def start_process(
    *,
    agent_id: int,
    workflow_id: str,
    input_data: dict[str, Any],
    files: Sequence[ProcessFileInput] = (),
    wait_for_completion: bool = False,
    idempotency_key: str | None = None,
    task_id: UUID | None = None,
    runtime: str = "internal",
) -> ProcessStartResponse:
    allowed = await get_for_agent(agent_id, workflow_id)
    if allowed is None:
        raise PermissionError(render_prompt(
            await tr("process.errors.workflow_not_allowed"),
            workflow_id=workflow_id,
        ))
    process = allowed
    if not process.engine_process_id:
        raise ValueError(await tr("process.errors.engine_process_id_missing"))
    tool = await _process_tool(process.tool_id)

    engine = registry.get(tool.code)
    if isinstance(engine, IntegratedProcessEngine):
        input_data = await engine.prepare_input(agent_id, workflow_id, input_data)
        # Only invocation identity deduplicates integrated operations, never their prompt.
        idempotency_key = (idempotency_key or "").strip() or uuid4().hex

    explicit_key = idempotency_key.strip() if idempotency_key else None
    if explicit_key:
        existing = (
            await get_db().execute(select(ProcessRun).where(
                ProcessRun.launcher_agent_id == agent_id,
                ProcessRun.process_id == process.id,
                ProcessRun.idempotency_key == explicit_key,
            ))
        ).scalar_one_or_none()
        if existing is not None:
            if wait_for_completion:
                await _ensure_process_wait(existing, process)
            return await _start_response(existing, process, deduplicated=True)

    run_id = uuid4()
    callback_token = secrets.token_urlsafe(42)[:64]
    resolved_files = await _resolve_files(
        agent_id, runtime, files, run_id=run_id, task_id=task_id
    )
    serialized_files = [item.model_dump(mode="json") for item in resolved_files]
    fingerprint = _json_fingerprint(process.id, input_data, serialized_files)
    if not explicit_key:
        window = runtime_settings.PROCESS_IDEMPOTENCY_WINDOW_SECONDS
        if window:
            cutoff = _utcnow() - timedelta(seconds=window)
            existing = (
                await get_db().execute(
                    select(ProcessRun)
                    .where(
                        ProcessRun.launcher_agent_id == agent_id,
                        ProcessRun.process_id == process.id,
                        ProcessRun.content_fingerprint == fingerprint,
                        ProcessRun.created_at >= cutoff,
                    )
                    .order_by(ProcessRun.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                if wait_for_completion:
                    await _ensure_process_wait(existing, process)
                return await _start_response(existing, process, deduplicated=True)

    launch_snapshot: dict[str, Any] = {
        "version": 1,
        "workflow_id": process.engine_process_id,
        "process_label": process.label,
        "tool_code": tool.code,
        "input": input_data,
        "files": serialized_files,
    }
    run = ProcessRun(
        id=run_id,
        process_id=process.id,
        launcher_agent_id=agent_id,
        task_id=task_id,
        launch_snapshot=launch_snapshot,
        engine_code=tool.code,
        correlation_id=f"proc-{uuid4().hex}",
        idempotency_key=explicit_key,
        content_fingerprint=fingerprint,
        callback_token=callback_token,
        status="queued",
        input=input_data,
    )
    job = ProcessStartJob(run_id=run.id)
    db = get_db()
    db.add_all([run, job])
    await _append_event(run, "run.created", payload={"workflow_id": process.engine_process_id})
    await _append_event(run, "engine.start.requested", payload={"tool_code": tool.code})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not explicit_key:
            raise
        existing = (
            await db.execute(select(ProcessRun).where(
                ProcessRun.launcher_agent_id == agent_id,
                ProcessRun.process_id == process.id,
                ProcessRun.idempotency_key == explicit_key,
            ))
        ).scalar_one()
        return await _start_response(existing, process, deduplicated=True)
    metrics.increment("process_runs_started_total", process_code=process.engine_process_id, engine=tool.code)
    await websocket.emit("process_run", "create", {"id": str(run.id), "status": run.status}, None)
    if wait_for_completion:
        await _ensure_process_wait(run, process)
    return await _start_response(run, process, deduplicated=False)


async def _locked_run(run_id: UUID) -> Optional[ProcessRun]:
    result = await get_db().execute(
        select(ProcessRun).where(ProcessRun.id == run_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


def _engine_run_reference(run: ProcessRun) -> EngineRunReference:
    return EngineRunReference(
        id=run.id,
        engine_run_id=run.engine_run_id,
        correlation_id=run.correlation_id,
        callback_token=run.callback_token,
    )


async def get_run(run_id: UUID) -> Optional[ProcessRun]:
    return await get_db().get(ProcessRun, run_id)


async def delete_run(run_id: UUID) -> bool:
    run = await get_run(run_id)
    if run is None:
        return False
    if run.status not in TERMINAL_STATUSES:
        raise ValueError(await tr("process.errors.active_run_delete"))
    db = get_db()
    await db.delete(run)
    await db.commit()
    await websocket.emit("process_run", "delete", {
        "id": str(run_id), "launcher_agent_id": run.launcher_agent_id,
    }, None)
    return True


async def list_runs(
    *,
    agent_id: int | None = None,
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[ProcessRun]:
    query = select(ProcessRun).join(ProcessDefinition, ProcessDefinition.id == ProcessRun.process_id)
    if agent_id is not None:
        query = query.where(ProcessRun.launcher_agent_id == agent_id)
    if workflow_id:
        query = query.where(ProcessDefinition.engine_process_id == workflow_id)
    if status:
        query = query.where(ProcessRun.status == status)
    query = query.order_by(ProcessRun.created_at.desc()).limit(max(1, min(limit, 500)))
    return list((await get_db().execute(query)).scalars().all())


async def paginate_runs(
    *,
    agent_id: int | None = None,
    process_id: int | None = None,
    workflow_id: str | None = None,
    status: str | None = None,
    active: bool | None = None,
    search: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    sort_by: str = "created_at",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
    agent_ids: Collection[int] | None = None,
) -> tuple[list[ProcessRun], int]:
    base = select(ProcessRun.id).join(
        ProcessDefinition,
        ProcessDefinition.id == ProcessRun.process_id,
    )
    if agent_id is not None:
        base = base.where(ProcessRun.launcher_agent_id == agent_id)
    if agent_ids is not None:
        base = base.where(ProcessRun.launcher_agent_id.in_(agent_ids))
    if process_id is not None:
        base = base.where(ProcessRun.process_id == process_id)
    if workflow_id:
        base = base.where(ProcessDefinition.engine_process_id == workflow_id)
    if status:
        base = base.where(ProcessRun.status == status)
    if active is not None:
        is_active = ProcessRun.status.not_in(TERMINAL_STATUSES)
        base = base.where(is_active if active else ~is_active)
    if created_after is not None:
        base = base.where(ProcessRun.created_at >= created_after)
    if created_before is not None:
        base = base.where(ProcessRun.created_at <= created_before)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        base = base.where(or_(
            sa_cast(ProcessRun.id, String).ilike(pattern),
            ProcessRun.status.ilike(pattern),
            ProcessRun.engine_run_id.ilike(pattern),
            ProcessDefinition.engine_process_id.ilike(pattern),
            ProcessDefinition.label.ilike(pattern),
        ))

    total = int((await get_db().execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one())
    sort_columns = {
        "status": ProcessRun.status,
        "launcher_agent_id": ProcessRun.launcher_agent_id,
        "created_at": ProcessRun.created_at,
        "finished_at": ProcessRun.finished_at,
    }
    sort_column = sort_columns.get(sort_by, ProcessRun.created_at)
    ordering = sort_column.desc() if descending else sort_column.asc()
    id_ordering = ProcessRun.id.desc() if descending else ProcessRun.id.asc()
    paged_ids = (
        base.order_by(ordering, id_ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (
        await get_db().execute(
            select(ProcessRun)
            .where(ProcessRun.id.in_(paged_ids))
            .order_by(ordering, id_ordering)
        )
    ).scalars().all()
    return list(rows), total


async def _run_read(run: ProcessRun, *, fresh: bool = True) -> ProcessRunRead:
    from app.agent import Agent

    # SQLAlchemy populates ``updated_at`` through ``onupdate`` and may expire it
    # after commit. Reloading explicitly prevents synchronous lazy loading in Pydantic.
    await get_db().refresh(run)
    process = await get_db().get(ProcessDefinition, run.process_id)
    if process is None:
        process = (
            await get_db().execute(
                select(ProcessDefinition)
                .where(ProcessDefinition.id == run.process_id)
                .execution_options(include_historized=True)
            )
        ).scalar_one_or_none()
    agent = await get_db().get(Agent, run.launcher_agent_id)
    base = ProcessRunRead.model_validate(run)
    return base.model_copy(update={
        "workflow_id": process.engine_process_id if process else str(run.launch_snapshot.get("workflow_id") or ""),
        "process_label": process.label if process else str(run.launch_snapshot.get("process_label") or ""),
        "launcher_agent_code": agent.code if agent else None,
        "fresh": fresh,
        "summary": await tr(f"process.summary.{run.status}"),
    })


async def get_run_detail(run_id: UUID, *, refresh_if_stale: bool = False) -> Optional[ProcessRunDetail]:
    fresh = True
    run = await get_run(run_id)
    if run is None:
        return None
    if refresh_if_stale and run.status not in TERMINAL_STATUSES:
        staleness = runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS
        last = run.updated_at or run.created_at
        if (_utcnow() - last).total_seconds() >= staleness:
            try:
                run = await refresh_run(run.id)
            except Exception as exc:
                logger.warning("Skipped process refresh for {}: {}", run.id, exc)
                fresh = False
    event_rows = (
        await get_db().execute(
            select(ProcessRunEvent)
            .where(ProcessRunEvent.run_id == run.id)
            .order_by(ProcessRunEvent.created_at)
        )
    ).scalars().all()
    from app.llm.models import LLMCall

    llm_rows = (
        await get_db().execute(
            select(LLMCall)
            .where(LLMCall.process_run_id == run.id)
            .order_by(LLMCall.started_at)
        )
    ).scalars().all()
    task_ids = {
        task_id
        for task_id in [run.task_id, run.await_task_id, *(call.task_id for call in llm_rows)]
        if task_id is not None
    }
    base = await _run_read(run, fresh=fresh)
    return ProcessRunDetail(**base.model_dump(), events=[
        ProcessRunEventRead.model_validate(event) for event in event_rows
    ], task_ids=sorted(task_ids, key=str), llm_calls=[
        ProcessLLMCallRead.model_validate(call) for call in llm_rows
    ])


async def list_for_task_ids(
    task_ids: Sequence[UUID],
    *,
    limit: int = 100,
) -> list[ProcessRunDetail]:
    """Return process evidence linked to any task in an analysis graph."""

    normalized_task_ids = tuple(dict.fromkeys(task_ids))
    if not normalized_task_ids:
        return []
    rows = list(
        (
            await get_db().scalars(
                ProcessRun.histo_filter(
                    select(ProcessRun)
                    .where(
                        or_(
                            ProcessRun.task_id.in_(normalized_task_ids),
                            ProcessRun.await_task_id.in_(normalized_task_ids),
                        )
                    )
                    .order_by(ProcessRun.created_at.asc(), ProcessRun.id.asc())
                    .limit(max(1, min(limit, 500)))
                )
            )
        ).all()
    )
    details: list[ProcessRunDetail] = []
    for row in rows:
        detail = await get_run_detail(row.id)
        if detail is not None:
            details.append(detail)
    return details


async def list_run_summaries_for_scope(
    run_ids: Sequence[UUID],
    task_ids: Sequence[UUID],
    *,
    limit: int = 500,
) -> list[ProcessRunRead]:
    """Return bounded run summaries linked directly or through scoped Tasks."""

    normalized_run_ids = tuple(dict.fromkeys(run_ids))
    normalized_task_ids = tuple(dict.fromkeys(task_ids))
    if normalized_run_ids and normalized_task_ids:
        scope_condition = or_(
            ProcessRun.id.in_(normalized_run_ids),
            ProcessRun.task_id.in_(normalized_task_ids),
            ProcessRun.await_task_id.in_(normalized_task_ids),
        )
    elif normalized_run_ids:
        scope_condition = ProcessRun.id.in_(normalized_run_ids)
    elif normalized_task_ids:
        scope_condition = or_(
            ProcessRun.task_id.in_(normalized_task_ids),
            ProcessRun.await_task_id.in_(normalized_task_ids),
        )
    else:
        return []
    rows = list(
        (
            await get_db().scalars(
                ProcessRun.histo_filter(
                    select(ProcessRun)
                    .where(scope_condition)
                    .order_by(ProcessRun.created_at, ProcessRun.id)
                    .limit(max(1, min(limit, 500)))
                )
            )
        ).all()
    )
    return [await _run_read(row) for row in rows]


async def list_run_summaries_page_for_scope(
    run_ids: Sequence[UUID],
    task_ids: Sequence[UUID],
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[ProcessRunRead], int]:
    """Return one recent-first page of runs linked directly or through scoped Tasks."""

    normalized_run_ids = tuple(dict.fromkeys(run_ids))
    normalized_task_ids = tuple(dict.fromkeys(task_ids))
    if normalized_run_ids and normalized_task_ids:
        scope_condition = or_(
            ProcessRun.id.in_(normalized_run_ids),
            ProcessRun.task_id.in_(normalized_task_ids),
            ProcessRun.await_task_id.in_(normalized_task_ids),
        )
    elif normalized_run_ids:
        scope_condition = ProcessRun.id.in_(normalized_run_ids)
    elif normalized_task_ids:
        scope_condition = or_(
            ProcessRun.task_id.in_(normalized_task_ids),
            ProcessRun.await_task_id.in_(normalized_task_ids),
        )
    else:
        return [], 0
    total = int(
        await get_db().scalar(
            select(func.count(ProcessRun.id)).where(
                scope_condition,
                ProcessRun.deleted_at.is_(None),
            )
        )
        or 0
    )
    rows = list(
        (
            await get_db().scalars(
                ProcessRun.histo_filter(
                    select(ProcessRun)
                    .where(scope_condition)
                    .order_by(ProcessRun.created_at.desc(), ProcessRun.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
        ).all()
    )
    return [await _run_read(row) for row in rows], total


async def _apply_snapshot(run: ProcessRun, snapshot: EngineRunSnapshot, event_type: str) -> None:
    if not await _transition(
        run, snapshot.status, event_type=event_type, payload=snapshot.model_dump(mode="json")
    ):
        return
    run.engine_run_id = snapshot.engine_run_id or run.engine_run_id
    if snapshot.output is not None:
        run.output = cast(dict[str, Any], await _sanitize(snapshot.output))
    run.raw_snapshot = cast(Optional[dict[str, Any]], await _sanitize(snapshot.raw))
    run.engine_metadata = {
        **(run.engine_metadata or {}),
        "last_observed_at": _utcnow().isoformat(),
        "refresh_failures": 0,
        "last_refresh_error": None,
        "next_refresh_at": None,
        "observation_degraded": False,
    }
    if run.error_code == "observation_unavailable":
        run.error_code = None
        run.error_message = None
    if snapshot.error:
        run.error_code = snapshot.error.code
        run.error_message = str(await _sanitize(snapshot.error.message))
        if snapshot.error.node_name:
            run.engine_metadata = {
                **(run.engine_metadata or {}),
                "failed_node": snapshot.error.node_name,
            }


async def refresh_run(run_id: UUID) -> ProcessRun:
    run = await get_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    if run.status in TERMINAL_STATUSES:
        await _resolve_await_if_terminal(run)
        return run
    engine = registry.get(run.engine_code)
    try:
        snapshot = await asyncio.wait_for(
            engine.get_run(_engine_run_reference(run)),
            timeout=(engine.refresh_timeout_seconds if isinstance(engine, IntegratedProcessEngine)
                     else runtime_settings.PROCESS_REFRESH_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError as error:
        exc = ProcessEngineError(
            "engine_timeout",
            "Process engine refresh timed out.",
            retryable=True,
        )
        await _record_refresh_failure(run.id, exc)
        raise exc from error
    except ProcessEngineError as exc:
        await _record_refresh_failure(run.id, exc)
        raise
    except Exception as error:
        if not get_db().is_active:
            await get_db().rollback()
        exc = ProcessEngineError("engine_unreachable", str(error), retryable=True)
        await _record_refresh_failure(run_id, exc)
        raise exc from error
    locked = await _locked_run(run.id)
    if locked is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    await _apply_snapshot(locked, snapshot, "engine.refresh")
    await get_db().commit()
    await _resolve_await_if_terminal(locked)
    await websocket.emit("process_run", "update", {"id": str(locked.id), "status": locked.status}, None)
    return locked


async def refresh_active_runs(*, engine_code: str | None = None, parallel: bool = False, batch_size: int = 100) -> int:
    """Refresh active remote runs when no callback is available."""
    # A terminal state is durable before task fan-in. Reconcile that boundary
    # after a crash, independently of callbacks and of the remote engine.
    pending_ids = list((await get_db().scalars(
        select(ProcessRun.id).where(
            ProcessRun.status.in_(TERMINAL_STATUSES),
            ProcessRun.await_task_id.is_not(None),
            ProcessRun.await_resolved_at.is_(None),
        ).order_by(ProcessRun.finished_at, ProcessRun.id).limit(100)
    )).all())
    for run_id in pending_ids:
        try:
            run = await get_db().get(ProcessRun, run_id)
            if run is not None:
                await _resolve_await_if_terminal(run)
        except Exception:
            await get_db().rollback()
            logger.warning("Process await reconciliation failed for {}", run_id)
    cutoff = _utcnow() - timedelta(seconds=runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS)
    run_ids = list(
        (
            await get_db().execute(
                select(ProcessRun.id)
                .where(
                    ProcessRun.status.in_({"running", "waiting", "unknown", "cancelling"}),
                    ProcessRun.engine_code == engine_code if engine_code is not None else true(),
                    ProcessRun.engine_run_id.is_not(None),
                    or_(
                        func.coalesce(
                            func.pg_input_is_valid(ProcessRun.engine_metadata["next_refresh_at"].astext, "timestamp with time zone"),
                            False,
                        ).is_(False),
                        case(
                            (func.pg_input_is_valid(ProcessRun.engine_metadata["next_refresh_at"].astext, "timestamp with time zone"),
                             sa_cast(ProcessRun.engine_metadata["next_refresh_at"].astext, DateTime(timezone=True))),
                            else_=None,
                        ) <= _utcnow(),
                    ),
                    or_(
                        ProcessRun.updated_at <= cutoff,
                        (
                            ProcessRun.updated_at.is_(None)
                            & (ProcessRun.created_at <= cutoff)
                        ),
                    ),
                )
                .order_by(ProcessRun.created_at)
                .limit(max(1, min(batch_size, 100)))
            )
        ).scalars().all()
    )
    refreshed = 0
    if parallel:
        await get_db().commit()
        from .workers import refresh_runs
        return await refresh_runs(run_ids)

    for run_id in run_ids:
        try:
            await refresh_run(run_id)
            refreshed += 1
        except Exception as exc:
            logger.warning("Automatic process refresh failed for {}: {}", run_id, exc)
    return refreshed


async def _record_refresh_failure(run_id: UUID, exc: ProcessEngineError) -> None:
    run = await _locked_run(run_id)
    if run is None or run.status in TERMINAL_STATUSES:
        return
    metadata = dict(run.engine_metadata or {})
    try:
        failures = max(0, int(metadata.get("refresh_failures") or 0)) + 1
    except (ValueError, TypeError):
        # This is optional observation bookkeeping, never execution evidence.
        failures = 1
    delay = min(3600, max(1, runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS) * 2 ** min(failures - 1, 10))
    metadata.update({
        "refresh_failures": failures,
        "last_refresh_error": str(await _sanitize(exc.message)),
        "last_refresh_error_code": exc.code,
        "last_refresh_failed_at": _utcnow().isoformat(),
        "next_refresh_at": (_utcnow() + timedelta(seconds=delay)).isoformat(),
        "observation_degraded": failures >= runtime_settings.PROCESS_REFRESH_MAX_FAILURES or not exc.retryable,
    })
    run.engine_metadata = metadata
    await _append_event(
        run,
        "engine.refresh.failed",
        payload={"code": exc.code, "attempt": failures, "retryable": exc.retryable},
    )
    if metadata["observation_degraded"]:
        run.error_code = "observation_unavailable"
        run.error_message = str(await _sanitize(exc.message))
        if run.status in {"running", "waiting"}:
            await _transition(
                run, "unknown", event_type="engine.observation.degraded",
                payload={"code": exc.code, "refresh_failures": failures},
            )
    metrics.increment("process_refresh_failures_total", engine=run.engine_code, error_code=exc.code)
    await get_db().commit()
    await websocket.emit("process_run", "update", {"id": str(run.id), "status": run.status}, None)
    logger.warning(
        "Process refresh failed for {} ({}/{}): {}",
        run.id,
        failures,
        runtime_settings.PROCESS_REFRESH_MAX_FAILURES,
        exc.message,
    )


async def _resolve_await_if_terminal(run: ProcessRun) -> None:
    if run.status not in TERMINAL_STATUSES or run.await_task_id is None or run.await_resolved_at is not None:
        return
    from app.task import collab

    await collab.resolve_process_await(
        await_task_id=run.await_task_id,
        process_label=str(
            run.launch_snapshot.get("process_label")
            or run.launch_snapshot.get("workflow_id")
        ),
        run_id=run.id,
        status=run.status,
        output=run.output,
        error=run.error_message,
    )
    run.await_resolved_at = _utcnow()
    await get_db().commit()


async def receive_callback(
    run_id: UUID, token: str, event: ProcessCallbackEvent
) -> tuple[ProcessRun, bool]:
    run = await _locked_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    if not secrets.compare_digest(token or "", run.callback_token):
        metrics.increment("process_callback_auth_failures_total", engine=run.engine_code)
        raise PermissionError(await tr("process.errors.invalid_callback_token"))
    duplicate = (
        await get_db().execute(select(ProcessRunEvent.id).where(
            ProcessRunEvent.run_id == run.id,
            ProcessRunEvent.event_id == event.event_id,
        ))
    ).scalar_one_or_none()
    if duplicate is not None:
        metrics.increment("process_callback_duplicates_total", engine=run.engine_code)
        await _resolve_await_if_terminal(run)
        return run, True
    event_payload = event.model_dump(mode="json")
    await _append_event(
        run,
        event.event_type or "engine.callback.received",
        source=run.engine_code,
        event_id=event.event_id,
        payload=event_payload,
    )
    accepted = await _transition(
        run, event.status, event_type="run.completed" if event.status in TERMINAL_STATUSES else "run.progress",
        source=run.engine_code, payload=event_payload,
    )
    if accepted:
        run.engine_run_id = event.engine_run_id or run.engine_run_id
        if event.output is not None:
            run.output = cast(dict[str, Any], await _sanitize(event.output))
        if event.error is not None:
            run.error_code = event.error.code
            run.error_message = str(await _sanitize(event.error.message))
    await get_db().commit()
    metrics.increment(
        "process_callbacks_total",
        engine=run.engine_code,
        status=event.status,
    )
    if event.occurred_at is not None:
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        metrics.observe(
            "process_callback_delivery_seconds",
            max(0.0, (_utcnow() - occurred_at).total_seconds()),
            engine=run.engine_code,
        )
    await _resolve_await_if_terminal(run)
    await websocket.emit("process_run", "update", {"id": str(run.id), "status": run.status}, None)
    return run, False


async def cancel_run(run_id: UUID) -> ProcessRun:
    run = await _locked_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    if run.status in TERMINAL_STATUSES:
        await _resolve_await_if_terminal(run)
        return run
    metrics.increment("process_cancel_requests_total", engine=run.engine_code)
    if run.status == "queued":
        job = (
            await get_db().execute(
                select(ProcessStartJob).where(ProcessStartJob.run_id == run.id).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is not None and job.status == "pending" and job.locked_at is None:
            job.status = "cancelled"
            await _transition(run, "cancelled", event_type="run.cancelled", payload={"remote_may_continue": False})
            await get_db().commit()
            await _resolve_await_if_terminal(run)
            return run
    engine = registry.get(run.engine_code)
    if not engine.supports_cancel:
        if isinstance(engine, IntegratedProcessEngine):
            raise ProcessEngineError("cancel_unsupported", "The media provider cannot confirm cancellation; tracking continues.")
        run.engine_metadata = {**(run.engine_metadata or {}), "remote_may_continue": True}
        await _transition(run, "cancelled", event_type="run.cancelled", payload={"remote_may_continue": True})
        await get_db().commit()
        await _resolve_await_if_terminal(run)
        return run
    await _transition(run, "cancelling", event_type="engine.cancel.requested")
    await get_db().commit()
    try:
        snapshot = await engine.cancel_run(_engine_run_reference(run))
    except ProcessEngineError as exc:
        if exc.code != "cancel_unsupported":
            raise
        locked = await _locked_run(run.id)
        if locked is None:
            raise LookupError(await tr("process.errors.run_not_found"))
        locked.engine_metadata = {**(locked.engine_metadata or {}), "remote_may_continue": True}
        await _transition(locked, "cancelled", event_type="run.cancelled", payload={"remote_may_continue": True})
        await get_db().commit()
        await _resolve_await_if_terminal(locked)
        return locked
    locked = await _locked_run(run.id)
    if locked is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    await _apply_snapshot(locked, snapshot, "engine.cancel.confirmed")
    locked.engine_metadata = {**(locked.engine_metadata or {}), "remote_may_continue": False}
    await get_db().commit()
    await _resolve_await_if_terminal(locked)
    return locked


async def retry_run(run_id: UUID) -> ProcessStartResponse:
    run = await get_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    if run.status not in {"error", "cancelled"}:
        raise ValueError(await tr("process.errors.retry_terminal_only"))
    process = await get_db().get(ProcessDefinition, run.process_id)
    if process is None:
        process = (
            await get_db().execute(
                select(ProcessDefinition)
                .where(ProcessDefinition.id == run.process_id)
                .execution_options(include_historized=True)
            )
        ).scalar_one_or_none()
    if process is None:
        raise LookupError(await tr("process.errors.definition_not_found"))
    raw_files = cast(list[dict[str, Any]], run.launch_snapshot.get("files") or [])
    files = [
        ProcessFileInput(
            uri=str(item.get("uri") or item.get("path") or ""),
            description=str(item.get("description") or ""),
        )
        for item in raw_files
        if item.get("uri") or item.get("path")
    ]
    runtime = str(raw_files[0].get("runtime") or "internal") if raw_files else "internal"
    response = await start_process(
        agent_id=run.launcher_agent_id,
        workflow_id=process.engine_process_id,
        input_data=run.input,
        files=files,
        idempotency_key=f"retry:{run.id}:{uuid4().hex}",
        task_id=run.task_id,
        runtime=cast(Any, runtime),
    )
    await _append_event(run, "run.retried", payload={"new_run_id": str(response.run_id)})
    await get_db().commit()
    metrics.increment("process_retry_requests_total", engine=run.engine_code)
    return response


async def analyze_run(run_id: UUID) -> ProcessAnalysis:
    detail = await get_run_detail(run_id)
    if detail is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    run = await get_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    duration: float | None = None
    if run.started_at:
        duration = max(0.0, ((run.finished_at or _utcnow()) - run.started_at).total_seconds())
    failed_steps: list[str] = []
    for event in detail.events:
        raw_error = event.payload.get("error")
        nested_error = cast(dict[str, Any], raw_error) if isinstance(raw_error, dict) else {}
        node_name = event.payload.get("node_name") or nested_error.get("node_name")
        if node_name and (
            event.payload.get("status") == "error"
            or nested_error
            or event.event_type.endswith("failed")
        ):
            failed_steps.append(str(node_name))
    failed_steps = sorted(set(failed_steps))
    agent_calls = [event.payload for event in detail.events if event.event_type == "agent.called"]
    llm_calls: list[dict[str, Any]] = []
    try:
        from app.llm.models import LLMCall

        rows = (
            await get_db().execute(
                select(LLMCall).where(LLMCall.process_run_id == run.id).order_by(LLMCall.started_at)
            )
        ).scalars().all()
        llm_calls = [{
            "id": str(call.id), "model": call.requested_model, "status": call.status,
            "duration": call.duration, "error": call.error,
        } for call in rows]
    except (AttributeError, ImportError):
        pass
    recommendations: list[str] = []
    if run.status == "error":
        recommendations.append(await tr("process.recommendation_retry"))
        if run.error_code in {"engine_unreachable", "unauthorized", "not_found"}:
            recommendations.append(await tr("process.recommendation_engine"))
    analysis = ProcessAnalysis(
        run_id=run.id,
        success=run.status == "success",
        status=cast(Any, run.status),
        summary=await tr(f"process.summary.{run.status}"),
        duration_seconds=duration,
        failed_steps=failed_steps,
        agent_calls=agent_calls,
        llm_calls=llm_calls,
        recommendations=recommendations,
    )
    run.analysis = analysis.model_dump(mode="json")
    await get_db().commit()
    return analysis


async def record_inbound_call(
    run_id: UUID,
    *,
    kind: str,
    target_code: str,
    metadata: dict[str, Any] | None = None,
    agent_ids: Collection[int] | None = None,
) -> None:
    run = await _locked_run(run_id)
    if run is None or (
        agent_ids is not None and run.launcher_agent_id not in agent_ids
    ):
        raise LookupError(await tr("process.errors.correlation_not_found"))
    if kind == "agent":
        from app.agent import Agent

        process = await get_db().get(ProcessDefinition, run.process_id)
        assigned_agent = (
            await get_db().get(Agent, process.agent_id)
            if process is not None and process.agent_id is not None
            else None
        )
        if assigned_agent is None or assigned_agent.code != target_code:
            raise PermissionError(await tr("process.errors.correlated_process_denied"))
    await _append_event(
        run,
        f"{kind}.called",
        source=kind,
        payload={"target_code": target_code, **(metadata or {})},
    )
    await get_db().commit()
    metrics.increment("process_inbound_calls_total", kind=kind, target=target_code)


async def sync_tool_definitions(tool_code: str) -> list[dict[str, Any]]:
    definitions = await registry.get(tool_code).sync_definitions()
    return [definition.model_dump(mode="json") for definition in definitions]


async def process_start_jobs(*, batch_size: int = 10, engine_code: str | None = None, job_id: int | None = None) -> int:
    processed = 0
    for _ in range(max(1, batch_size)):
        db = get_db()
        now = _utcnow()
        lock_timeout = max(
            [runtime_settings.PROCESS_START_TIMEOUT_SECONDS] + [
                engine.start_timeout_seconds for code in (registry.codes() if engine_code is None else (engine_code,))
                if isinstance(engine := registry.get(code), IntegratedProcessEngine)
            ]
        )
        stale_lock = now - timedelta(seconds=max(30.0, lock_timeout * 2))
        job = (
            await db.execute(
                select(ProcessStartJob)
                .join(ProcessRun, ProcessRun.id == ProcessStartJob.run_id)
                .where(
                    ProcessStartJob.status == "pending",
                    ProcessStartJob.available_at <= now,
                    ProcessRun.engine_code == engine_code if engine_code is not None else true(),
                    ProcessStartJob.id == job_id if job_id is not None else true(),
                    or_(ProcessStartJob.locked_at.is_(None), ProcessStartJob.locked_at < stale_lock),
                )
                .order_by(ProcessStartJob.available_at, ProcessStartJob.id)
                .with_for_update(of=ProcessStartJob, skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            break
        job.attempts += 1
        job.locked_at = now
        metrics.observe(
            "process_start_job_lag_seconds",
            max(0.0, (now - job.created_at).total_seconds()),
        )
        attempt = job.attempts
        run = await db.get(ProcessRun, job.run_id)
        if run is None or run.status != "queued":
            job.status = "cancelled" if run and run.status == "cancelled" else "done"
            await db.commit()
            processed += 1
            continue
        process = (
            await db.execute(
                select(ProcessDefinition)
                .where(ProcessDefinition.id == run.process_id)
                .execution_options(include_historized=True)
            )
        ).scalar_one()
        await db.commit()
        started = asyncio.get_running_loop().time()
        try:
            try:
                snapshot = LaunchSnapshot.model_validate(run.launch_snapshot)
            except ValidationError as error:
                # Invalid/future launch data must never invoke an external effect,
                # nor poison all subsequent jobs in this engine's queue.
                raise ProcessEngineError(
                    "invalid_launch_snapshot", "Unsupported or invalid durable launch snapshot",
                ) from error
            payload = ProcessStartPayload(
                input=snapshot.input, files=snapshot.files,
                launch_snapshot=snapshot.model_dump(mode="json"),
            )
            engine = registry.get(run.engine_code)
            result = await asyncio.wait_for(
                engine.start_run(
                    process.engine_process_id or "",
                    _engine_run_reference(run),
                    payload,
                ),
                timeout=(engine.start_timeout_seconds if isinstance(engine, IntegratedProcessEngine)
                         else runtime_settings.PROCESS_START_TIMEOUT_SECONDS),
            )
            if not result.accepted:
                raise ProcessEngineError(
                    "engine_rejected",
                    await tr("process.errors.engine_rejected"),
                )
        except BufferedAdmissionDeferred:
            locked_job = (await db.execute(
                select(ProcessStartJob).where(ProcessStartJob.id == job.id)
                .with_for_update().execution_options(populate_existing=True)
            )).scalar_one()
            locked_job.attempts = max(0, locked_job.attempts - 1)
            locked_job.locked_at = None
            locked_job.available_at = _utcnow() + timedelta(seconds=runtime_settings.PROCESS_START_RETRY_BACKOFF_SECONDS)
            await db.commit()
            processed += 1
            continue
        except asyncio.TimeoutError:
            exc = ProcessEngineError(
                "engine_timeout",
                await tr("process.errors.engine_timeout"),
                retryable=True,
            )
            metrics.increment("process_start_timeouts_total", engine=run.engine_code)
        except ProcessEngineError as error:
            exc = error
        except Exception as error:
            exc = ProcessEngineError("engine_unreachable", str(error), retryable=True)
        else:
            locked_job = (
                await db.execute(select(ProcessStartJob).where(ProcessStartJob.id == job.id).with_for_update())
            ).scalar_one()
            locked_run = await _locked_run(run.id)
            if locked_run is None:
                locked_job.status = "failed"
                await db.commit()
                continue
            if locked_run.status not in TERMINAL_STATUSES:
                locked_run.engine_run_id = result.engine_run_id or locked_run.engine_run_id
                locked_run.raw_snapshot = cast(dict[str, Any], await _sanitize(result.raw))
            locked_job.status = "done"
            locked_job.locked_at = None
            if locked_run.status == "queued":
                await _transition(
                    locked_run, "running", event_type="engine.start.accepted",
                    payload={"engine_run_id": result.engine_run_id},
                )
            else:
                await _append_event(
                    locked_run, "engine.start.accepted", payload={
                        "engine_run_id": result.engine_run_id,
                        "status_preserved": locked_run.status,
                    },
                )
            metrics.observe(
                "process_start_latency_seconds",
                asyncio.get_running_loop().time() - started,
                engine=locked_run.engine_code,
            )
            await db.commit()
            await websocket.emit("process_run", "update", {"id": str(locked_run.id), "status": locked_run.status}, None)
            processed += 1
            continue

        max_retries = runtime_settings.PROCESS_START_MAX_RETRIES
        locked_job = (
            await db.execute(select(ProcessStartJob).where(ProcessStartJob.id == job.id).with_for_update())
        ).scalar_one()
        locked_run = await _locked_run(run.id)
        if locked_run is None:
            locked_job.status = "failed"
            await db.commit()
            continue
        if locked_run.status in TERMINAL_STATUSES:
            # A callback can finish the run before the start response arrives.
            # Its durable outcome outranks a lost or rejected HTTP response.
            locked_job.status = "done"
            locked_job.locked_at = None
            await _append_event(locked_run, "engine.start.failed", payload={
                "code": exc.code, "status_preserved": locked_run.status,
            })
            await db.commit()
            await _resolve_await_if_terminal(locked_run)
            processed += 1
            continue
        if exc.retryable and attempt < max_retries and locked_run.status == "queued":
            base = runtime_settings.PROCESS_START_RETRY_BACKOFF_SECONDS
            delay = min(base * (2 ** max(0, attempt - 1)), 3600.0)
            locked_job.available_at = _utcnow() + timedelta(seconds=delay)
            locked_job.locked_at = None
            await _append_event(locked_run, "engine.start.retry", payload={
                "attempt": attempt, "delay_seconds": delay, "code": exc.code,
            })
            metrics.increment("process_start_retries_total", process_code=process.engine_process_id)
        else:
            locked_job.status = "failed"
            locked_job.locked_at = None
            locked_run.error_code = "engine_unreachable" if exc.retryable else exc.code
            locked_run.error_message = str(await _sanitize(exc.message))
            await _transition(locked_run, "error", event_type="run.failed", payload={"code": exc.code})
            metrics.increment(
                "process_runs_failed_total", process_code=process.engine_process_id,
                engine=locked_run.engine_code, error_code=locked_run.error_code or "unknown",
            )
        await db.commit()
        # A terminal start failure must wake the synthetic child created for a
        # caller awaiting this process.  Callback and refresh transitions already
        # do this; start-job exhaustion is another terminal path and must obey the
        # same fan-in contract.
        await _resolve_await_if_terminal(locked_run)
        processed += 1
    return processed


async def purge_retention(*, preview: bool = False, batch_size: int = 100) -> dict[str, int]:
    from .retention import purge_retention as purge

    return await purge(preview=preview, batch_size=batch_size)


async def file_reference(run_id: UUID, file_id: str, token: str) -> ProcessFileRef:
    run = await get_run(run_id)
    if run is None:
        raise LookupError(await tr("process.errors.run_not_found"))
    if not secrets.compare_digest(token or "", run.callback_token):
        raise PermissionError(await tr("process.errors.invalid_file_token"))
    snapshot = LaunchSnapshot.model_validate(run.launch_snapshot)
    for ref in snapshot.files:
        if ref.id == file_id:
            if ref.expires_at < _utcnow():
                raise PermissionError(await tr("process.errors.file_reference_expired"))
            return ref
    raise PermissionError(await tr("process.errors.file_wrong_run"))
