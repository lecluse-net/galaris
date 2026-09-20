"""Evidence-based repair of uncertain file delivery without provider resubmission."""

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.file_share import ResourceContext, materialize_resource, parse_resource_uri
from app.process.interface import engine_checkpoint
from core.database import get_db
from .models import MediaDeliveryResolution, MediaOutputReceipt
from .checkpoints import MultimediaCheckpoint


class DeliveryRepair(BaseModel):
    attempt_number: int = Field(ge=0)
    decision: Literal["attach", "retry_absent"]
    evidence: str = Field(min_length=10, max_length=4000)
    uri: str | None = Field(default=None, max_length=2048)


async def repair_delivery(
    run_id: UUID, receipt_id: UUID, request: DeliveryRepair, *, actor_user_id: int | None
) -> None:
    data = await engine_checkpoint(run_id, "multimedia")
    MultimediaCheckpoint.model_validate(data["metadata"])
    if data["terminal"]:
        raise ValueError("A terminal result cannot be changed")
    db = get_db()
    receipt = await db.scalar(
        select(MediaOutputReceipt)
        .where(
            MediaOutputReceipt.id == receipt_id,
            MediaOutputReceipt.run_id == run_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if receipt is None:
        raise LookupError("Output receipt not found")
    previous = await db.scalar(
        select(MediaDeliveryResolution).where(
            MediaDeliveryResolution.receipt_id == receipt_id,
            MediaDeliveryResolution.attempt_number == request.attempt_number,
        )
    )
    if previous is not None:
        if (
            previous.decision == request.decision
            and previous.uri == request.uri
            and previous.evidence == request.evidence
        ):
            return
        raise ValueError("This delivery attempt already has a different resolution")
    if (
        receipt.delivery_attempts != request.attempt_number
        or not receipt.delivery_started
        or receipt.uri is not None
    ):
        raise ValueError("This receipt is not awaiting repair of the specified attempt")
    if receipt.delivery_lease_until and receipt.delivery_lease_until > datetime.now(timezone.utc):
        raise ValueError("The delivery lease is still active; allow its owner to finish")
    if receipt.content is None:
        raise ValueError("The durable output content is missing")
    if request.decision == "attach":
        reference = parse_resource_uri(request.uri)
        frozen = data["input"]
        ctx = ResourceContext(data["agent_id"], frozen["runtime"], data.get("task_id"))
        with TemporaryDirectory(prefix="galaris-delivery-proof-") as directory:
            path = Path(directory) / "proof"
            await materialize_resource(ctx, reference, path, max_bytes=100_000_000)

            def remote_digest() -> bytes:
                with path.open("rb") as source:
                    return hashlib.file_digest(source, "sha256").digest()

            expected = await asyncio.to_thread(
                lambda: hashlib.sha256(receipt.content or b"").digest()
            )
            if expected != await asyncio.to_thread(remote_digest):
                raise ValueError("The selected file does not match the durable output")
        receipt.uri = str(reference)
        receipt.content = None
    else:
        if request.uri is not None:
            raise ValueError("Absence confirmation must not attach a destination URI")
        # This is an explicit operator assertion recorded below, never an
        # inference from a timeout or a provider's eventual-consistency window.
        receipt.delivery_started = False
    receipt.delivery_lease_until = None
    db.add(
        MediaDeliveryResolution(
            receipt_id=receipt.id,
            actor_user_id=actor_user_id,
            attempt_number=request.attempt_number,
            decision=request.decision,
            evidence=request.evidence,
            uri=request.uri,
        )
    )
    await db.commit()
