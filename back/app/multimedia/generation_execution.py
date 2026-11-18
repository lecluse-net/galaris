"""Domain-owned media generation with durable submission and delivery receipts."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.agent import validate_agent_driver
from app.file_share import ResourceContext, resource_create
from app.llm import MediaRequest, MediaResult, resolve_media_resource
from app.llm.facade import SelectedMediaResource, VideoFrameProvider, start_media_call, finish_media_call, MediaRequestRejected
from .generation_contracts import MediaGenerationError, MediaGenerationSnapshot
from .generation_store import generation_checkpoint
from core import settings
from core.database import get_db
from core.util import as_dict, buffered_io_budget

from .models import MediaOutputReceipt
from .provider_results import receive_result
from .checkpoints import MultimediaCheckpoint
from .service import authorize, validate_destination
from .video_frames import FrameInput, FrozenFrame, VideoFrameError, freeze_frames, load_frozen_frames


class MediaGenerationExecutor:
    refresh_timeout_seconds = 660.0

    async def prepare_input(
        self, agent_id: int, input_data: dict[str, Any], *, task_id: UUID | None = None,
    ) -> dict[str, Any]:
        request = MediaRequest.model_validate(input_data.get("request"))
        if request.operation not in {"sound_generate", "music_generate", "video_generate"}:
            raise ValueError("Only generation requests are accepted.")
        await authorize(agent_id, request.operation)
        selected = await resolve_media_resource(agent_id, request.operation)
        request = request.model_copy(update={"model": selected.model})
        selected.provider.validate(request)
        if selected.connection.catalog_code == "sunoapi":
            base = settings.APP_HOST
            if not base.startswith("https://"):
                raise ValueError("SunoAPI requires a public HTTPS Galaris callback base URL.")
        runtime = validate_agent_driver(input_data.get("runtime"), require_available=False)
        ctx = ResourceContext(agent_id, runtime, task_id)
        destination = await validate_destination(ctx, str(input_data.get("destination") or ""))
        payload: dict[str, Any] = {"request": request.model_dump(mode="json"), "llm_id": selected.llm_id,
                   "provider_id": selected.connection.id, "provider_code": selected.connection.catalog_code,
                   "provider_base_url": selected.connection.base_url, "destination": destination, "runtime": runtime}
        if raw_frames := input_data.get("frames"):
            if request.operation != "video_generate" or not isinstance(selected.provider, VideoFrameProvider):
                raise VideoFrameError("The selected provider does not support video frame references.")
            sources = tuple(FrameInput.model_validate(item) for item in raw_frames)
            if tuple(source.role for source in sources) not in {("first_frame",), ("first_frame", "last_frame")}:
                raise VideoFrameError("Provide the first frame before an optional last frame.")
            async with buffered_io_budget.reserve(160_000_000, owner=f"media:{agent_id}"):
                frames = await freeze_frames(ctx, sources)
            payload["frames"] = [frame.model_dump(mode="json") for frame in frames]
        return payload

    async def submit(self, generation_id: UUID) -> None:
        data = await generation_checkpoint(generation_id)
        async with buffered_io_budget.reserve(800_000_000, owner=f"media:{data['agent_id']}"):
            await self._submit(generation_id)

    async def _submit(self, generation_id: UUID) -> None:
        data = await generation_checkpoint(generation_id)
        metadata = MultimediaCheckpoint.model_validate(data["metadata"]).model_dump()
        if data["terminal"] or metadata.get("submission"):
            # A worker restart after admission never repeats a possibly billable POST.
            return
        frozen = as_dict(data["input"])
        request = MediaRequest.model_validate(frozen["request"])
        selected = await self._selected(data, request)
        agent_id = int(data["agent_id"])
        await authorize(agent_id, request.operation)
        selected.provider.validate(request)
        submit_with_frames = None
        frames = ()
        if raw_frames := frozen.get("frames"):
            if not isinstance(selected.provider, VideoFrameProvider):
                raise VideoFrameError("The admitted provider no longer supports video frame references.")
            submit_with_frames = selected.provider.submit_with_frames
            runtime = validate_agent_driver(frozen["runtime"], require_available=False)
            ctx = ResourceContext(agent_id, runtime, data.get("task_id"))
            frames = await load_frozen_frames(ctx, tuple(FrozenFrame.model_validate(item) for item in raw_frames))
            await authorize(agent_id, request.operation)
        claimed = await generation_checkpoint(generation_id, {"multimedia_version": 1}, claim="submission")
        if not claimed["claimed"]:
            return
        call_id = await start_media_call(selected, request, agent_id=agent_id,
                                        task_id=data.get("task_id"), media_generation_id=generation_id)
        await generation_checkpoint(generation_id, {"call_id": str(call_id)})
        base = settings.APP_HOST.rstrip("/")
        callback_url = f"{base}/multimedia/callback/{generation_id}/{data['callback_token']}"
        try:
            result = (
                await submit_with_frames(selected.connection, request, frames) if submit_with_frames is not None
                else await selected.provider.submit(selected.connection, request, callback_url=callback_url)
            )
        except MediaRequestRejected as exc:
            result = MediaResult("error", error=str(exc))
        except Exception as exc:
            # The connection can fail after acceptance, so do not repeat the POST.
            logger.warning("Media submission outcome unknown for {} ({})", generation_id, type(exc).__name__)
            await generation_checkpoint(generation_id, {"submission": "unknown"})
            await finish_media_call(call_id, MediaResult("unknown"))
            return
        await self._receive(generation_id, result)

    async def _selected(self, data: dict[str, Any], request: MediaRequest) -> SelectedMediaResource:
        frozen = as_dict(data["input"])
        selected = await resolve_media_resource(int(data["agent_id"]), request.operation, llm_id=int(frozen["llm_id"]))
        if (selected.connection.id != frozen["provider_id"]
                or selected.connection.catalog_code != frozen["provider_code"]
                or selected.connection.base_url != frozen["provider_base_url"]
                or selected.model != request.model):
            raise ValueError("The admitted provider resource was changed; automatic substitution is forbidden.")
        return selected

    async def _receive(self, run_id: UUID, result: MediaResult) -> None:
        await receive_result(run_id, result)

    async def advance(self, generation_id: UUID) -> MediaGenerationSnapshot:
        data = await generation_checkpoint(generation_id)
        async with buffered_io_budget.reserve(800_000_000, owner=f"media:{data['agent_id']}"):
            pending = await self._poll_run(generation_id)
        if pending is not None:
            return pending
        # One DB receipt and resource copies, plus the adapter's bounded upload.
        # The allowance is held globally before loading the receipt into memory.
        async with buffered_io_budget.reserve(200_000_000, child_bytes=300_000_000, owner=f"media:{data['agent_id']}"):
            return await self._deliver_run(generation_id)

    async def _poll_run(self, generation_id: UUID) -> MediaGenerationSnapshot | None:
        data = await generation_checkpoint(generation_id)
        metadata = MultimediaCheckpoint.model_validate(data["metadata"]).model_dump()
        frozen = as_dict(data["input"])
        request = MediaRequest.model_validate(frozen["request"])
        if metadata.get("provider_state") == "cancelled":
            return _remote_cancellation(metadata)
        if metadata.get("provider_state") == "error":
            return MediaGenerationSnapshot(status="error", error=MediaGenerationError(
                code="provider_rejected", message=str(metadata.get("provider_error") or "Generation failed.")))
        if metadata.get("provider_state") != "success":
            external_id = str(metadata.get("external_id") or "")
            if not external_id:
                return MediaGenerationSnapshot(status="unknown", error=MediaGenerationError(
                    code="submission_unknown", message="Provider admission could not be confirmed. No automatic resubmission."))
            selected = await self._selected(data, request)
            result = await selected.provider.poll(selected.connection, request, external_id)
            await self._receive(generation_id, result)
            latest = await generation_checkpoint(generation_id)
            observed = MultimediaCheckpoint.model_validate(latest["metadata"])
            if observed.provider_state == "cancelled":
                return _remote_cancellation(as_dict(latest["metadata"]))
            if observed.provider_state != "success":
                state = observed.provider_state or "unknown"
                return MediaGenerationSnapshot(status=state,
                    error=MediaGenerationError(code="provider_failed", message=str(as_dict(latest["metadata"]).get("provider_error") or "Generation failed")) if state == "error" else None)
        return None

    async def _deliver_run(self, generation_id: UUID) -> MediaGenerationSnapshot:
        data = await generation_checkpoint(generation_id)
        frozen = as_dict(data["input"])
        request = MediaRequest.model_validate(frozen["request"])
        receipts = list((await get_db().scalars(select(MediaOutputReceipt.id).where(
            MediaOutputReceipt.generation_id == generation_id,
        ).order_by(MediaOutputReceipt.ordinal))).all())
        if not receipts:
            raise ValueError("Completed generation has no durable output receipts.")
        runtime = validate_agent_driver(frozen["runtime"], require_available=False)
        ctx = ResourceContext(int(data["agent_id"]), runtime, data.get("task_id"))
        files: list[dict[str, Any]] = []
        for saved in receipts:
            receipt = (await get_db().scalars(select(MediaOutputReceipt).where(
                MediaOutputReceipt.id == saved,
            ).with_for_update().execution_options(populate_existing=True))).one()
            if receipt.uri is None:
                if receipt.delivery_started:
                    await get_db().commit()
                    return _uncertain_delivery()
                receipt.delivery_started = True
                receipt.delivery_attempts += 1
                receipt.delivery_lease_until = datetime.now(timezone.utc) + timedelta(seconds=self.refresh_timeout_seconds + 60)
                await get_db().commit()
                extension = {"video/mp4": "mp4", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(receipt.media_type, "bin")
                try:
                    mutation = await resource_create(ctx, frozen["destination"], receipt.content or b"",
                                                    name=f"{generation_id}-{receipt.ordinal}.{extension}", max_bytes=100_000_000)
                except Exception as exc:
                    logger.warning("Media delivery outcome unknown for {} ({})", generation_id, type(exc).__name__)
                    await get_db().rollback()
                    return _uncertain_delivery()
                receipt.uri = mutation.uri
                receipt.content = None
                receipt.delivery_lease_until = None
                await get_db().commit()
            files.append({"uri": receipt.uri, "media_type": receipt.media_type, "external_id": receipt.external_id})
        latest = await generation_checkpoint(generation_id)
        cost = as_dict(latest["metadata"]).get("cost")
        output: dict[str, Any] = {"files": files, "model": request.model,
                  "cost": cost, "cost_quality": "exact" if cost is not None else "unknown"}
        if raw_frames := frozen.get("frames"):
            output["reference_frames"] = [FrozenFrame.model_validate(frame).model_dump(exclude={"uri"})
                                          for frame in raw_frames]
        return MediaGenerationSnapshot(status="success", output=output)

    async def cancel(self, generation_id: UUID) -> MediaGenerationSnapshot:
        raise ValueError("The media provider does not confirm cancellation.")


def _uncertain_delivery() -> MediaGenerationSnapshot:
    return MediaGenerationSnapshot(status="unknown", error=MediaGenerationError(
        code="delivery_unknown", message="File creation was interrupted. Check the destination before retrying delivery."))


def _remote_cancellation(metadata: dict[str, Any]) -> MediaGenerationSnapshot:
    cost = metadata.get("cost")
    return MediaGenerationSnapshot(status="cancelled", output={
        "cost": cost, "cost_quality": "exact" if cost is not None else "unknown",
    })
