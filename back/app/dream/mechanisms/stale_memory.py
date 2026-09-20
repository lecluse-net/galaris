"""Deterministically forget expired or long-unused governed memories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from app.memory import MemoryItem
from app.memory.service import forget_stale_item
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


_CLAIM_SCAN_LIMIT = 100
_COUNT_CHUNK_SIZE = 1_000


def _subject_id(item: MemoryItem) -> str:
    return _subject_key(item.id, item.activity_at)


def _subject_key(item_id: UUID, activity_at: datetime) -> str:
    return f"{item_id}:{activity_at.isoformat()}"


class StaleMemoryMechanism:
    key = "memory.forget_stale"

    async def is_available(self) -> bool:
        return True

    async def count_pending(self) -> int:
        now = datetime.now(timezone.utc)
        forget_after_days = runtime_settings.MEMORY_FORGET_AFTER_DAYS
        stale_clause = MemoryItem.valid_until <= now
        if forget_after_days > 0:
            stale_clause = or_(
                stale_clause,
                MemoryItem.activity_at
                <= now - timedelta(days=forget_after_days),
            )

        async with get_db_session():
            candidates = (
                await get_db().execute(
                    select(MemoryItem.id, MemoryItem.activity_at).where(
                        MemoryItem.source_managed.is_(False),
                        stale_clause,
                    )
                )
            ).all()
            subject_ids = [
                _subject_key(item_id, activity_at)
                for item_id, activity_at in candidates
            ]
            processed = 0
            for offset in range(0, len(subject_ids), _COUNT_CHUNK_SIZE):
                chunk = subject_ids[offset : offset + _COUNT_CHUNK_SIZE]
                processed += int(
                    await get_db().scalar(
                        select(func.count(DreamReceipt.id)).where(
                            DreamReceipt.mechanism_key == self.key,
                            DreamReceipt.subject_kind == "memory_activity",
                            DreamReceipt.subject_id.in_(chunk),
                        )
                    )
                    or 0
                )
            return len(subject_ids) - processed

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry

        now = datetime.now(timezone.utc)
        forget_after_days = runtime_settings.MEMORY_FORGET_AFTER_DAYS
        stale_clause = MemoryItem.valid_until <= now
        if forget_after_days > 0:
            stale_clause = or_(
                stale_clause,
                MemoryItem.activity_at
                <= now - timedelta(days=forget_after_days),
            )

        async with get_db_session():
            candidates = list(
                (
                    await get_db().scalars(
                        select(MemoryItem)
                        .where(
                            MemoryItem.source_managed.is_(False),
                            stale_clause,
                        )
                        .order_by(MemoryItem.activity_at, MemoryItem.id)
                        .with_for_update(skip_locked=True)
                        .limit(_CLAIM_SCAN_LIMIT)
                    )
                ).all()
            )
            for item in candidates:
                subject_id = _subject_id(item)
                already_processed = await get_db().scalar(
                    select(DreamReceipt.id).where(
                        DreamReceipt.mechanism_key == self.key,
                        DreamReceipt.subject_kind == "memory_activity",
                        DreamReceipt.subject_id == subject_id,
                    )
                )
                if already_processed is not None:
                    continue
                claim = create_running_receipt(
                    mechanism_key=self.key,
                    subject_kind="memory_activity",
                    subject_id=subject_id,
                )
                await get_db().flush()
                return claim
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        item_id_text, activity_text = claim.subject_id.split(":", 1)
        return DreamPrepared(
            payload={
                "item_id": item_id_text,
                "expected_activity_at": activity_text,
                "forget_after_days": (
                    runtime_settings.MEMORY_FORGET_AFTER_DAYS
                ),
            },
            cost=0.0,
        )

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim
        item_id = UUID(str(payload["item_id"]))
        expected_activity_at = datetime.fromisoformat(
            str(payload["expected_activity_at"])
        )
        forget_after_days = int(payload["forget_after_days"])
        async with get_db_session():
            result = await forget_stale_item(
                item_id,
                expected_activity_at=expected_activity_at,
                forget_after_days=forget_after_days,
            )
        return int(result is not None)


stale_memory_mechanism = StaleMemoryMechanism()


__all__ = ["StaleMemoryMechanism", "stale_memory_mechanism"]
