"""Project authorized per-attempt media into Claude's user message blocks."""

from base64 import b64encode
from collections.abc import Sequence
from typing import Any

from pydantic_ai import BinaryContent

from app.agent.contracts import TaskMessage
from app.file_share import ResourceContext
from app.llm import LLM

from .media import message_native_parts, prepare_native_inputs


TRANSIENT_MEDIA_PREFIX = "\n\n[Galaris media for this attempt]\n"
TRANSIENT_MEDIA_TYPES = frozenset({"image", "document"})


def _accepts_native(mime: str) -> bool:
    return mime.startswith("image/") or mime == "application/pdf"


async def claude_media_blocks(
    model: LLM, ctx: ResourceContext, current: Sequence[TaskMessage], history: Sequence[TaskMessage], *,
    prompt: str, system_prompt: str, tools: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not any(message.resource_references for message in (*current, *history)):
        return []
    inputs = await prepare_native_inputs(model, ctx, current, history, prompt=prompt, system_prompt=system_prompt,
                                         tools=tools, transport_accepts=_accepts_native)
    blocks: list[dict[str, Any]] = []
    for label, messages in (("Historical message", history), ("Current message", current)):
        for message in messages:
            parts = message_native_parts(message, inputs)
            if parts:
                blocks.append({"type": "text", "text": f"{TRANSIENT_MEDIA_PREFIX}{label} attachments:\n"})
            for part in parts:
                if isinstance(part, str):
                    blocks.append({"type": "text", "text": f"{TRANSIENT_MEDIA_PREFIX}{part}\n"})
                elif isinstance(part, BinaryContent) and _accepts_native(part.media_type):
                    blocks.append({
                        "type": "document" if part.media_type == "application/pdf" else "image",
                        "source": {"type": "base64", "media_type": part.media_type, "data": b64encode(part.data).decode("ascii")},
                    })
    return blocks
