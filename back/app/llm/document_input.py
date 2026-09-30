"""Document routing at the shared Chat protocol boundary, preserving call accounting."""

from __future__ import annotations

import base64
import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse

from core.document import PreparedDocument, prepare_document, page_images
from core.util import as_dict, as_list
from .provider_models import LLM

Send = Callable[[dict[str, Any]], Awaitable[JSONResponse | StreamingResponse]]
_MAX_INLINE_BYTES = 64 * 1024 * 1024
_BATCH_TEXT = 80_000
_BATCH_IMAGES = 8


def has_documents(body: dict[str, Any]) -> bool:
    return any(as_dict(part).get("type") == "file"
               for message in as_list(body.get("messages"))
               for part in as_list(as_dict(message).get("content")))


def _image(path: Path) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"), "detail": "high"}}


def _batch_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Only materialize the current batch, not every rendered page in memory.
    return [_image(Path(str(part["_galaris_image_path"])))
            if "_galaris_image_path" in part else part for part in parts]


def _visual_parts(path: Path, text: str) -> list[Path]:
    """Keep the whole page and magnified quadrants for image-dominated pages.

    Provider vision resizing can erase small handwritten digits even with high detail.
    These source-derived crops contain no inferred text and remain caller-local.
    """
    return page_images(path, text)


def _response_text(payload: dict[str, Any]) -> str | None:
    choices = as_list(payload.get("choices"))
    if choices:
        content = as_dict(as_dict(choices[0]).get("message")).get("content")
        return content if isinstance(content, str) else None
    texts = [str(as_dict(part).get("text", ""))
             for output in as_list(payload.get("output"))
             for part in as_list(as_dict(output).get("content"))
             if as_dict(part).get("type") == "output_text"]
    return "\n".join(texts) or None


def _usable(response: JSONResponse | StreamingResponse) -> bool:
    if not isinstance(response, JSONResponse):
        return True  # Never replay a live stream or a possibly delivered tool effect.
    if response.status_code >= 400:
        return False
    try:
        payload = as_dict(json.loads(bytes(response.body)))
        if payload.get("status") == "incomplete":
            return False
        choices = as_list(payload.get("choices"))
        message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
        content = _response_text(payload)
        if message.get("tool_calls") or any(as_dict(item).get("type") == "function_call" for item in as_list(payload.get("output"))):
            return True
        if not isinstance(content, str) or not content.strip():
            return False
        # Structured document readers must explicitly report missing/unreadable material.
        try:
            answers = as_list(as_dict(json.loads(content)).get("answers"))
        except ValueError:
            return True
        for answer in answers:
            limits = as_dict(answer).get("limitations")
            if isinstance(limits, list) and limits:
                return False
        return True
    except (ValueError, IndexError, TypeError):
        return False


def _document_rejection(response: JSONResponse) -> bool:
    if response.status_code in {413, 415}:
        return True
    if response.status_code not in {400, 422}:
        return False
    try:
        error = as_dict(json.loads(bytes(response.body))).get("error")
    except ValueError:
        return False
    details = json.dumps(error).lower()
    return bool(re.search(r"\b(?:file\w*|document\w*|mime\w*|pdf|context_length\w*)\b|context window", details))


def _annotate(response: JSONResponse | StreamingResponse, mode: str, pages: int,
              batches: int, reason: str = "") -> JSONResponse | StreamingResponse:
    response.headers["X-Galaris-Document-Mode"] = mode
    response.headers["X-Galaris-Document-Pages"] = str(pages)
    response.headers["X-Galaris-Document-Batches"] = str(batches)
    response.headers["X-Galaris-Document-Coverage"] = (
        "native-unverified" if mode.startswith("direct") else
        "partial" if mode.endswith("partial") or response.status_code >= 400 else "source-units-supplied")
    response.headers["X-Galaris-Document-Semantic-Verified"] = "false"
    if reason:
        response.headers["X-Galaris-Document-Fallback"] = reason
    return response


async def route_documents(body: dict[str, Any], llm: LLM, send: Send) -> JSONResponse | StreamingResponse:
    budget = body.get("galaris_document_max_calls", 64)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 64:
        return JSONResponse({"error": {"message": "Document call budget must be 1..64"}}, status_code=422)
    calls: list[str] = []
    count = 0
    async def measured(payload: dict[str, Any]) -> JSONResponse | StreamingResponse:
        nonlocal count
        for attempt in range(3):
            if count >= budget:
                return JSONResponse({"error": {"message": "Document inference budget exhausted; analysis incomplete"}}, status_code=429)
            count += 1
            response = await send(payload)
            call_id = response.headers.get("X-Galaris-LLM-Call-Id")
            if call_id:
                calls.append(call_id)
            # Retry only completed, read-only requests on transient upstream failure.
            # Streams, tool effects and authentication errors are never replayed.
            if (attempt == 2 or not isinstance(response, JSONResponse)
                    or response.status_code not in {502, 503, 504}
                    or payload.get("stream") or payload.get("tools") or payload.get("functions")):
                return response
            await asyncio.sleep(attempt + 1)
        raise AssertionError("Unreachable document retry state")
    response = await _route_documents(body, llm, measured)
    response.headers["X-Galaris-Document-Calls"] = str(count)
    if calls:
        response.headers["X-Galaris-Document-Call-Ids"] = ",".join(calls)
    return response


async def _route_documents(body: dict[str, Any], llm: LLM, send: Send) -> JSONResponse | StreamingResponse:
    """Prepare local inlined files once; retry only known document rejection/insufficiency.

    Conversion failures never turn into source-less guesses. Long prepared inputs use
    bounded non-streaming map/reduce calls; all source units are visited. This first stage
    is transient, not a durable resumable Process.
    """
    mode = body.get("galaris_document_mode", "auto")
    if mode not in {"auto", "direct", "prepared"}:
        return JSONResponse({"error": {"message": "Invalid document input mode"}}, status_code=422)
    clean = deepcopy(body)
    clean.pop("galaris_document_mode", None)
    clean.pop("galaris_document_max_calls", None)
    if mode == "direct":
        return _annotate(await send(clean), "direct", 0, 1)
    with TemporaryDirectory(prefix="galaris-documents-") as temporary:
        root = Path(temporary)
        prepared: list[tuple[PreparedDocument, Path]] = []
        native = deepcopy(clean)
        stripped = deepcopy(clean)
        native_possible = bool(llm.input_file)
        total_bytes = 0
        for message_index, raw_message in enumerate(as_list(clean.get("messages"))):
            message = as_dict(raw_message)
            content = as_list(message.get("content"))
            if not content:
                continue
            retained: list[dict[str, Any]] = []
            native_parts = as_list(as_dict(as_list(native["messages"])[message_index]).get("content"))
            for raw_part in content:
                part = as_dict(raw_part)
                if part.get("type") != "file":
                    retained.append(part)
                    continue
                file = as_dict(part.get("file"))
                data_url = file.get("file_data")
                if not isinstance(data_url, str) or not data_url.startswith("data:"):
                    return JSONResponse({"error": {"message": "Document preparation requires inlined file data; use authorized resource materialization"}}, status_code=422)
                if len(data_url) > _MAX_INLINE_BYTES * 4 // 3 + 256:
                    return JSONResponse({"error": {"message": "Document input exceeds inline budget"}}, status_code=413)
                if "," not in data_url:
                    return JSONResponse({"error": {"message": "Invalid document data URL"}}, status_code=422)
                header, encoded = data_url.split(",", 1)
                if not header.endswith(";base64"):
                    return JSONResponse({"error": {"message": "Invalid document data encoding"}}, status_code=422)
                try:
                    data = base64.b64decode(encoded, validate=True)
                except ValueError:
                    return JSONResponse({"error": {"message": "Invalid document base64"}}, status_code=422)
                total_bytes += len(data)
                if total_bytes > _MAX_INLINE_BYTES:
                    return JSONResponse({"error": {"message": "Document input exceeds inline budget"}}, status_code=413)
                directory = root / str(len(prepared))
                directory.mkdir()
                path = directory / "input"
                path.write_bytes(data)
                name = Path(str(file.get("filename") or "document")).name
                mime = header[5:-7]
                try:
                    document = await prepare_document(path, name, mime, directory)
                except ValueError:
                    return JSONResponse({"error": {"message": "Document conversion failed or format unsupported; no content was silently omitted"}}, status_code=422)
                prepared.append((document, directory))
                if document.converted or mime != "application/pdf":
                    native_possible = False
                # Native file plus cover preserves visually encoded titles which file
                # parsers can omit. Other pages remain available to prepared fallback.
                if llm.input_image and document.pages:
                    cover = document.image_path(document.pages[0], directory)
                    if cover:
                        native_parts.extend([{"type": "text", "text": f"[Rendered cover of {name}, page 1]"}, _image(cover)])
                retained.append({"type": "text", "text": f"[Document {name}; {len(document.pages)} source pages]"})
            as_dict(as_list(stripped["messages"])[message_index])["content"] = retained
        pages = sum(len(document.pages) for document, _ in prepared)
        reason = ""
        if mode == "auto" and native_possible:
            response = await send(native)
            if _usable(response):
                return _annotate(response, "direct-with-cover", pages, 1)
            if isinstance(response, JSONResponse) and response.status_code >= 400:
                if not _document_rejection(response):
                    return _annotate(response, "direct-with-cover", pages, 1)
                reason = "native-document-rejected"
            else:
                reason = "native-result-incomplete"
        elif mode == "auto":
            reason = "format-or-model-requires-preparation"

        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        size = images = 0
        for document, directory in prepared:
            if document.structured_text:
                for offset in range(0, len(document.structured_text), _BATCH_TEXT - 200):
                    batches.append([{"type": "text", "text": f"[Document {document.name}; structured source cells, independent of printed pages]\n" + document.structured_text[offset:offset + _BATCH_TEXT - 200]}])
            for page in document.pages:
                text = f"[Document {document.name}; physical page {page.number}]\n{page.text}"
                image = document.image_path(page, directory) if llm.input_image else None
                if current and (size + len(text) > _BATCH_TEXT or (image and images >= _BATCH_IMAGES)):
                    batches.append(current)
                    current = []
                    size = images = 0
                # A single dense page is split too; no unbounded unit reaches the provider.
                for offset in range(0, max(1, len(text)), _BATCH_TEXT):
                    if size + min(_BATCH_TEXT, len(text) - offset) > _BATCH_TEXT and current:
                        batches.append(current)
                        current = []
                        size = images = 0
                    piece = text[offset:offset + _BATCH_TEXT]
                    current.append({"type": "text", "text": piece})
                    size += len(piece)
                if image:
                    for detail_number, visual in enumerate(_visual_parts(image, page.text)):
                        label = f"[Document {document.name}; physical page {page.number}; " + (
                            "whole page]" if detail_number == 0 else f"detail quadrant {detail_number} (top-left, top-right, bottom-left, bottom-right order)]")
                        if current and (images >= _BATCH_IMAGES or size + len(label) > _BATCH_TEXT):
                            batches.append(current)
                            current = []
                            size = images = 0
                        current.extend([{"type": "text", "text": label}, {"_galaris_image_path": str(visual)}])
                        size += len(label)
                        images += 1
                elif page.image:
                    current.append({"type": "text", "text": "[Visual content is not supplied to this text-only model; extracted text and OCR do not prove that figures, annotations or handwriting were read. Report visual limitations.]"})
        if current:
            batches.append(current)
        if not batches:
            return JSONResponse({"error": {"message": "Document contains no readable units"}}, status_code=422)
        if len(batches) == 1:
            request = deepcopy(stripped)
            request["messages"].append({"role": "user", "content": _batch_parts(batches[0])})
            return _annotate(await send(request), "prepared", pages, 1, reason)
        if clean.get("tools"):
            return JSONResponse({"error": {"message": "Long document preparation requires a dedicated analysis request without tools"}}, status_code=422)
        # Do not emit partial streams while later batches can still fail.
        outputs: list[str] = []
        for number, batch in enumerate(batches, 1):
            request = deepcopy(stripped)
            request["stream"] = False
            request["messages"].append({"role": "user", "content": [
                {"type": "text", "text": f"Source batch {number}/{len(batches)}. Record relevant facts with source pages. Unavailable answers in this batch are not absence in the whole document. Preserve exact numbers and quotations for final consolidation."}, *_batch_parts(batch)]})
            response = await send(request)
            if not isinstance(response, JSONResponse) or response.status_code >= 400:
                return _annotate(response, "prepared-partial", pages, number, reason)
            try:
                payload = as_dict(json.loads(bytes(response.body)))
                output = _response_text(payload)
            except (ValueError, IndexError, TypeError):
                output = None
            if not isinstance(output, str) or not output.strip():
                return _annotate(JSONResponse({"error": {"message": "A document batch returned no text; analysis incomplete"}}, status_code=502), "prepared-partial", pages, number, reason)
            outputs.append(output)
        combined = "\n\n".join(outputs)
        if len(combined) > 500_000:
            return JSONResponse({"error": {"message": "Document consolidation exceeds budget; analysis incomplete"}}, status_code=413)
        request = deepcopy(stripped)
        request["messages"].append({"role": "user", "content": "Consolidate the following source-batch observations into the originally requested answer format. Preserve page citations and contradictions; do not invent missing facts. All source batches were visited. For each question, use the batches that contain its evidence. If one batch establishes the complete answer, discard other batches' caveats that merely say the answer is absent from their pages. Keep genuine uncertainty about the cited evidence or information missing from the entire document. Absence in a different batch is not an unresolved limitation of a complete answer.\n\n" + combined})
        return _annotate(await send(request), "prepared", pages, len(batches), reason)
