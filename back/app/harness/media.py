"""Input and output file objects owned by the internal harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from collections.abc import Sequence
from tempfile import TemporaryDirectory

import anyio
from loguru import logger
from pydantic_ai import BinaryContent
from pydantic_ai.messages import UserContent

from app.agent.contracts import TaskMessage
from app.file_share import ResourceContext
from app.llm import LLM, normalized_media_type, supports_native_input
from core.params import runtime_settings


AgentFileKind = Literal["image", "audio", "video", "document", "other"]

@dataclass(frozen=True)
class AgentInputFile:
    """Local file staged for optional presentation through Pydantic AI's multimodal API."""

    path: Path
    media_type: str
    display_name: str
    agent_path: str
    kind: AgentFileKind = "other"


@dataclass(frozen=True)
class NativeInput:
    content: BinaryContent | None = None
    reason: str = ""
    owner: TaskMessage | None = None
    prepared_parts: tuple[UserContent, ...] = ()

    def parts(self, uri: str) -> list[UserContent]:
        if self.prepared_parts:
            return [f"[Prepared text for {uri}; {self.reason}]", *self.prepared_parts]
        if self.content is not None:
            return [f"[Native media for {uri}]", self.content]
        return [f"[Media not supplied natively: {uri}; {self.reason}. "
                "Use an available image_read, audio_transcribe, audio_read, video_read or "
                "file_read or document_analyze tool with this exact URI if needed. Do not infer unseen content.]"]


async def prepare_native_inputs(
    llm: LLM,
    ctx: ResourceContext,
    current: Sequence[TaskMessage],
    history: Sequence[TaskMessage],
) -> dict[str, NativeInput]:
    """Resolve authorized media once per run, current first, within one total byte budget.

    Canonical URIs remain in their original message. Temporary files disappear before
    inference; no provider URL, server path or global content cache reaches the agent.
    """
    from app.file_share import materialize_resource, resource_info

    remaining = runtime_settings.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES
    remaining_text = 120_000
    result: dict[str, NativeInput] = {}
    for message in [*current, *reversed(history)]:
        for uri in message.resource_references:
            if not uri or uri in result:
                continue
            if remaining <= 0:
                result[uri] = NativeInput(reason="native media byte budget exhausted")
                continue
            try:
                # Resolve authoritative metadata and ACLs even for old/reopened messages.
                info = await resource_info(ctx, uri)
                mime = normalized_media_type(info.media_type, info.name)
                if not supports_native_input(llm, mime):
                    if mime == "application/pdf" or info.name.lower().endswith(
                            (".doc", ".docx", ".odt", ".odg", ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods")):
                        from app.file_share import prepared_resource

                        async with prepared_resource(ctx, uri) as (document, directory):
                            text = document.text()
                            if len(text) > remaining_text:
                                result[uri] = NativeInput(reason=f"document prepared ({len(document.pages)} pages), but exceeds this run's inline text budget; call document_analyze with this exact URI for resumable document analysis")
                                continue
                            parts: list[UserContent] = [text]
                            remaining_text -= len(text)
                            supplied = 0
                            if llm.input_image:
                                for page in document.pages:
                                    image = document.image_path(page, directory)
                                    if image is None:
                                        continue
                                    if supplied >= 8 or image.stat().st_size > remaining:
                                        break
                                    image_data = await anyio.Path(image).read_bytes()
                                    remaining -= len(image_data)
                                    parts.extend([f"[Physical page {page.number}]", BinaryContent(data=image_data, media_type="image/png")])
                                    supplied += 1
                            else:
                                from app.agent import describe_input_image

                                attempted = 0
                                for page in document.pages:
                                    image = document.image_path(page, directory)
                                    if attempted >= 8:
                                        break
                                    if image is None or image.stat().st_size > remaining:
                                        continue
                                    attempted += 1
                                    try:
                                        image_data = await anyio.Path(image).read_bytes()
                                        remaining -= len(image_data)
                                        description = await describe_input_image(image_data, "image/png",
                                            agent_id=ctx.agent_id, task_id=ctx.task_id, language=ctx.language)
                                    except Exception:
                                        parts.append(f"[Page {page.number}: visual analysis unavailable; use the extracted text only]")
                                        continue
                                    if not description.strip() or len(description) > remaining_text:
                                        parts.append(f"[Page {page.number}: visual analysis empty or exceeds inline text budget]")
                                        continue
                                    remaining_text -= len(description)
                                    parts.append(f"[Page {page.number} visual transcription]\n{description}")
                                    supplied += 1
                            reason = f"{len(document.pages)} text pages; {supplied} pages supplied visually or as visual transcriptions"
                            if supplied < len(document.pages):
                                reason += "; visual coverage incomplete, do not infer unseen figures"
                            result[uri] = NativeInput(owner=message, prepared_parts=tuple(parts), reason=reason)
                        continue
                    if not mime.startswith(("image/", "audio/", "video/")):
                        result[uri] = NativeInput(reason="format unsupported by the selected model/transport")
                        continue
                if info.size is not None and info.size > remaining:
                    result[uri] = NativeInput(reason="file exceeds the remaining native media byte budget")
                    continue
                with TemporaryDirectory(prefix="galaris_input_") as directory:
                    path = Path(directory) / "input"
                    source = await materialize_resource(ctx, uri, path, max_bytes=remaining)
                    source_mime = normalized_media_type(source.media_type, source.name)
                    if source_mime != mime:
                        result[uri] = NativeInput(reason="resource format changed")
                        continue
                    size = path.stat().st_size
                    if size > remaining:
                        result[uri] = NativeInput(reason="file exceeds the remaining native media byte budget")
                        continue
                    remaining -= size
                    if not supports_native_input(llm, mime):
                        try:
                            text = await _analyze_input(path, mime, source.name, ctx)
                        except Exception:
                            result[uri] = NativeInput(reason="text analysis unavailable; no media content was supplied")
                            continue
                        if not text.strip():
                            result[uri] = NativeInput(reason="text analysis returned no content; media remains unseen")
                            continue
                        if len(text) > remaining_text:
                            result[uri] = NativeInput(reason="text analysis exceeds this run's inline text budget")
                            continue
                        remaining_text -= len(text)
                        result[uri] = NativeInput(owner=message, prepared_parts=(text,),
                            reason="analysis/transcription from a configured specialist; not native media")
                        continue
                    data = await anyio.Path(path).read_bytes()
                    result[uri] = NativeInput(owner=message, content=BinaryContent(
                        data=data, media_type=mime, identifier=uri,
                    ))
            except Exception:
                # Transport errors may contain signed URLs/credentials; keep the model notice generic.
                logger.warning("Native media unavailable for message {}", message.id)
                result[uri] = NativeInput(reason="resource unavailable or access denied")
    return result


def message_native_parts(message: TaskMessage, inputs: dict[str, NativeInput]) -> list[UserContent]:
    return [part for uri in message.resource_references if uri in inputs
            if inputs[uri].owner is None or inputs[uri].owner is message
            for part in inputs[uri].parts(uri)]


async def _analyze_input(path: Path, mime: str, name: str, ctx: ResourceContext) -> str:
    if mime.startswith("image/"):
        from app.agent import describe_input_image
        return await describe_input_image(await anyio.Path(path).read_bytes(), mime,
            agent_id=ctx.agent_id, task_id=ctx.task_id, language=ctx.language)
    if mime.startswith("audio/"):
        from app.llm import transcription_service
        return await transcription_service.transcribe_audio_file(path, filename=name,
            mime_type=mime, agent_id=ctx.agent_id, language=ctx.language or "")
    from app.llm.facade import analyze_input_video
    return await analyze_input_video(path, mime, agent_id=ctx.agent_id, task_id=ctx.task_id)
