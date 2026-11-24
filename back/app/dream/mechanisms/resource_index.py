"""Schedule shared resource indexing without storing source text in Dream receipts."""

from typing import Any

from sqlalchemy import Select, func, select

from core.database import get_db, get_db_session

from ..contracts import DreamClaim, DreamPrepared
from ..interface import file_catalogue_port
from ..models import DreamReceipt
from ..service import claim_projection_receipt, claim_retry


class ResourceIndexMechanism:
    key = "resource.index_current_content"
    _next_kind = 0

    def _handled(self) -> Select[tuple[str]]:
        return select(DreamReceipt.subject_id).where(DreamReceipt.mechanism_key == self.key, DreamReceipt.status != "success")

    async def is_available(self) -> bool:
        return file_catalogue_port() is not None

    async def count_pending(self) -> int:
        port = file_catalogue_port()
        if port is None:
            return 0
        async with get_db_session():
            return await port.resource_index_pending(self._handled())

    async def claim_one(self) -> DreamClaim | None:
        port = file_catalogue_port()
        if port is None:
            return None
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            await get_db().execute(select(func.pg_advisory_xact_lock(731846295)))
            subjects = {subject.partition(":")[0]: subject for subject in await port.resource_index_subjects(self._handled())}
            order = ("document", "file", "task", "stored", "attachment", "vectors")
            for step in range(len(order)):
                index = (self._next_kind + step) % len(order)
                if subject := subjects.get(order[index]):
                    self._next_kind = (index + 1) % len(order)
                    return await claim_projection_receipt(self.key, subject_kind=order[index], subject_id=subject)
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        return DreamPrepared(payload={})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        port = file_catalogue_port()
        if port is None:
            return 0
        async with get_db_session():
            return int(await port.index_resource(claim.subject_id))


resource_index_mechanism = ResourceIndexMechanism()
