"""Document routing for Responses without changing the selected protocol or model."""

from copy import deepcopy
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse
from core.util import as_dict, as_list
from .document_input import Send, route_documents
from .provider_models import LLM


def has_response_documents(body: dict[str, Any]) -> bool:
    return any(as_dict(part).get("type") == "input_file"
               for item in as_list(body.get("input"))
               for part in as_list(as_dict(item).get("content")))


async def route_response_documents(body: dict[str, Any], llm: LLM, send: Send) -> JSONResponse | StreamingResponse:
    mapped = deepcopy(body)
    mapped.pop("input", None)
    messages: list[dict[str, Any]] = []
    for raw in as_list(body.get("input")):
        item = as_dict(raw)
        if not item.get("role"):
            # Tool/reasoning items have stateful semantics. Do not transform them.
            return await send(body)
        content = item.get("content")
        if isinstance(content, str):
            messages.append({"role": item["role"], "content": content})
            continue
        parts: list[dict[str, Any]] = []
        for value in as_list(content):
            part = as_dict(value)
            kind = part.get("type")
            if kind == "input_file":
                if not part.get("file_data"):
                    return await send(body)  # Provider-hosted IDs/URLs stay with their owner.
                parts.append({"type": "file", "file": {"filename": part.get("filename"), "file_data": part["file_data"]}})
            elif kind in {"input_text", "output_text"}:
                parts.append({"type": "text", "text": part.get("text", "")})
            elif kind == "input_image":
                parts.append({"type": "image_url", "image_url": {"url": part.get("image_url"), "detail": part.get("detail", "auto")}})
            else:
                return await send(body)
        messages.append({"role": item["role"], "content": parts})
    mapped["messages"] = messages

    async def response_send(payload: dict[str, Any]) -> JSONResponse | StreamingResponse:
        wire = deepcopy(payload)
        wire.pop("messages", None)
        inputs: list[dict[str, Any]] = []
        for message in as_list(payload.get("messages")):
            item = as_dict(message)
            content = item.get("content")
            if isinstance(content, str):
                inputs.append({"role": item["role"], "content": content})
                continue
            parts: list[dict[str, Any]] = []
            for value in as_list(content):
                part = as_dict(value)
                if part.get("type") == "text":
                    parts.append({"type": "input_text", "text": part["text"]})
                elif part.get("type") == "file":
                    parts.append({"type": "input_file", **as_dict(part["file"])})
                elif part.get("type") == "image_url":
                    image = as_dict(part["image_url"])
                    parts.append({"type": "input_image", "image_url": image["url"], "detail": image.get("detail", "high")})
            inputs.append({"role": item["role"], "content": parts})
        wire["input"] = inputs
        return await send(wire)

    return await route_documents(mapped, llm, response_send)
