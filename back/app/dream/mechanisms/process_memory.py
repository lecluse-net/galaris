"""Project canonical Process procedures and successful outputs without an LLM."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.memory.process_projection import (
    sync_process_definition_projection,
    sync_process_run_projection,
)
from app.process import ProcessDefinition, ProcessRun
from core.database import get_db, get_db_session

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


_SCAN_PAGE_SIZE = 100
_COUNT_CHUNK_SIZE = 1_000


def _stamp(*values: object | None) -> str:
    return ":".join(
        value.isoformat()
        if isinstance(value, datetime)
        else (str(value) if value is not None else "-")
        for value in values
    )


def _definition_subject_id(
    definition_id: int,
    updated_at: object | None,
    deleted_at: object | None,
) -> str:
    return f"definition:{definition_id}:{_stamp(updated_at, deleted_at)}"


def _run_subject_id(
    run_id: UUID,
    status: str,
    updated_at: object | None,
    deleted_at: object | None,
) -> str:
    return f"run:{run_id}:{status}:{_stamp(updated_at, deleted_at)}"


async def _count_unprocessed(subject_ids: list[str]) -> int:
    processed = 0
    for offset in range(0, len(subject_ids), _COUNT_CHUNK_SIZE):
        chunk = subject_ids[offset : offset + _COUNT_CHUNK_SIZE]
        processed += int(
            await get_db().scalar(
                select(func.count(DreamReceipt.id)).where(
                    DreamReceipt.mechanism_key
                    == ProcessMemoryMechanism.key,
                    DreamReceipt.subject_kind == "process_projection",
                    DreamReceipt.subject_id.in_(chunk),
                )
            )
            or 0
        )
    return len(subject_ids) - processed


class ProcessMemoryMechanism:
    key = "memory.project_process"

    async def is_available(self) -> bool:
        return True

    async def _claim_first_unprocessed(self, subject_ids: list[str]) -> DreamClaim | None:
        if not subject_ids:
            return None
        db = get_db()
        receipts = select(DreamReceipt.subject_id).where(
            DreamReceipt.mechanism_key == self.key,
            DreamReceipt.subject_kind == "process_projection",
        )
        processed = set(await db.scalars(receipts.where(DreamReceipt.subject_id.in_(subject_ids))))
        for subject_id in subject_ids:
            if subject_id in processed:
                continue
            # Recheck the candidate before creating a receipt in case another
            # worker claimed it after this page was read.
            if await db.scalar(receipts.where(DreamReceipt.subject_id == subject_id)) is not None:
                continue
            claim = create_running_receipt(
                mechanism_key=self.key,
                subject_kind="process_projection",
                subject_id=subject_id,
            )
            await db.flush()
            return claim
        return None

    async def count_pending(self) -> int:
        async with get_db_session():
            definitions = (
                await get_db().execute(
                    select(
                        ProcessDefinition.id,
                        ProcessDefinition.updated_at,
                        ProcessDefinition.deleted_at,
                    )
                    .execution_options(include_historized=True)
                )
            ).all()
            runs = (
                await get_db().execute(
                    select(
                        ProcessRun.id,
                        ProcessRun.status,
                        ProcessRun.updated_at,
                        ProcessRun.deleted_at,
                    )
                    .where(
                        ProcessRun.status.in_(
                            ("success", "error", "cancelled")
                        )
                    )
                    .execution_options(include_historized=True)
                )
            ).all()
            subject_ids = [
                _definition_subject_id(
                    definition_id,
                    updated_at,
                    deleted_at,
                )
                for definition_id, updated_at, deleted_at in definitions
            ]
            subject_ids.extend(
                _run_subject_id(
                    run_id,
                    status,
                    updated_at,
                    deleted_at,
                )
                for run_id, status, updated_at, deleted_at in runs
            )
            return await _count_unprocessed(subject_ids)

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            offset = 0
            while True:
                definitions = (
                    await get_db().execute(
                        select(
                            ProcessDefinition.id,
                            ProcessDefinition.updated_at,
                            ProcessDefinition.deleted_at,
                        )
                        .execution_options(include_historized=True)
                        .order_by(ProcessDefinition.created_at, ProcessDefinition.id)
                        .offset(offset)
                        .limit(_SCAN_PAGE_SIZE)
                    )
                ).all()
                claim = await self._claim_first_unprocessed([
                    _definition_subject_id(definition_id, updated_at, deleted_at)
                    for definition_id, updated_at, deleted_at in definitions
                ])
                if claim is not None:
                    return claim
                if len(definitions) < _SCAN_PAGE_SIZE:
                    break
                offset += _SCAN_PAGE_SIZE

            offset = 0
            while True:
                runs = (
                    await get_db().execute(
                        select(
                            ProcessRun.id,
                            ProcessRun.status,
                            ProcessRun.updated_at,
                            ProcessRun.deleted_at,
                        )
                        .where(ProcessRun.status.in_(("success", "error", "cancelled")))
                        .execution_options(include_historized=True)
                        .order_by(ProcessRun.created_at, ProcessRun.id)
                        .offset(offset)
                        .limit(_SCAN_PAGE_SIZE)
                    )
                ).all()
                claim = await self._claim_first_unprocessed([
                    _run_subject_id(run_id, status, updated_at, deleted_at)
                    for run_id, status, updated_at, deleted_at in runs
                ])
                if claim is not None:
                    return claim
                if len(runs) < _SCAN_PAGE_SIZE:
                    break
                offset += _SCAN_PAGE_SIZE
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        parts = claim.subject_id.split(":", 2)
        if len(parts) < 2:
            raise ValueError("Invalid Process projection subject.")
        return DreamPrepared(
            payload={"source_kind": parts[0], "source_id": parts[1]},
            cost=0.0,
        )

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim
        source_kind = str(payload["source_kind"])
        source_id = str(payload["source_id"])
        async with get_db_session():
            if source_kind == "definition":
                item = await sync_process_definition_projection(
                    int(source_id)
                )
            elif source_kind == "run":
                item = await sync_process_run_projection(UUID(source_id))
            else:
                raise ValueError(
                    f"Unsupported Process projection kind: {source_kind}"
                )
        return int(item is not None)


process_memory_mechanism = ProcessMemoryMechanism()


__all__ = ["ProcessMemoryMechanism", "process_memory_mechanism"]
