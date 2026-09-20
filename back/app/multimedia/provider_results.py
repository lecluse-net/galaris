"""Persist provider observations and output receipts before delivery can begin."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.file_share import read_public_https_bytes
from app.llm import MediaResult
from app.llm.facade import finish_media_call
from app.process.interface import engine_checkpoint
from core.database import get_db
from core.util import as_dict

from .checkpoints import MultimediaCheckpoint
from .models import MediaOutputReceipt


async def receive_result(run_id: UUID, result: MediaResult) -> None:
    checkpoint = await engine_checkpoint(run_id, "multimedia")
    MultimediaCheckpoint.model_validate(checkpoint["metadata"])
    if checkpoint["terminal"]:
        return
    if result.state != "success":
        observation: dict[str, Any] = {
            "provider_state": result.state,
            "provider_error": result.error,
        }
        if result.external_id:
            observation.update(external_id=result.external_id, submission="accepted")
        accepted = await engine_checkpoint(
            run_id,
            "multimedia",
            observation,
            preserve_if={"provider_outcome": "success", "provider_state": "success"},
        )
        if accepted["applied"] and result.state == "error":
            call_id = as_dict(accepted["metadata"]).get("call_id")
            if call_id:
                await finish_media_call(UUID(str(call_id)), result)
        return
    if not result.artifacts or len(result.artifacts) > 4:
        raise ValueError("The provider returned no usable media outputs.")
    accepted = await engine_checkpoint(
        run_id,
        "multimedia",
        {
            "multimedia_version": 1,
            "provider_outcome": "success",
            "provider_state": "waiting",
            "provider_error": None,
            **(
                {"external_id": result.external_id, "submission": "accepted"}
                if result.external_id
                else {}
            ),
            "output_manifest": [
                {"external_id": item.external_id, "media_type": item.media_type, "url": item.url}
                for item in result.artifacts
            ],
        },
        immutable_values={
            "output_identity": [
                {"external_id": item.external_id, "media_type": item.media_type}
                for item in result.artifacts
            ]
        },
        preserve_if={"provider_state": "success"},
    )
    if not accepted["applied"]:
        return
    call_id = as_dict(accepted["metadata"]).get("call_id")
    if call_id:
        await finish_media_call(UUID(str(call_id)), result)
    for ordinal, artifact in enumerate(result.artifacts):
        existing = await get_db().scalar(
            select(MediaOutputReceipt.id).where(
                MediaOutputReceipt.run_id == run_id,
                MediaOutputReceipt.ordinal == ordinal,
            )
        )
        if existing is not None:
            continue
        content = artifact.content
        if not content and artifact.url:
            content = (await read_public_https_bytes(artifact.url, max_bytes=100_000_000)).content
        if not content or len(content) > 100_000_000:
            raise ValueError("Generated media is empty or exceeds 100 MB.")
        signatures = {
            "audio/mpeg": content.startswith(b"ID3")
            or (len(content) >= 2 and content[0] == 255 and content[1] & 224 == 224),
            "audio/wav": content.startswith(b"RIFF") and content[8:12] == b"WAVE",
            "video/mp4": content[4:8] == b"ftyp",
        }
        if not signatures.get(artifact.media_type, False):
            raise ValueError("Provider output does not match its declared media container.")
        await get_db().execute(
            insert(MediaOutputReceipt)
            .values(
                run_id=run_id,
                ordinal=ordinal,
                external_id=artifact.external_id,
                media_type=artifact.media_type,
                content=content,
            )
            .on_conflict_do_nothing(
                index_elements=[MediaOutputReceipt.run_id, MediaOutputReceipt.ordinal]
            )
        )
        await get_db().commit()
    await engine_checkpoint(
        run_id,
        "multimedia",
        {
            "submission": "accepted",
            "provider_state": "success",
            "output_count": len(result.artifacts),
            "cost": result.cost,
        },
    )
