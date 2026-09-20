"""Build current-message content sent to the Hermes runtime."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from loguru import logger

from app.agent.contracts import AgentRunRequest
from app.messenger import File
from app.agent.contracts import TaskMessage

# Hermes transport supports text and images reliably. Audio, file, and video content use
# Galaris local fallbacks even when the underlying model supports those modalities.
_HERMES_TRANSPORT_MODALITIES = frozenset({"text", "image"})


async def current_content(task: AgentRunRequest, messenger: Any | None, text: str) -> Any:
    """Return multimodal parts or enriched text for the current Hermes message."""
    if messenger is None or not isinstance(task.data, dict):
        return text
    try:
        current = TaskMessage.model_validate(task.data)
    except Exception:
        return text
    if not current.file_ids:
        return text

    from sqlalchemy import select

    from core.database import get_db

    rows = list(
        (
            await get_db().scalars(
                select(File).where(
                    File.id.in_(current.file_ids)
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    files = [by_id[file_id] for file_id in current.file_ids if file_id in by_id]
    if not files:
        return text

    from app.llm import caps_for_llm, get_vision_llm, llm_service
    from app.messenger import as_openai_content

    llm = await llm_service.get_llm(task.model.id)

    # Intersect model capabilities with Hermes transport capabilities.
    allow = _HERMES_TRANSPORT_MODALITIES
    model_caps = caps_for_llm(llm)
    caps = replace(
        model_caps,
        image=model_caps.image and "image" in allow,
        file=model_caps.file and "file" in allow,
        video=model_caps.video and "video" in allow,
        audio=model_caps.audio and "audio" in allow,
    )

    # Hermes may route image understanding through its configured auxiliary vision model.
    has_image = any(file.kind == "image" for file in files)
    if "image" in allow and has_image and not caps.image:
        vision_llm = await get_vision_llm(
            exclude_llm_id=llm.id if llm else None,
            agent_id=task.agent.id,
        )
        if vision_llm is not None:
            caps = replace(caps, image=True)
            logger.info(
                "Hermes: image transport enabled through auxiliary vision model {}",
                vision_llm.llm_name,
            )
    return await as_openai_content(
        messenger,
        files,
        text,
        caps,
        language=str(task.task_data.get("language") or ""),
    )
