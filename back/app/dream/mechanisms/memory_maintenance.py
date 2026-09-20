"""Run deterministic Memory finding policies through the Dream scheduler."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import String, case, cast, exists, func, literal, select

from app.memory import (
    MemoryEmbeddingChunk,
    MemoryFinding,
    MemoryItem,
    detect_memory_findings,
)
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


class MemoryMaintenanceMechanism:
    """Detect and optionally resolve Memory findings without using an LLM."""

    key = "memory.maintain_findings"
    # Receipts provide crash recovery, but this high-volume mechanical work is
    # deliberately absent from the gauges reserved for substantial Dream work.
    monitoring_visible = False

    @staticmethod
    def _enabled() -> bool:
        return not (
            runtime_settings.MEMORY_DUPLICATE_MODE == "off"
            and runtime_settings.MEMORY_CONTRADICTION_MODE == "off"
            and runtime_settings.MEMORY_AGING_MODE == "off"
        )

    @staticmethod
    def _policy_token() -> str:
        policy = (
            "automatic-backlog-v2:"
            f"{runtime_settings.MEMORY_DUPLICATE_MODE}:"
            f"{runtime_settings.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD}:"
            f"{runtime_settings.MEMORY_CONTRADICTION_MODE}:"
            f"{runtime_settings.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD}:"
            f"{runtime_settings.MEMORY_AGING_MODE}:"
            f"{runtime_settings.MEMORY_AGING_AFTER_DAYS}"
        )
        return hashlib.sha256(policy.encode()).hexdigest()[:16]

    def _subject_id(self) -> Any:
        """Build a SQL identity that changes with policy, revision, day and index."""

        indexed = case(
            (
                exists(
                    select(MemoryEmbeddingChunk.id).where(
                        MemoryEmbeddingChunk.item_id == MemoryItem.id
                    )
                ).correlate(MemoryItem),
                "i1",
            ),
            else_="i0",
        )
        return func.concat(
            cast(MemoryItem.id, String),
            ":",
            cast(MemoryItem.revision, String),
            ":",
            self._policy_token(),
            ":",
            datetime.now(timezone.utc).strftime("%Y%m%d"),
            ":",
            indexed,
        )

    @staticmethod
    def _automatic_finding_kinds() -> tuple[str, ...]:
        kinds: list[str] = []
        if runtime_settings.MEMORY_DUPLICATE_MODE == "automatic":
            kinds.append("duplicate")
        if runtime_settings.MEMORY_CONTRADICTION_MODE == "automatic":
            kinds.append("contradiction")
        if runtime_settings.MEMORY_AGING_MODE == "automatic":
            kinds.append("aging")
        return tuple(kinds)

    @staticmethod
    def _eligible_item() -> Any:
        return (
            MemoryItem.owner_agent_id.is_not(None)
            & (MemoryItem.deleted_at.is_(None))
            & (MemoryItem.node_kind == "memory")
            & (MemoryItem.source_managed.is_(False))
        )

    async def is_available(self) -> bool:
        return self._enabled()

    async def count_pending(self) -> int:
        # This mechanism is intentionally hidden from monitoring gauges.
        return 0

    async def claim_one(self) -> DreamClaim | None:
        if not self._enabled():
            return None
        subject_id = self._subject_id()
        current_retry = exists(
            select(MemoryItem.id).where(
                self._eligible_item(),
                subject_id == DreamReceipt.subject_id,
            )
        )
        retry = await claim_retry(self.key, eligibility=current_retry)
        if retry is not None:
            return retry
        async with get_db_session():
            automatic_kinds = self._automatic_finding_kinds()
            automatic_priority = (
                case(
                    (
                        exists(
                            select(MemoryFinding.id).where(
                                MemoryFinding.primary_item_id == MemoryItem.id,
                                MemoryFinding.status == "pending",
                                MemoryFinding.kind.in_(automatic_kinds),
                            )
                        ),
                        0,
                    ),
                    else_=1,
                )
                if automatic_kinds
                else literal(1)
            )
            row = (
                await get_db().execute(
                    select(MemoryItem.id, subject_id.label("subject_id"))
                    .where(
                        self._eligible_item(),
                        ~exists(
                            select(DreamReceipt.id).where(
                                DreamReceipt.mechanism_key == self.key,
                                DreamReceipt.subject_kind == "memory_item",
                                DreamReceipt.subject_id == subject_id,
                            )
                        ),
                    )
                    .order_by(
                        automatic_priority,
                        MemoryItem.updated_at.asc().nullsfirst(),
                        MemoryItem.created_at,
                        MemoryItem.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            item_id, identity = row
            claim = create_running_receipt(
                mechanism_key=self.key,
                subject_kind="memory_item",
                subject_id=str(identity),
                prepared_payload={"item_id": str(item_id)},
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        item_id = claim.subject_id.split(":", 1)[0]
        return DreamPrepared(payload={"item_id": item_id})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim
        raw_item_id = payload.get("item_id")
        if not raw_item_id:
            return 0
        async with get_db_session():
            finding_ids = await detect_memory_findings(UUID(str(raw_item_id)))
        return len(finding_ids)


memory_maintenance_mechanism = MemoryMaintenanceMechanism()


__all__ = ["MemoryMaintenanceMechanism", "memory_maintenance_mechanism"]
