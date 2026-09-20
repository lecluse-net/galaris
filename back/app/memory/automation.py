"""Durable, idempotent post-task memory capture and maintenance worker."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import case, false, func, select, update

from app.agent.contracts import AgentTask, ExecutionResult, normalize_tool_name
from core.database import get_db, get_db_session
from core.i18n import normalize_language, t
from core.params import runtime_settings

from . import acquisition_service
from .models import MemoryAutomationJob, MemoryItem, MemorySource
from .schemas import (
    MemoryAcquisitionCreate,
    MemoryLinkReconciliationJobStatus,
    MemoryLinkReconciliationStatus,
)
from .safety import redact_secrets
from .storage import get_storage

_WORD_RE = re.compile(r"[^\W\d_][\w'-]{2,}", re.UNICODE)
_STOPWORDS = {
    "avec",
    "dans",
    "des",
    "elle",
    "est",
    "les",
    "mais",
    "nous",
    "pour",
    "que",
    "qui",
    "sur",
    "une",
    "vous",
    "and",
    "for",
    "from",
    "that",
    "the",
    "this",
    "was",
    "with",
    "your",
}
_CONTRADICTION_MARKERS = (
    "correction",
    "contrairement",
    "n'est plus",
    "ne doit plus",
    "actually",
    "contrary",
    "no longer",
    "instead of",
)
_EXPLICIT_MEMORY_CAPTURE_TOOLS = frozenset(
    {
        "memory_index",
        "memory_remember",
        "memory_summarize",
    }
)
_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX = "link_reconcile_global:"
_AFTER_DREAM_TRIGGER_MODES = frozenset(
    {"after_dream", "after_dream_and_scheduled"}
)
_SCHEDULED_TRIGGER_MODES = frozenset(
    {"scheduled", "after_dream_and_scheduled"}
)
_EMBEDDING_JOB_KINDS = frozenset({"semantic_index", "semantic_reconcile"})
_EMBEDDING_PROVIDER_RETRY_DELAY = timedelta(minutes=5)


@dataclass(frozen=True)
class _ClaimedJob:
    id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int


class _ForegroundWorkActive(RuntimeError):
    """Daily graph maintenance must wait for foreground work to finish."""


def _task_status(task: AgentTask) -> str:
    raw = getattr(task.status, "value", task.status)
    return str(raw).upper()


_redact_secrets = redact_secrets


def _keywords(text: str) -> list[str]:
    words = [word.casefold() for word in _WORD_RE.findall(text)]
    counts = Counter(word for word in words if word not in _STOPWORDS)
    return [word for word, _count in counts.most_common(10)]


def _memory_type(objective: str, result: ExecutionResult) -> str:
    text = f"{objective}\n{result.result}".casefold()
    if any(marker in text for marker in ("je préfère", "j'aime", "i prefer", "always use")):
        return "core"
    if result.tools_used or any(
        marker in text for marker in ("procédure", "procedure", "étapes", "steps")
    ):
        return "procedural"
    if any(marker in text for marker in ("a décidé", "décision", "decided", "decision")):
        return "semantic"
    return "episodic"


def _is_conversational_task(task: AgentTask, data: Mapping[str, Any]) -> bool:
    """Identify Tasks whose context belongs to a Messenger session by default."""

    return bool(
        task.message_platform
        or task.message_group_id
        or data.get("connection_id")
        or data.get("message_id")
    )


def _capture_was_explicitly_handled(result: ExecutionResult) -> bool:
    """Avoid storing the same memory after an explicit memory tool call."""

    return any(
        normalize_tool_name(tool_name).casefold() in _EXPLICIT_MEMORY_CAPTURE_TOOLS
        for tool_name in result.tools_used
    )


async def enqueue_terminal_capture(task: AgentTask) -> None:
    """Persist a small capture job; never perform extraction on the response path."""

    if not runtime_settings.MEMORY_CAPTURE_ENABLED:
        return
    if _task_status(task) != "SUCCESS" or task.agent_id is None:
        return
    if task.parent_id is not None:
        return
    # Goal and GoalCycle data have their own deterministic source projections.
    # Capturing their Task again would create an unrelated duplicate memory.
    if task.goal_id is not None:
        return
    result = task.get_execution_result()
    if result is None or not result.success:
        return
    data = dict(task.data or {})
    if data.get("memory_capture") is False:
        return
    if _capture_was_explicitly_handled(result):
        return
    if _is_conversational_task(task, data) and data.get("memory_capture") is not True:
        return
    objective = str(task.objective or "").strip()
    answer = str(result.result or "").strip()
    if len(objective) + len(answer) < runtime_settings.MEMORY_CAPTURE_MIN_CHARS:
        return
    key = f"task_capture:{task.id}"
    db = get_db()
    existing = await db.scalar(
        select(MemoryAutomationJob.id).where(
            MemoryAutomationJob.idempotency_key == key
        )
    )
    if existing is not None:
        return
    db.add(
        MemoryAutomationJob(
            kind="task_capture",
            idempotency_key=key,
            payload={
                "task_id": str(task.id),
                "agent_id": task.agent_id,
                "label": str(task.label or "")[:500],
                "objective": objective[:50_000],
                "answer": answer[:100_000],
                "tools_used": list(result.tools_used),
                "message_platform": task.message_platform,
                "message_group_id": task.message_group_id,
                "language": normalize_language(data.get("language")),
            },
        )
    )
    await db.commit()


async def enqueue_source_projection(
    source_kind: str,
    source_id: str,
    action: str = "upsert",
) -> None:
    """Queue a fail-open source refresh after its canonical transaction commits."""

    normalized_kind = source_kind.strip()
    normalized_id = source_id.strip()
    normalized_action = "delete" if action == "delete" else "upsert"
    if normalized_kind not in {"agent", "goal"} or not normalized_id:
        raise ValueError("A source projection job requires a supported source identity.")
    nonce = uuid4()
    get_db().add(
        MemoryAutomationJob(
            kind="source_projection",
            idempotency_key=hashlib.sha256(
                (
                    f"source_projection:{normalized_kind}:{normalized_id}:"
                    f"{normalized_action}:{nonce}"
                ).encode("utf-8")
            ).hexdigest(),
            payload={
                "source_kind": normalized_kind,
                "source_id": normalized_id,
                "action": normalized_action,
            },
        )
    )
    await get_db().commit()


async def enqueue_link_reconciliation(
    item_ids: set[UUID],
    *,
    include_suggestions: bool = True,
    trigger: str = "mutation",
) -> int:
    """Queue idempotent targeted graph convergence for concrete Memory nodes."""

    db = get_db()
    created = 0
    for item_id in sorted(item_ids, key=str):
        exists_item = await db.scalar(
            select(MemoryItem.id).where(MemoryItem.id == item_id)
        )
        if exists_item is None:
            continue
        db.add(
            MemoryAutomationJob(
                kind="link_reconcile",
                idempotency_key=hashlib.sha256(
                    (
                        f"link_reconcile:{item_id}:{trigger}:{uuid4()}"
                    ).encode("utf-8")
                ).hexdigest(),
                payload={
                    "item_id": str(item_id),
                    "include_suggestions": include_suggestions,
                    "trigger": trigger[:80],
                },
            )
        )
        created += 1
    if created:
        await db.commit()
    return created


async def enqueue_scheduled_global_link_reconciliation() -> UUID:
    """Queue one scheduled global sweep, coalescing an active sweep."""

    db = get_db()
    existing = await db.scalar(
        select(MemoryAutomationJob)
        .where(
            MemoryAutomationJob.kind == "link_reconcile",
            MemoryAutomationJob.idempotency_key.like(
                f"{_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX}%"
            ),
            MemoryAutomationJob.status.in_(("pending", "running")),
        )
        .order_by(MemoryAutomationJob.created_at)
        .limit(1)
    )
    if existing is not None:
        return existing.id

    now = datetime.now(timezone.utc)
    interval_seconds = (
        runtime_settings.MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS * 3_600
    )
    schedule_bucket = int(now.timestamp() // interval_seconds)
    job = MemoryAutomationJob(
        kind="link_reconcile",
        idempotency_key=(
            f"{_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX}scheduled:{schedule_bucket}"
        ),
        payload={
            "item_id": None,
            "include_suggestions": True,
            "trigger": "scheduled",
        },
    )
    db.add(job)
    await db.commit()
    return job.id


async def get_link_reconciliation_status() -> MemoryLinkReconciliationStatus:
    """Describe configured triggers and the latest global sweep."""

    db = get_db()
    global_jobs = (
        MemoryAutomationJob.kind == "link_reconcile",
        MemoryAutomationJob.idempotency_key.like(
            f"{_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX}%"
        ),
    )
    latest = await db.scalar(
        select(MemoryAutomationJob)
        .where(*global_jobs)
        .order_by(MemoryAutomationJob.created_at.desc())
        .limit(1)
    )
    latest_scheduled = await db.scalar(
        select(MemoryAutomationJob)
        .where(
            MemoryAutomationJob.kind == "link_reconcile",
            MemoryAutomationJob.idempotency_key.like(
                f"{_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX}scheduled:%"
            ),
        )
        .order_by(MemoryAutomationJob.created_at.desc())
        .limit(1)
    )
    last_completed_at = await db.scalar(
        select(MemoryAutomationJob.updated_at)
        .where(*global_jobs, MemoryAutomationJob.status == "success")
        .order_by(MemoryAutomationJob.updated_at.desc())
        .limit(1)
    )

    trigger_mode = runtime_settings.MEMORY_LINK_RECONCILIATION_TRIGGER_MODE
    scheduled_enabled = trigger_mode in _SCHEDULED_TRIGGER_MODES
    now = datetime.now(timezone.utc)
    interval = timedelta(
        hours=runtime_settings.MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS
    )
    next_scheduled_at: datetime | None = None
    if scheduled_enabled:
        due_at = (
            latest_scheduled.created_at + interval
            if latest_scheduled is not None
            else now
        )
        next_scheduled_at = max(due_at, now)

    latest_status = (
        cast(MemoryLinkReconciliationJobStatus, latest.status)
        if latest is not None
        else None
    )
    return MemoryLinkReconciliationStatus(
        trigger_mode=trigger_mode,
        after_dream_enabled=trigger_mode in _AFTER_DREAM_TRIGGER_MODES,
        scheduled_enabled=scheduled_enabled,
        interval_hours=runtime_settings.MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS,
        latest_job_status=latest_status,
        latest_job_trigger=(
            str(latest.payload.get("trigger") or "") or None
            if latest is not None
            else None
        ),
        latest_job_created_at=latest.created_at if latest is not None else None,
        last_completed_at=last_completed_at,
        next_scheduled_at=next_scheduled_at,
        job_pending=latest_status in {"pending", "running"},
    )


async def enqueue_dream_link_reconciliation(
    *,
    mechanism_key: str,
    subject_kind: str,
    subject_id: str,
    payload: Mapping[str, Any],
) -> int:
    """Resolve Memory nodes affected by one completed Dream operation."""

    if (
        runtime_settings.MEMORY_LINK_RECONCILIATION_TRIGGER_MODE
        not in _AFTER_DREAM_TRIGGER_MODES
    ):
        return 0

    item_ids: set[UUID] = set()
    async with get_db_session():
        db = get_db()
        raw_subject_id = subject_id.split(":", 1)[0]
        try:
            subject_uuid = UUID(raw_subject_id)
        except ValueError:
            subject_uuid = None
        source_query = select(MemorySource.item_id)
        if subject_uuid is not None and subject_kind in ("task", "task_outcome"):
            source_query = source_query.where(MemorySource.task_id == subject_uuid)
        elif subject_uuid is not None and subject_kind == "conversation_round":
            source_query = source_query.where(
                MemorySource.conversation_round_id == subject_uuid
            )
        else:
            source_query = source_query.where(false())
        item_ids.update((await db.scalars(source_query)).all())

        raw_item_id = payload.get("item_id")
        if raw_item_id is not None:
            try:
                item_ids.add(UUID(str(raw_item_id)))
            except ValueError:
                pass
        if subject_kind == "memory_activity" and subject_uuid is not None:
            item_ids.add(subject_uuid)

        source_kind = str(payload.get("source_kind") or "").strip()
        source_id = str(payload.get("source_id") or "").strip()
        if source_kind in {"definition", "run"} and source_id:
            managed_kind = (
                "process_definition" if source_kind == "definition" else "process_run"
            )
            managed_ref = f"{managed_kind}:{source_id}"
            projected_id = await db.scalar(
                select(MemoryItem.id).where(
                    MemoryItem.source_managed.is_(True),
                    MemoryItem.managed_source_kind == managed_kind,
                    MemoryItem.managed_source_ref == managed_ref,
                )
            )
            if projected_id is not None:
                item_ids.add(projected_id)

        return await enqueue_link_reconciliation(
            item_ids,
            include_suggestions=True,
            trigger=f"dream:{mechanism_key}",
        )


async def _claim_job() -> _ClaimedJob | None:
    async with get_db_session():
        now = datetime.now(timezone.utc)
        job = await get_db().scalar(
            select(MemoryAutomationJob)
            .where(
                MemoryAutomationJob.status == "pending",
                MemoryAutomationJob.available_at <= now,
                MemoryAutomationJob.attempts
                < runtime_settings.MEMORY_AUTOMATION_MAX_ATTEMPTS,
            )
            .order_by(MemoryAutomationJob.available_at, MemoryAutomationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_at = now
        return _ClaimedJob(
            id=job.id,
            kind=job.kind,
            payload=dict(job.payload),
            attempts=job.attempts,
        )


def _payload_int(payload: Mapping[str, Any], key: str) -> int:
    try:
        value = int(payload.get(key) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Automation payload requires integer {key}.") from exc
    if value <= 0:
        raise ValueError(f"Automation payload requires positive {key}.")
    return value


async def _process_task_capture(payload: Mapping[str, Any]) -> None:
    agent_id = _payload_int(payload, "agent_id")
    task_id = str(payload.get("task_id") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    safe_objective = _redact_secrets(objective)
    safe_answer = _redact_secrets(answer)
    if safe_objective is None or safe_answer is None:
        logger.warning("Memory capture skipped private-key material task={}", task_id)
        return
    language = normalize_language(payload.get("language"))
    combined = (
        f"{t('memory.capture.user_request', language)}:\n{safe_objective}\n\n"
        f"{t('memory.capture.outcome', language)}:\n{safe_answer}"
    )
    tools_raw = payload.get("tools_used")
    tools = (
        [str(item) for item in cast(list[Any], tools_raw)]
        if isinstance(tools_raw, list)
        else []
    )
    result = ExecutionResult(
        prompt=objective,
        result=answer,
        tools_used=tools,
        success=True,
    )
    default_title = t("memory.capture.default_title", language)
    raw_title = str(payload.get("label") or default_title).strip() or default_title
    title = _redact_secrets(raw_title)
    if title is None:
        title = default_title
    async with get_db_session():
        existing = await get_db().scalar(
            select(MemoryItem)
            .where(
                MemoryItem.owner_agent_id == agent_id,
                MemoryItem.source_managed.is_(False),
                MemoryItem.node_kind == "memory",
                func.lower(MemoryItem.title) == title[:500].casefold(),
            )
            .order_by(MemoryItem.updated_at.desc().nullslast(), MemoryItem.created_at.desc())
            .limit(1)
        )
        action = "create"
        if existing is not None:
            folded = combined.casefold()
            action = (
                "contradict"
                if any(marker in folded for marker in _CONTRADICTION_MARKERS)
                else "update"
            )
        await acquisition_service.acquire_memory(
            MemoryAcquisitionCreate(
                agent_id=agent_id,
                action=action,
                target_item_id=existing.id if existing is not None else None,
                title=title[:500],
                content=combined,
                keywords=_keywords(combined),
                source_kind="task",
                source_ref=f"task:{task_id}",
                metadata={
                    "memory_type": _memory_type(objective, result),
                    "target_revision": (
                        existing.revision if existing is not None else None
                    ),
                    "tools_used": tools,
                    "message_platform": payload.get("message_platform"),
                    "message_group_id": payload.get("message_group_id"),
                    "language": language,
                    "capture_version": 1,
                },
                idempotency_key=hashlib.sha256(
                    f"capture:{task_id}".encode("utf-8")
                ).hexdigest(),
            )
        )


async def _process_resource_cleanup(payload: Mapping[str, Any]) -> None:
    provider_code = str(payload.get("provider_code") or "").strip()
    resource_id = str(payload.get("resource_id") or "").strip()
    if not provider_code or not resource_id:
        raise ValueError("Resource cleanup payload is incomplete.")
    await get_storage(provider_code).delete(resource_id)


async def _process_consolidation(payload: Mapping[str, Any]) -> None:
    """Resume acquisitions left pending by an interrupted older runtime."""

    agent_id = _payload_int(payload, "agent_id")
    async with get_db_session():
        await acquisition_service.resolve_pending_acquisitions(agent_id=agent_id)


async def _process_source_projection(payload: Mapping[str, Any]) -> None:
    source_kind = str(payload.get("source_kind") or "").strip()
    source_id = str(payload.get("source_id") or "").strip()
    action = str(payload.get("action") or "upsert").strip()
    if not source_kind or not source_id:
        raise ValueError("Source projection payload is incomplete.")
    from .source_projection import sync_source_projection

    async with get_db_session():
        await sync_source_projection(
            source_kind=source_kind,
            source_id=source_id,
            action=action,
        )


async def _foreground_work_active() -> bool:
    from app.task import has_active_task_work
    from app.voice import has_active_voice_calls

    return has_active_voice_calls() or await has_active_task_work()


async def _process_link_reconciliation(payload: Mapping[str, Any]) -> None:
    from .link_reconciliation import MemoryLinkFamily, reconcile_memory_links

    raw_item_id = payload.get("item_id")
    item_id = UUID(str(raw_item_id)) if raw_item_id else None
    if await _foreground_work_active():
        raise _ForegroundWorkActive
    families: frozenset[MemoryLinkFamily] | None = (
        None
        if bool(payload.get("include_suggestions", True))
        else frozenset({"canonical"})
    )
    async with get_db_session():
        if item_id is not None:
            exists_item = await get_db().scalar(
                select(MemoryItem.id).where(MemoryItem.id == item_id)
            )
            if exists_item is None:
                return
        result = await reconcile_memory_links(item_id=item_id, families=families)
    logger.info("Memory-link reconciliation: {}", result.model_dump())


_last_scheduled_link_check: datetime | None = None
_last_semantic_check: datetime | None = None


async def _enqueue_scheduled_semantic_reconciliation() -> None:
    """Repair missed/legacy intents without resetting an active provider backoff."""
    global _last_semantic_check
    now = datetime.now(timezone.utc)
    if _last_semantic_check is not None and now - _last_semantic_check < timedelta(minutes=5):
        return
    from sqlalchemy.dialects.postgresql import insert

    async with get_db_session():
        await get_db().execute(insert(MemoryAutomationJob).values(
            kind="semantic_reconcile",
            idempotency_key="semantic_reconcile:periodic",
            payload={},
        ).on_conflict_do_update(
            index_elements=[MemoryAutomationJob.idempotency_key],
            set_={"status": "pending", "attempts": 0, "available_at": now, "last_error": None},
            where=MemoryAutomationJob.status.in_(("success", "error")),
        ))
    _last_semantic_check = now


async def _enqueue_scheduled_link_reconciliation() -> None:
    """Queue a due global graph sweep according to the runtime policy."""

    global _last_scheduled_link_check
    now = datetime.now(timezone.utc)
    if (
        _last_scheduled_link_check is not None
        and (now - _last_scheduled_link_check).total_seconds() < 60.0
    ):
        return
    _last_scheduled_link_check = now
    if (
        runtime_settings.MEMORY_LINK_RECONCILIATION_TRIGGER_MODE
        not in _SCHEDULED_TRIGGER_MODES
    ):
        return

    interval = timedelta(
        hours=runtime_settings.MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS
    )
    async with get_db_session():
        latest_created_at = await get_db().scalar(
            select(MemoryAutomationJob.created_at)
            .where(
                MemoryAutomationJob.kind == "link_reconcile",
                MemoryAutomationJob.idempotency_key.like(
                    f"{_GLOBAL_LINK_RECONCILIATION_KEY_PREFIX}scheduled:%"
                ),
            )
            .order_by(MemoryAutomationJob.created_at.desc())
            .limit(1)
        )
    if latest_created_at is not None and latest_created_at + interval > now:
        return
    if await _foreground_work_active():
        return
    async with get_db_session():
        await enqueue_scheduled_global_link_reconciliation()


async def _process(job: _ClaimedJob) -> None:
    if job.kind == "goal_folder_reconcile":
        from .goal_folders import GoalFolderRequest, process_goal_folder_job

        async with get_db_session():
            changed = await process_goal_folder_job(job.id, GoalFolderRequest.model_validate(job.payload))
        if changed:
            from .service import invalidate_memory_views
            await invalidate_memory_views()
    elif job.kind == "task_capture":
        await _process_task_capture(job.payload)
    elif job.kind == "resource_cleanup":
        await _process_resource_cleanup(job.payload)
    elif job.kind == "consolidate":
        await _process_consolidation(job.payload)
    elif job.kind == "source_projection":
        await _process_source_projection(job.payload)
    elif job.kind == "semantic_index":
        from .semantic_index import process_embedding_job

        await process_embedding_job(job.payload)
    elif job.kind == "semantic_reconcile":
        from .semantic_index import process_reconciliation_job

        await process_reconciliation_job()
    elif job.kind == "link_reconcile":
        await _process_link_reconciliation(job.payload)
    elif job.kind == "memory_maintenance":
        # Drain jobs queued before finding detection moved under Dream. New
        # scans are claimed exclusively by ``memory.maintain_findings``.
        logger.info("Skipping obsolete Memory maintenance job {}", job.id)
    else:
        raise ValueError(f"Unknown memory automation job kind: {job.kind!r}.")


async def _mark_success(job_id: UUID) -> None:
    async with get_db_session():
        job = await get_db().get(MemoryAutomationJob, job_id)
        if job is not None:
            job.status = "success"
            job.locked_at = None
            job.last_error = None


async def _mark_failure(job: _ClaimedJob, exc: BaseException) -> None:
    from .embedding import MemoryEmbeddingProviderUnavailableError

    async with get_db_session():
        record = await get_db().get(MemoryAutomationJob, job.id)
        if record is None:
            return
        provider_failure = job.kind in _EMBEDDING_JOB_KINDS and isinstance(exc, MemoryEmbeddingProviderUnavailableError)
        terminal = not provider_failure and job.attempts >= runtime_settings.MEMORY_AUTOMATION_MAX_ATTEMPTS
        if provider_failure:
            record.attempts = max(0, record.attempts - 1)
        record.status = "error" if terminal else "pending"
        record.locked_at = None
        record.last_error = f"{type(exc).__name__}: {exc}"[:4_000]
        delay = min(300.0, 2.0 ** min(job.attempts, 8))
        record.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)


async def _defer_embedding_jobs_after_provider_failure() -> None:
    """Apply one provider-wide backoff instead of draining a failing backlog."""

    retry_at = datetime.now(timezone.utc) + _EMBEDDING_PROVIDER_RETRY_DELAY
    async with get_db_session():
        await get_db().execute(
            update(MemoryAutomationJob)
            .where(
                MemoryAutomationJob.kind.in_(_EMBEDDING_JOB_KINDS),
                MemoryAutomationJob.status == "pending",
            )
            .values(
                available_at=func.greatest(
                    MemoryAutomationJob.available_at,
                    retry_at,
                )
            )
        )


async def _defer_for_foreground_work(job: _ClaimedJob) -> None:
    async with get_db_session():
        record = await get_db().get(MemoryAutomationJob, job.id)
        if record is None:
            return
        record.status = "pending"
        record.attempts = max(0, record.attempts - 1)
        record.locked_at = None
        record.last_error = "Deferred while foreground work is active."
        record.available_at = datetime.now(timezone.utc) + timedelta(minutes=5)


_worker_task: asyncio.Task[None] | None = None
_stopping = False


async def _worker() -> None:
    while not _stopping:
        try:
            await _enqueue_scheduled_semantic_reconciliation()
            await _enqueue_scheduled_link_reconciliation()
            job = await _claim_job()
            if job is None:
                await asyncio.sleep(runtime_settings.MEMORY_AUTOMATION_POLL_SECONDS)
                continue
            try:
                await _process(job)
            except asyncio.CancelledError:
                raise
            except _ForegroundWorkActive:
                await _defer_for_foreground_work(job)
            except BaseException as exc:
                logger.exception("Memory automation job {} failed", job.id)
                await _mark_failure(job, exc)
                from .embedding import MemoryEmbeddingProviderUnavailableError

                if isinstance(exc, MemoryEmbeddingProviderUnavailableError):
                    await _defer_embedding_jobs_after_provider_failure()
            else:
                await _mark_success(job.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Memory automation worker iteration failed")
            await asyncio.sleep(runtime_settings.MEMORY_AUTOMATION_POLL_SECONDS)


async def start_memory_automation() -> None:
    global _worker_task, _stopping
    if _worker_task is not None and not _worker_task.done():
        return
    async with get_db_session():
        # A process crash can leave claimed work in ``running``. Requeue it on
        # startup while preserving the attempt budget and idempotency key.
        await get_db().execute(
            update(MemoryAutomationJob)
            .where(MemoryAutomationJob.status == "running")
            .values(
                status=case(
                    (
                        MemoryAutomationJob.attempts
                        >= runtime_settings.MEMORY_AUTOMATION_MAX_ATTEMPTS,
                        "error",
                    ),
                    else_="pending",
                ),
                locked_at=None,
                available_at=datetime.now(timezone.utc),
            )
        )
        applied, failed = await acquisition_service.resolve_pending_acquisitions()
        if applied or failed:
            logger.info(
                "Memory acquisition recovery: applied={} failed={}",
                applied,
                failed,
            )
        from .source_projection import rebuild_source_memories

        rebuilt = await rebuild_source_memories(missing_only=True)
        if (
            rebuilt.agents_scanned
            or rebuilt.goals_scanned
            or rebuilt.orphans_removed
            or rebuilt.stale_cycles_removed
            or rebuilt.failures
        ):
            logger.info("Source-memory startup reconciliation: {}", rebuilt.model_dump())
        # DbAdmin reconciles existing generations. The periodic worker repairs
        # later drift; do not run a second full index scan in the lifespan.
    _stopping = False
    _worker_task = asyncio.create_task(_worker(), name="memory_automation")


async def stop_memory_automation() -> None:
    global _worker_task, _stopping
    _stopping = True
    if _worker_task is not None:
        _worker_task.cancel()
        await asyncio.gather(_worker_task, return_exceptions=True)
        _worker_task = None
    from .topic_maintenance import stop_topic_maintenance

    stop_topic_maintenance()


def memory_automation_running() -> bool:
    return _worker_task is not None and not _worker_task.done()


__all__ = [
    "enqueue_dream_link_reconciliation",
    "enqueue_link_reconciliation",
    "enqueue_scheduled_global_link_reconciliation",
    "enqueue_source_projection",
    "enqueue_terminal_capture",
    "get_link_reconciliation_status",
    "memory_automation_running",
    "start_memory_automation",
    "stop_memory_automation",
]
