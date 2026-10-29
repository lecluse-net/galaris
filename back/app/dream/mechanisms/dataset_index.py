"""Dream schedules Dataset-owned, revision-guarded embedding maintenance."""

from typing import Any

from sqlalchemy import select

from app.dataset import facade as datasets
from app.llm import EmbeddingNotConfiguredError, require_configured_embedding_model
from core.database import get_db_session

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


class DatasetIndexMechanism:
    key = "resource.index_dataset"

    async def is_available(self) -> bool:
        async with get_db_session():
            try:
                await require_configured_embedding_model()
                return True
            except EmbeddingNotConfiguredError:
                return False

    async def count_pending(self) -> int:
        async with get_db_session():
            model = await require_configured_embedding_model()
            return await datasets.count_pending_dataset_indexes(model.key,
                select(DreamReceipt.subject_id).where(DreamReceipt.mechanism_key == self.key))

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            model = await require_configured_embedding_model()
            subject = await datasets.claim_dataset_index(model.key,
                select(DreamReceipt.subject_id).where(DreamReceipt.mechanism_key == self.key))
            if subject is None:
                return None
            return create_running_receipt(mechanism_key=self.key, subject_kind="dataset", subject_id=subject)

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        async with get_db_session():
            snapshot = await datasets.dataset_index_source(claim.subject_id)
            model = await require_configured_embedding_model()
        if snapshot is None or model.key != claim.subject_id.split(":")[-1]:
            return DreamPrepared(payload={"stale": True})
        return DreamPrepared(payload=await datasets.prepare_dataset_index(snapshot, model))

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        if payload.get("stale"):
            return 0
        async with get_db_session():
            return int(await datasets.apply_dataset_index(claim.subject_id, payload))


dataset_index_mechanism = DatasetIndexMechanism()
