"""Input and output file objects owned by the internal harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import Any
from collections.abc import Sequence
from tempfile import TemporaryDirectory

import anyio
from loguru import logger
from pydantic_ai import BinaryContent
from pydantic_ai.messages import UserContent

from app.agent.contracts import TaskMessage
from app.file_share import ResourceContext
from app.llm import LLM, normalized_media_type, supports_native_input
from app.llm.facade import document_input_budget, document_tokens, retrieve_prepared_document, text_tokens
from core.document import OFFICE_EXTENSIONS
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
    *, prompt: str = '', system_prompt: str = '', tools: Sequence[dict[str, Any]] = (),
) -> dict[str, NativeInput]:
    """Resolve authorized media once per run, current first, within one total byte budget.

    Canonical URIs remain in their original message. Temporary files disappear before
    inference; no provider URL, server path or global content cache reaches the agent.
    """
    from app.file_share import materialize_resource, resource_info

    remaining = runtime_settings.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES
    remaining_tokens = document_input_budget(llm.context_length, {
        'instructions': system_prompt,
        'tools': list(tools),
        'messages': [{'role': 'user', 'content': prompt or '\n'.join(message.text for message in current)},
                     *[{'role': 'user', 'content': message.text} for message in history]],
    })
    remaining_text = min(120_000, remaining_tokens * 3)
    remaining_resources = len({uri for message in [*current, *history] for uri in message.resource_references if uri})
    result: dict[str, NativeInput] = {}
    for message in [*current, *reversed(history)]:
        for uri in message.resource_references:
            if not uri or uri in result:
                continue
            try:
                # Resolve authoritative metadata and ACLs even for old/reopened messages.
                info = await resource_info(ctx, uri)
                mime = normalized_media_type(info.media_type, info.name)
                if (mime == 'application/pdf' or mime.startswith('text/') or Path(info.name).suffix.lower()
                    in OFFICE_EXTENSIONS | {'.pdf', '.md', '.html', '.htm', '.epub', '.txt', '.csv', '.tsv', '.json', '.xml'}):
                    document_input, used_tokens, used_bytes = await _prepare_document_input(
                        llm, ctx, message, uri, mime,
                        '\n'.join(item.text for item in current).strip() or prompt,
                        token_budget=remaining_tokens // max(1, remaining_resources), byte_budget=remaining,
                    )
                    remaining_tokens -= used_tokens
                    remaining_text = min(remaining_text, max(0, remaining_tokens * 3))
                    remaining -= used_bytes
                    if document_input is not None:
                        result[uri] = document_input
                        continue
                if remaining <= 0:
                    result[uri] = NativeInput(reason="native media byte budget exhausted")
                    continue
                if not supports_native_input(llm, mime):
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
            finally:
                remaining_resources -= 1
    return result


async def _prepare_document_input(
    llm: LLM, ctx: ResourceContext, message: TaskMessage, uri: str, mime: str, query: str,
    *, token_budget: int, byte_budget: int,
) -> tuple[NativeInput | None, int, int]:
    from app.file_share import document_rag_cache, prepared_resource, resource_info

    if token_budget < 256:
        return NativeInput(reason='document input budget exhausted by context, tools and output reserves'), 0, 0
    before = await resource_info(ctx, uri)
    fields = {'size', 'revision', 'checksum', 'etag', 'modified_at'}
    async with prepared_resource(ctx, uri) as (document, directory):
        required = document_tokens(document, visual=bool(llm.input_image))
        if required > token_budget or (supports_native_input(llm, mime) and before.size is not None and before.size > byte_budget):
            cache = await document_rag_cache(ctx, uri, document.sha256)
            selection = await retrieve_prepared_document(document, query, token_budget=token_budget, cache=cache)
            after = await resource_info(ctx, uri)
            if before.model_dump(include=fields) != after.model_dump(include=fields):
                raise ValueError('Document changed during retrieval')
            text = selection.text
            return NativeInput(owner=message, prepared_parts=(text,),
                               reason="RAG selected deterministically because the complete document exceeds available input capacity. "
                                      "For additional questions, call file_search on this exact URI with mode='semantic'"), text_tokens(text), 0
        if supports_native_input(llm, mime):
            return None, required, 0  # Preserve native file delivery when it fits.
        text = document.text()
        parts: list[UserContent] = [text]
        used_tokens, used_bytes, supplied, attempted = text_tokens(text), 0, 0, 0
        for page in document.pages:
            image = document.image_path(page, directory)
            if image is None:
                continue
            if attempted >= 8 or used_tokens + 4096 > token_budget:
                break
            if image.stat().st_size + used_bytes > byte_budget:
                continue
            attempted += 1
            image_data = await anyio.Path(image).read_bytes()
            used_bytes += len(image_data)
            if llm.input_image:
                parts.extend([f'[Physical page {page.number}]', BinaryContent(data=image_data, media_type='image/png')])
                used_tokens += 4096
                supplied += 1
            else:
                from app.agent import describe_input_image
                try:
                    description = await describe_input_image(image_data, 'image/png',
                        agent_id=ctx.agent_id, task_id=ctx.task_id, language=ctx.language)
                except Exception:
                    parts.append(f'[Page {page.number}: visual analysis unavailable; use the extracted text only]')
                    continue
                if not description.strip() or text_tokens(description) + used_tokens > token_budget:
                    parts.append(f'[Page {page.number}: visual analysis empty or exceeds inline text budget]')
                    continue
                used_tokens += text_tokens(description)
                parts.append(f'[Page {page.number} visual transcription]\n{description}')
                supplied += 1
        reason = f'{len(document.pages)} text pages; {supplied} pages supplied visually or as visual transcriptions'
        if supplied < sum(page.image is not None for page in document.pages):
            reason += ('; visual coverage incomplete, do not infer unseen figures. For questions requiring unread '
                       'visual pages or complete visual coverage, call document_analyze with this exact URI for resumable analysis')
        return NativeInput(owner=message, prepared_parts=tuple(parts), reason=reason), used_tokens, used_bytes


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
