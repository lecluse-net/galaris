"""Repair canonical document structure one source at a time, without a model."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select

from app.memory import MemoryItem, DocumentTag
from app.memory.facade import reconcile_structure_subject
from core.database import get_db, get_db_session

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


class DocumentStructureMechanism:
    key = "memory.document_structure"
    monitoring_visible = False

    async def is_available(self) -> bool:
        return True

    async def count_pending(self) -> int:
        return 0

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        day = datetime.now(timezone.utc).date().isoformat()
        async with get_db_session():
            for kind, model in (("document", MemoryItem), ("folder", DocumentTag)):
                stamp = MemoryItem.lock_version if model is MemoryItem else DocumentTag.updated_at
                identity = func.concat(kind, ":", model.id, ":", stamp, ":", day)
                query = select(model.id, identity).where(~exists(select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key, DreamReceipt.subject_id == identity,
                )))
                if model is MemoryItem:
                    query = query.where(MemoryItem.node_kind == "document")
                row = (await get_db().execute(query.order_by(model.id).limit(1).with_for_update(skip_locked=True))).one_or_none()
                if row is not None:
                    claim = create_running_receipt(mechanism_key=self.key, subject_kind=kind,
                        subject_id=str(row[1]), prepared_payload={"identity": str(row[0])})
                    await get_db().flush()
                    return claim
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        return DreamPrepared(payload={"identity": claim.subject_id.split(":")[1]})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        async with get_db_session():
            return await reconcile_structure_subject(claim.subject_kind, UUID(str(payload["identity"])))


document_structure_mechanism = DocumentStructureMechanism()
