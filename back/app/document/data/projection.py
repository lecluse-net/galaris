"""Coalesced Document notifications published only after Data commits."""
import asyncio
from contextvars import Context
from typing import Any
from uuid import UUID

from loguru import logger
from core.database import after_commit
from app.document import DatasetProjectionWriter
from .models import Dataset

_pending: dict[UUID, dict[str, Any]] = {}
_invalidate_access = False
_worker: asyncio.Task[None] | None = None

def register_projection_writer(writer: DatasetProjectionWriter) -> None:
    """Retained import contract; there is no second writable projection."""
    pass

async def _publish() -> None:
    global _invalidate_access
    from core import websocket
    try:
        while _pending or _invalidate_access:
            invalidate_access = _invalidate_access
            _invalidate_access = False
            while _pending:
                _, payload = _pending.popitem()
                await websocket.emit("document", "update", payload)
            if invalidate_access:
                await websocket.emit("document", "invalidate", {})
    except Exception:
        logger.exception("Unable to publish committed Data document changes")

def _wake() -> None:
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_publish(), context=Context())

def _enqueue(identity: UUID, payload: dict[str, Any]) -> None:
    _pending[identity] = payload
    _wake()

def _enqueue_access_invalidation() -> None:
    global _invalidate_access
    _invalidate_access = True
    _wake()

async def changed(dataset: Dataset, *, invalidate_access: bool = True) -> None:
    identity = dataset.id
    payload = {"id": str(identity), "node_kind": "document", "revision": dataset.revision,
        "lock_version": dataset.lock_version, "owner_agent_id": dataset.owner_agent_id,
        "owner_user_id": dataset.owner_user_id}
    # Content writes refresh readers without stopping every consented HTML app.
    # Keep an access invalidation even if this transaction also writes content.
    after_commit(lambda: _enqueue(identity, payload), key=("data-document", identity))
    if invalidate_access:
        after_commit(_enqueue_access_invalidation, key="data-document-access")
