"""Lazy attachment ingestion: download, cache, and content extraction.

This logic belongs to the application layer, never to a messaging bridge. A bridge only exposes
``fetch_attachment(attachment) -> bytes``. This module turns those bytes into content usable by
non-multimodal agents. Missing extractors degrade to an informative description instead of
failing the whole agent run.
"""

from __future__ import annotations

import base64
import asyncio
import io
import sys
from pathlib import Path
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from loguru import logger

from app.messenger.facade import MessengerFacade
from app.messenger.models import (
    AUDIO_TRANSCRIPT_METADATA_KEY,
    File,
    Message,
    conversation_audio_transcripts,
)
from core.database import get_db
from core.params import runtime_settings
from core.i18n import default_language, is_supported, render_prompt, t

if TYPE_CHECKING:
    from app.llm import MediaCaps

# Maximum retained or returned extracted text length, in characters.
_MAX_TEXT_CHARS = 20_000
# Bounded transient LRU caches for raw bytes and extracted text.
_CACHE_MAXLEN = 64
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_PDF_MAX_BYTES = 16 * 1024 * 1024
_pdf_slots = asyncio.Semaphore(2)
_bytes_cache: "OrderedDict[str, bytes]" = OrderedDict()
_text_cache: "OrderedDict[str, str]" = OrderedDict()


def _key(messenger: MessengerFacade, att: File) -> str:
    return f"{messenger.tool_id}:{att.id}"


def _cache_put(cache: "OrderedDict[str, object]", key: str, value: object) -> None:
    def size(item: object) -> int:
        return len(item) if isinstance(item, bytes) else len(str(item).encode("utf-8"))

    cache.pop(key, None)
    if size(value) > _CACHE_MAX_BYTES:
        return
    cache[key] = value
    cache.move_to_end(key)
    total = sum(size(item) for item in cache.values())
    while len(cache) > _CACHE_MAXLEN or total > _CACHE_MAX_BYTES:
        _, removed = cache.popitem(last=False)
        total -= size(removed)


def _language(language: str | None) -> str:
    normalized = (language or "").strip().lower()
    return normalized if is_supported(normalized) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_ingest.{key}", language), **values)


def describe(att: File, language: str | None = None) -> str:
    """Return a short localized attachment description without downloading it."""
    lang = _language(language)
    size = (
        f", {_message(lang, 'bytes', count=att.size_bytes)}"
        if att.size_bytes
        else ""
    )
    name = att.name or att.external_identifier or f"({_message(lang, 'unnamed')})"
    return f"{name} [{att.kind}/{att.mime_type or '?'}{size}]"


async def fetch_bytes(messenger: MessengerFacade, att: File) -> bytes:
    """Download attachment bytes through the bridge on demand and cache them."""
    key = _key(messenger, att)
    cached = _bytes_cache.get(key)
    if cached is not None:
        _bytes_cache.move_to_end(key)
        return cached
    data = await messenger.fetch_attachment(att)
    _cache_put(_bytes_cache, key, data)  # type: ignore[arg-type]
    return data


async def extract_text(
    messenger: MessengerFacade,
    att: File,
    language: str | None = None,
) -> str:
    """Extract or transcribe attachment text lazily and cache the localized result.

    Text, JSON, and CSV are decoded directly. PDFs use ``pypdf`` when available. Images, audio,
    video, and other binary formats fall back to a localized description when no native or
    transcription path is available.
    """
    lang = _language(language)
    key = f"{_key(messenger, att)}:{lang}"
    cached = _text_cache.get(key)
    if cached is not None:
        _text_cache.move_to_end(key)
        return cached

    try:
        text = await _extract(messenger, att, lang)
    except Exception as exc:
        description = describe(att, lang)
        logger.exception("Messenger file extraction failed for {}", description)
        text = _message(lang, "unreadable_error", description=description, error=exc)

    text = text[:_MAX_TEXT_CHARS]
    _cache_put(_text_cache, key, text)  # type: ignore[arg-type]
    return text


async def _extract(messenger: MessengerFacade, att: File, language: str) -> str:
    mime = (att.mime_type or "").lower()

    if att.kind == "document" and (
        mime.startswith("text/") or mime in ("application/json",) or "csv" in mime
    ):
        data = await fetch_bytes(messenger, att)
        return data.decode("utf-8", errors="replace")

    if mime == "application/pdf" or att.name.lower().endswith(".pdf"):
        return await _extract_pdf(messenger, att, language)

    if att.kind == "audio":
        transcript = await _transcribe(messenger, att)
        if transcript:
            return transcript
        return _message(
            language,
            "transcription_unavailable",
            description=describe(att, language),
        )

    if att.kind in ("image", "video"):
        return _message(
            language,
            "binary_untranscribed",
            kind=att.kind,
            description=describe(att, language),
        )

    return _message(
        language,
        "binary_no_text",
        description=describe(att, language),
    )


async def _transcribe(
    messenger: MessengerFacade,
    att: File,
    *,
    agent_id: int | None = None,
) -> Optional[str]:
    """Transcribe an attachment through the shared provider-neutral service."""
    from sqlalchemy import select

    from app.connection import Connection
    from app.llm import transcription_service
    from core.database import get_db

    try:
        if agent_id is None:
            agent_id = await get_db().scalar(
                select(Connection.agent_id).where(
                    Connection.id == messenger.connection_id
                )
            )
        data = await fetch_bytes(messenger, att)
        return await transcription_service.transcribe_audio(
            data,
            filename=att.name or "audio",
            mime_type=att.mime_type or "audio/wav",
            agent_id=agent_id,
        )
    except Exception:
        logger.exception("Audio transcription failed ({})", describe(att, "en"))
        return None


async def transcribe_audio_for_conversation(
    message: Message,
    *,
    agent_id: int,
) -> bool:
    """Persist STT for each audio file when the conversation model cannot hear it.

    Failure is deliberately fail-open: the canonical audio remains available through its
    provider URI and ordinary conversation admission continues.
    """

    audio_files = [
        file
        for file in message.files
        if file.kind == "audio" or file.mime_type.lower().startswith("audio/")
    ]
    if not audio_files:
        return False

    from app.llm import llm_service, model_usages, supports_native_input, transcription_service
    from app.messenger.facade import get_messenger

    conversation_llm = await llm_service.get_profile_llm_for_agent_id(
        model_usages.CONVERSATION,
        agent_id,
    )
    if conversation_llm is None:
        return False
    audio_files = [file for file in audio_files if not (
        supports_native_input(conversation_llm, file.mime_type, file.name)
        and file.size_bytes is not None
        and 0 < file.size_bytes <= runtime_settings.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES
    )]
    if not audio_files:
        return False
    if not await transcription_service.transcription_available_for_agent(agent_id):
        return False

    transcripts = conversation_audio_transcripts(message.metadata_)
    pending = [file for file in audio_files if str(file.id) not in transcripts]
    if not pending:
        return False

    messenger = await get_messenger(message.connection_id)
    prepared = 0
    for file in pending:
        transcript = await _transcribe(messenger, file, agent_id=agent_id)
        if not transcript or not transcript.strip():
            continue
        transcripts[str(file.id)] = transcript.strip()[:_MAX_TEXT_CHARS]
        prepared += 1
    if not prepared:
        return False

    db = get_db()
    record = await db.get(Message, message.id)
    if record is None:
        logger.warning(
            "Could not persist audio transcription for missing Messenger message {}",
            message.id,
        )
        return False
    current_metadata = dict(record.metadata_ or {})
    current_transcripts = conversation_audio_transcripts(current_metadata)
    current_transcripts = {**transcripts, **current_transcripts}
    current_metadata[AUDIO_TRANSCRIPT_METADATA_KEY] = current_transcripts
    record.metadata_ = current_metadata
    message.metadata_ = dict(current_metadata)
    # The conversation facade wakes its scheduler from an independent session. Commit the
    # transcript first so even an immediately claimed round sees the enriched projection.
    await db.commit()
    logger.info(
        "Prepared {} audio transcription(s) for Messenger conversation message {}",
        prepared,
        message.id,
    )
    return True


async def _extract_pdf(messenger: MessengerFacade, att: File, language: str) -> str:
    if att.size_bytes and att.size_bytes > _PDF_MAX_BYTES:
        return _message(
            language,
            "pdf_unavailable",
            description=describe(att, language),
        )

    data = await fetch_bytes(messenger, att)
    if len(data) > _PDF_MAX_BYTES:
        return _message(language, "pdf_unavailable", description=describe(att, language))
    async with _pdf_slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("pdf_extract.py")),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(15):
                output, _ = await process.communicate(data)
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        if process.returncode != 0:
            return _message(language, "pdf_unavailable", description=describe(att, language))
    text = output.decode("utf-8", errors="replace")[:_MAX_TEXT_CHARS]
    return text or _message(
        language,
        "pdf_no_text",
        description=describe(att, language),
    )


async def as_prompt_block(
    messenger: MessengerFacade,
    files: list[File],
    include_images: bool = True,
    language: str | None = None,
) -> str:
    """Build a localized prompt block describing and extracting message attachments.

    This universal fallback lets non-multimodal agents inspect file contents. When images have
    already been sent as native multimodal content, ``include_images=False`` records their
    presence without extracting them again.
    """
    if not files:
        return ""
    lang = _language(language)
    lines: List[str] = ["", _message(lang, "attachments_heading")]
    for att in files:
        description = describe(att, lang)
        lines.append(f"### {description}")
        if att.kind == "image" and not include_images:
            lines.append(_message(lang, "image_native"))
            continue
        try:
            lines.append(await extract_text(messenger, att, lang))
        except Exception:
            logger.exception("Prompt attachment extraction failed for {}", description)
            lines.append(_message(lang, "unreadable_short", description=description))
    return "\n".join(lines)


def _audio_format(att: File) -> str:
    """Infer the OpenAI ``input_audio`` format from MIME type or filename extension."""
    from app.llm.transcription_service import audio_format

    return audio_format(att.mime_type or "", att.name or att.remote_url or "")


def _is_pdf(att: File) -> bool:
    return (att.mime_type or "").lower() == "application/pdf" or att.name.lower().endswith(".pdf")


def _image_part(data: bytes, mime: Optional[str]) -> Dict[str, Any]:
    """Build an OpenAI ``image_url`` part from raw bytes as a data URL."""
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"},
    }


async def pdf_to_images(
    messenger: MessengerFacade, att: File, max_pages: int = 10, dpi: int = 150
) -> List[Tuple[bytes, str]]:
    """Rasterize PDF pages to PNG for vision models without native file support.

    Scanned PDFs become ``image_url`` parts through ``pypdfium2`` and Pillow. Missing libraries
    or rendering failures return an empty list so callers can fall back to text extraction.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        logger.warning(
            "pypdfium2 is missing; PDF rasterization is unavailable ({})",
            describe(att, "en"),
        )
        return []

    data = await fetch_bytes(messenger, att)
    scale = dpi / 72.0
    out: List[Tuple[bytes, str]] = []
    try:
        pdf = pdfium.PdfDocument(data)
        try:
            for i in range(min(len(pdf), max_pages)):
                page: Any = pdf[i]
                pil = page.render(scale=scale).to_pil()
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                out.append((buf.getvalue(), "image/png"))
        finally:
            pdf.close()
    except Exception:
        logger.exception("PDF rasterization failed ({})", describe(att, "en"))
        return []
    return out


def _oversize(att: File) -> bool:
    """Return whether an attachment exceeds the inline-content threshold."""
    return bool(att.size_bytes and att.size_bytes > runtime_settings.MESSENGER_MAX_INLINE_MB * 1024 * 1024)


async def as_openai_content(
    messenger: MessengerFacade,
    files: list[File],
    text: str,
    caps: "MediaCaps",
    language: str | None = None,
) -> Union[str, List[Dict[str, Any]]]:
    """Build OpenAI message content according to the selected model's media capabilities.

    Accepted media is sent natively. Unsupported media falls back to transcription, PDF text
    extraction, PDF page rasterization, or a localized description. The result is a list of
    native parts when any media is accepted, and otherwise a text string.
    """
    if not files:
        return text

    lang = _language(language)
    media_parts: List[Dict[str, Any]] = []
    doc_blocks: List[str] = []
    for att in files:
        handled = False
        # Do not inline or eagerly extract oversized attachments. The agent can use its file
        # tools, and the request stays below upstream payload limits.
        if _oversize(att):
            description = describe(att, lang)
            doc_blocks.append(
                f"### {description}\n"
                + _message(
                    lang,
                    "oversize",
                )
            )
            continue
        try:
            if caps.image and att.kind == "image":
                data = await fetch_bytes(messenger, att)
                media_parts.append(_image_part(data, att.mime_type))
                handled = True
            elif caps.audio and att.kind == "audio":
                data = await fetch_bytes(messenger, att)
                b64 = base64.b64encode(data).decode("ascii")
                media_parts.append({
                    "type": "input_audio",
                    "input_audio": {"data": b64, "format": _audio_format(att)},
                })
                handled = True
            elif att.kind == "document" and caps.file:
                data = await fetch_bytes(messenger, att)
                b64 = base64.b64encode(data).decode("ascii")
                mime = att.mime_type or ("application/pdf" if _is_pdf(att) else "application/octet-stream")
                media_parts.append({
                    "type": "file",
                    "file": {
                        "filename": att.name or str(att.id),
                        "file_data": f"data:{mime};base64,{b64}",
                    },
                })
                handled = True
            elif att.kind == "document" and caps.image and _is_pdf(att):
                pages = await pdf_to_images(messenger, att)
                for data, mime in pages:
                    media_parts.append(_image_part(data, mime))
                handled = bool(pages)
        except Exception:
            logger.exception(
                "Native media preparation failed for {}",
                describe(att, "en"),
            )
        if handled:
            continue
        # Unsupported or failed native media falls back to extracted text or a description.
        description = describe(att, lang)
        try:
            doc_blocks.append(
                f"### {description}\n{await extract_text(messenger, att, lang)}"
            )
        except Exception:
            doc_blocks.append(
                f"### {description}\n{_message(lang, 'unreadable_content')}"
            )

    full_text = text
    if doc_blocks:
        full_text += f"\n\n{_message(lang, 'attachments_heading')}\n" + "\n".join(
            doc_blocks
        )
    if not media_parts:
        return full_text
    return [{"type": "text", "text": full_text}, *media_parts]


async def image_parts(
    messenger: MessengerFacade, files: list[File], max_images: int = 4
) -> List[Tuple[bytes, str]]:
    """Return image bytes and MIME types for a native multimodal executor.

    Protected attachment references are downloaded as bytes instead of exposed as public URLs.
    ``max_images`` bounds request size and cost.
    """
    parts: List[Tuple[bytes, str]] = []
    for att in files:
        if att.kind != "image":
            continue
        try:
            parts.append((await fetch_bytes(messenger, att), att.mime_type or "image/png"))
        except Exception:
            logger.exception("Image download failed for {}", describe(att, "en"))
        if len(parts) >= max_images:
            break
    return parts


def _reset_cache_for_tests() -> None:  # pyright: ignore[reportUnusedFunction]
    _bytes_cache.clear()
    _text_cache.clear()
