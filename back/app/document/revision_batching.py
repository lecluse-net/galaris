"""Persist content immediately and checkpoint history after five quiet minutes.

The public revision remains a content concurrency token (including app consents).
Only immutable history snapshots are delayed; their numbers may have gaps.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db

from .models import Document, DocumentAutomationJob, DocumentRevision

QUIET_PERIOD = timedelta(minutes=5)
JOB_KIND = "document_revision"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def job_key(identity: UUID) -> str:
    return f"{JOB_KIND}:{identity}"


def settled_clause() -> ColumnElement[bool]:
    """Initial discovery also waits five minutes; pending edits block inference."""
    return (Document.created_at <= utcnow() - QUIET_PERIOD) & ~exists(
        select(DocumentAutomationJob.id).where(
            DocumentAutomationJob.idempotency_key == func.concat(JOB_KIND, ":", Document.id),
            DocumentAutomationJob.status != "success",
        )
    )


async def stage_revision(item: Document, revision: DocumentRevision) -> None:
    """One reusable durable timer per document, committed with the saved content."""
    db = get_db()
    # Lock ordering is source then job, both here and in the worker.
    await db.flush()
    values = dict(kind=JOB_KIND, idempotency_key=job_key(item.id), status="pending",
        attempts=0, locked_at=None, last_error=None, available_at=utcnow() + QUIET_PERIOD,
        payload={"document_id": str(item.id), "revision": item.revision,
            "author_agent_id": revision.author_agent_id, "author_user_id": revision.author_user_id,
            "task_id": str(revision.task_id) if revision.task_id else None,
            "document_append": revision.document_append})
    await db.execute(insert(DocumentAutomationJob).values(**values).on_conflict_do_update(
        index_elements=[DocumentAutomationJob.idempotency_key], set_=values))


async def seal_revision(identity: UUID, expected_revision: int) -> bool:
    """Called by the leased worker; stale claims cannot seal a newer edit."""
    from .resource_service import revision_for

    db = get_db()
    item = await db.scalar(select(Document).where(Document.id == identity)
        .with_for_update().execution_options(populate_existing=True))
    if item is None or item.revision != expected_revision:
        return False
    job = await db.scalar(select(DocumentAutomationJob).where(
        DocumentAutomationJob.idempotency_key == job_key(identity))
        .execution_options(populate_existing=True))
    if job is None or job.available_at > utcnow() or job.payload["revision"] != item.revision:
        return False
    previous_hash = await db.scalar(select(DocumentRevision.content_hash).where(DocumentRevision.document_id == identity)
        .order_by(DocumentRevision.revision.desc()).limit(1))
    # Returning to the last checkpoint creates no redundant history entry.
    if previous_hash == item.content_hash:
        return False
    payload = job.payload
    db.add(revision_for(item, author_agent_id=payload.get("author_agent_id"),
        author_user_id=payload.get("author_user_id"),
        task_id=UUID(payload["task_id"]) if payload.get("task_id") else None,
        document_append=bool(payload.get("document_append"))))
    await db.flush()
    return True
