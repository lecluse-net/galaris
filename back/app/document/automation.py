"""Durable, leased personal-classification jobs owned by Document."""
import asyncio
from datetime import datetime,timedelta,timezone
from sqlalchemy import and_,or_,select,update
from loguru import logger
from core.database import get_db,get_db_session
from .models import DocumentAutomationJob
from .goal_folders import GoalFolderRequest,process_goal_folder_job
from .events import emit_classification
from .safety import redact_secrets

_task: asyncio.Task[None] | None=None
_LEASE=timedelta(minutes=10)


async def process_next() -> bool:
    now=datetime.now(timezone.utc)
    async with get_db_session():
        job=await get_db().scalar(select(DocumentAutomationJob).where(or_(
            and_(DocumentAutomationJob.status=="pending",DocumentAutomationJob.available_at<=now),
            and_(DocumentAutomationJob.status=="running",DocumentAutomationJob.locked_at<now-_LEASE),
        )).order_by(DocumentAutomationJob.available_at,DocumentAutomationJob.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return False
        identity,payload,kind=job.id,dict(job.payload),job.kind
        job.status,job.locked_at,job.attempts="running",now,job.attempts+1
        attempts=job.attempts
    try:
        async with get_db_session():
            if kind == "resource_cleanup":
                from core.storage import get_storage, resource_is_referenced
                provider, pointer = str(payload["provider"]), str(payload["pointer"])
                if not await resource_is_referenced(provider, pointer):
                    await get_storage(provider).delete(pointer)
                change = None
            elif kind == "goal_folder_reconcile":
                change=await process_goal_folder_job(identity,GoalFolderRequest.model_validate(payload))
            else:
                raise ValueError(f"Unsupported Document job: {kind}")
            await get_db().commit()
            if change is not None:
                await emit_classification(change.user_id,tag_ids=[change.tag_id] if change.document_ids else [],document_ids=change.document_ids,tags_changed=change.tags_changed,list_changed=bool(change.document_ids))
    except BaseException as error:
        async with get_db_session():
            await get_db().execute(update(DocumentAutomationJob).where(DocumentAutomationJob.id==identity,
                DocumentAutomationJob.status=="running",DocumentAutomationJob.locked_at==now).values(
                status="pending" if isinstance(error,asyncio.CancelledError) or attempts<5 else "error",locked_at=None,
                last_error=str(redact_secrets(f"{type(error).__name__}: {error}"))[:4000],
                available_at=datetime.now(timezone.utc)+timedelta(seconds=min(300,2**attempts))))
        if isinstance(error,asyncio.CancelledError):
            raise
        logger.exception("Document classification job {} failed",identity)
    else:
        async with get_db_session():
            await get_db().execute(update(DocumentAutomationJob).where(DocumentAutomationJob.id==identity,
                DocumentAutomationJob.status=="running",DocumentAutomationJob.locked_at==now).values(status="success",locked_at=None,last_error=None))
    return True


async def _worker() -> None:
    while True:
        try:
            if not await process_next():
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Document classification worker failed")
            await asyncio.sleep(2)


async def start_document_automation() -> None:
    global _task
    if _task is None or _task.done():
        _task=asyncio.create_task(_worker(),name="document_classification")


async def stop_document_automation() -> None:
    global _task
    task,_task=_task,None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def document_automation_running() -> bool:
    return _task is not None and not _task.done()
