"""Internal image generation, editing, composition, and description service.

Configured image-output models produce or edit images. Vision models describe and analyze image
content. These specialized models are invoked on demand and never act as the agent's main model.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, cast
from uuid import UUID

from fastapi.responses import JSONResponse
from loguru import logger

from .schemas import ImageDimension, ImageGenerationOptions
from core.util import as_dict, as_list
from core.i18n import default_language, is_supported, render_prompt, t

from app.llm import LLM, LLMCallPurpose, generate_image_native, llm_service
from app.llm.facade import proxy_chat_completion

_DEFAULT_MIME = "image/png"


async def _resolve_llm_config(
    resolver: Callable[[], Awaitable[Optional[LLM]]],
    missing_key: str,
    language: str,
) -> tuple[str, str]:
    """Resolve an LLM outside an HTTP context and detach values from the DB session."""
    llm = await resolver()
    if llm is None:
        raise RuntimeError(t(f"image.{missing_key}", language))
    return llm.code, llm.llm_name


async def _proxy_completion_json(
    body: Dict[str, Any],
    model: str,
    kind: str,
    language: str,
    *,
    task_id: UUID | None = None,
    agent_id: int | None = None,
) -> Dict[str, Any]:
    response = await proxy_chat_completion(
        body,
        purpose=(
            LLMCallPurpose.IMAGE_ANALYSIS
            if kind == "vision"
            else LLMCallPurpose.IMAGE_GENERATION
        ),
        task_id=task_id,
        agent_id=agent_id,
        # Image generation and vision use explicitly configured specialist models. The task
        # remains correlated for supervision, but a high-effort executor must not replace them.
        route_executor_model=False,
    )
    if not isinstance(response, JSONResponse):
        raise RuntimeError(
            render_prompt(t("image.proxy_streaming_response", language), kind=kind)
        )
    raw = bytes(response.body)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            render_prompt(t("image.proxy_invalid_response", language), model=model)
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            render_prompt(t("image.proxy_non_object", language), model=model)
        )
    typed_payload = cast(Dict[str, Any], payload)
    if response.status_code >= 400:
        detail = str(typed_payload.get("error") or typed_payload)[:500]
        raise RuntimeError(
            render_prompt(
                t("image.provider_rejected", language),
                kind=kind,
                model=model,
                status=response.status_code,
                detail=detail,
            )
        )
    return typed_payload


def image_markdown(data: bytes, mime: Optional[str] = None) -> str:
    """Return an image as a Markdown data URL for transport-independent delivery."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"![image](data:{mime or _DEFAULT_MIME};base64,{b64})"


def _data_url_to_bytes(url: str) -> Optional[Tuple[bytes, str]]:
    """Decode ``data:<mime>;base64,<...>`` into bytes and MIME type."""
    if not url.startswith("data:"):
        return None
    try:
        header, b64 = url.split(",", 1)
        mime = header[5:].split(";", 1)[0] or _DEFAULT_MIME
        return base64.b64decode(b64), mime
    except (binascii.Error, ValueError):
        return None


def _extract_image(message: Dict[str, Any]) -> Optional[Tuple[bytes, str]]:
    """Extract the first image from an OpenAI/OpenRouter response message."""
    for img in as_list(message.get("images")):
        if isinstance(img, dict):
            got = _data_url_to_bytes(str(as_dict(as_dict(img).get("image_url")).get("url", "")))
            if got:
                return got
    content = message.get("content")
    if isinstance(content, list):
        for part in as_list(content):
            part_dict = as_dict(part)
            if part_dict.get("type") == "image_url":
                got = _data_url_to_bytes(str(as_dict(part_dict.get("image_url")).get("url", "")))
                if got:
                    return got
    return None


def _data_url(data: bytes, mime: Optional[str]) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime or _DEFAULT_MIME};base64,{b64}"


def _normalized_mime(mime: Optional[str]) -> str:
    """Return a lower-case MIME type without parameters."""
    return str(mime or "").partition(";")[0].strip().lower()


async def generate_image_bytes(
    prompt: str,
    sources: Optional[List[Tuple[bytes, str]]] = None,
    *,
    width: ImageDimension | None = None,
    height: ImageDimension | None = None,
    language: str | None = None,
    task_id: UUID | None = None,
    agent_id: int | None = None,
) -> Tuple[bytes, str]:
    """Generate, edit, or compose an image and return bytes plus MIME type."""
    options = ImageGenerationOptions(width=width, height=height)
    lang = language if is_supported(language) else default_language()
    model_code, model = await _resolve_llm_config(
        lambda: llm_service.get_image_llm(agent_id=agent_id),
        "generation_model_missing",
        lang,
    )
    if options.width is not None and options.height is not None:
        native = await generate_image_native(
            model_code, prompt, sources or [], width=options.width, height=options.height,
            agent_id=agent_id, task_id=task_id,
        )
        if native is not None:
            return native

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for data, mime in (sources or []):
        user_content.append({
            "type": "image_url",
            "image_url": {"url": _data_url(data, mime)},
        })

    body: Dict[str, Any] = {
        "model": model_code,
        "messages": [{"role": "user", "content": user_content}],
        # Image-only models such as Flux are rejected by OpenRouter when text is also
        # requested. The response extractor already treats textual content as optional.
        "modalities": ["image"],
    }
    payload = await _proxy_completion_json(
        body,
        model,
        "image",
        lang,
        task_id=task_id,
        agent_id=agent_id,
    )

    choices = as_list(payload.get("choices"))
    message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
    got = _extract_image(message)
    if got is None:
        logger.warning("generate_image: model {} returned no image", model)
        raise RuntimeError(t("image.model_returned_no_image", lang))
    return got


async def describe_image(
    data: bytes,
    mime: Optional[str] = None,
    instruction: str = "",
    *,
    language: str | None = None,
    task_id: UUID | None = None,
    agent_id: int | None = None,
) -> str:
    """Describe or analyze an image through the configured vision model."""
    lang = language if is_supported(language) else default_language()
    normalized_mime = _normalized_mime(mime)
    if not normalized_mime.startswith("image/"):
        raise RuntimeError(
            render_prompt(
                t("image.unsupported_analysis_mime", lang),
                mime=normalized_mime or "application/octet-stream",
            )
        )
    model_code, model = await _resolve_llm_config(
        lambda: llm_service.get_vision_llm(agent_id=agent_id),
        "vision_model_missing",
        lang,
    )

    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": instruction.strip() or t("image.default_description", lang)},
        {"type": "image_url", "image_url": {"url": _data_url(data, normalized_mime)}},
    ]
    body: Dict[str, Any] = {
        "model": model_code,
        "messages": [{"role": "user", "content": user_content}],
    }
    payload = await _proxy_completion_json(
        body,
        model,
        "vision",
        lang,
        task_id=task_id,
        agent_id=agent_id,
    )

    choices = as_list(payload.get("choices"))
    message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
    content = message.get("content")
    if isinstance(content, list):  # Some APIs return content parts.
        text = "".join(
            str(as_dict(part).get("text", "")) for part in as_list(content) if isinstance(part, dict)
        ).strip()
    else:
        text = str(content or "").strip()
    if not text:
        logger.warning("describe_image: vision model {} returned an empty response", model)
        raise RuntimeError(t("image.model_returned_no_description", lang))
    return text
