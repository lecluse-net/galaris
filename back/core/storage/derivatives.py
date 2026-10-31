"""Source-locked publication of disposable projections; these functions grant no access."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextvars import Context
import json
from uuid import UUID
from typing import TypeVar

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db, get_db_session
from core.util import complete_io
from .models import StoredFile, StoredFileDerivative

MAX_DERIVATIVE_BYTES = 64 * 1024 * 1024
_T = TypeVar('_T')
_cleanup: list[Callable[[Sequence[UUID]], Awaitable[None]]] = []


def register_file_derivative_cleanup(callback: Callable[[Sequence[UUID]], Awaitable[None]]) -> None:
    """Bind disposable workspace cleanup at composition; callbacks must not run SQL.

    Retirement owns the source lock. Losing a rebuildable cache on rollback is safe;
    source bytes and SQL projections retain their transactional guarantees.
    """
    if callback not in _cleanup:
        _cleanup.append(callback)


async def discard_file_derivative_workspaces(file_ids: Sequence[UUID]) -> None:
    for callback in _cleanup:
        await callback(file_ids)


async def register_live_file_workspace(file_id: UUID, source_sha256: str, register: Callable[[], _T]) -> _T:
    """Register a local workspace while holding the same lock as source retirement.

    The callback only registers/creates a disposable directory; conversion, network
    calls and caller-session operations belong outside this short worker transaction.
    """
    async def live() -> _T:
        async with get_db_session() as db:
            source = await db.scalar(select(StoredFile).where(StoredFile.id == file_id).with_for_update()
                .execution_options(include_historized=True, populate_existing=True))
            if source is None or source.deleted_at is not None or source.sha256 != source_sha256:
                raise FileNotFoundError('Document source was deleted or replaced')
            return register()

    return await asyncio.create_task(live(), context=Context())


async def publish_file_derivative(
    file_id: UUID, namespace: str, fingerprint: str, payload: dict[str, JsonValue], *, source_sha256: str,
) -> bool:
    """Await an infrastructure worker with its own short transaction and no caller session.

    This rebuildable projection must neither commit caller changes nor inherit a
    session into concurrent work. Cancellation drains/rolls back the awaited worker.
    """
    async def publish() -> bool:
        async with get_db_session():
            return await write_file_derivative(file_id, namespace, fingerprint, payload,
                                               source_sha256=source_sha256)

    return await asyncio.create_task(publish(), context=Context())


async def read_file_derivative(file_id: UUID, namespace: str, fingerprint: str) -> dict[str, JsonValue] | None:
    """Caller must authorize its exact domain reference before reading a projection."""
    return await get_db().scalar(select(StoredFileDerivative.payload).join(
        StoredFile, StoredFile.id == StoredFileDerivative.file_id,
    ).where(StoredFileDerivative.file_id == file_id, StoredFileDerivative.namespace == namespace,
            StoredFileDerivative.fingerprint == fingerprint, StoredFile.deleted_at.is_(None)))


async def write_file_derivative(
    file_id: UUID, namespace: str, fingerprint: str, payload: dict[str, JsonValue], *, source_sha256: str,
) -> bool:
    """Publish under the same row lock as retirement; a deleted file cannot be resurrected.

    No provider call belongs inside this short transaction. The caller owns commit.
    """
    if not namespace or len(namespace) > 80 or len(fingerprint) != 64:
        raise ValueError("Invalid file derivative identity")
    if await complete_io(lambda: len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())) > MAX_DERIVATIVE_BYTES:
        return False
    db = get_db()
    source = await db.scalar(select(StoredFile).where(StoredFile.id == file_id).with_for_update()
                             .execution_options(include_historized=True, populate_existing=True))
    if source is None or source.deleted_at is not None or source.sha256 != source_sha256:
        return False
    statement = insert(StoredFileDerivative).values(file_id=file_id, namespace=namespace,
        fingerprint=fingerprint, payload=payload)
    await db.execute(statement.on_conflict_do_update(
        index_elements=[StoredFileDerivative.file_id, StoredFileDerivative.namespace],
        set_={"fingerprint": fingerprint, "payload": payload},
    ))
    return True
