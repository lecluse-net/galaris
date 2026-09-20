"""Configured LLM management service."""

from dataclasses import dataclass
from typing import Any, Optional, List
from loguru import logger
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import ColumnElement

from core.database import get_db
from core.i18n import render_prompt, tr
from app.agent.models import Agent
from . import model_usages
from .profile_models import LlmProfile, PROFILE_MODEL_FIELDS
from .provider_models import LLM
from .provider_schemas import LLMCreate, LLMUpdate
from .provider_facade import ReasoningEffort


@dataclass(frozen=True)
class MediaCaps:
    """Native input modalities accepted directly by a model.

    These mirror :class:`LLM` ``input_*`` columns; documents and PDFs map to ``file``.
    """

    text: bool = True
    image: bool = False
    file: bool = False
    video: bool = False
    audio: bool = False


def caps_for_llm(llm: Optional[LLM]) -> MediaCaps:
    """Return input capabilities with a safe image-capable fallback for unknown models."""
    if llm is None:
        return MediaCaps(text=True, image=True)
    return MediaCaps(
        text=llm.input_text,
        image=llm.input_image,
        file=llm.input_file,
        video=llm.input_video,
        audio=llm.input_audio,
    )

# ==========================================================================
# Configured LLM CRUD
# ==========================================================================

async def _assert_llm_code_available(code: str, *, exclude_llm_id: int | None = None) -> None:
    db = get_db()
    query = select(LLM.id).where(LLM.code == code)
    if exclude_llm_id is not None:
        query = query.where(LLM.id != exclude_llm_id)
    existing = (await db.execute(query.limit(1))).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.code_in_use"),
                code=code,
            )
        )


async def create_llm(data: LLMCreate) -> LLM:
    """Create a configured LLM."""
    db = get_db()
    await _assert_llm_code_available(data.code)
    llm = LLM(
        llm_provider_id=data.llm_provider_id,
        code=data.code,
        llm_name=data.llm_name,
        label=data.label,
        resource_type=data.resource_type,
        primary_capability=data.primary_capability,
        service_capabilities=(
            list(dict.fromkeys([data.primary_capability, *data.service_capabilities]))
        ),
        pricing=data.pricing,
        context_length=data.context_length,
        cost_per_input_token=data.cost_per_input_token,
        cost_per_cached_input_token=data.cost_per_cached_input_token,
        cost_per_output_token=data.cost_per_output_token,
        is_subscription=data.is_subscription,
        input_text=data.input_text if data.input_text is not None else True,
        input_image=bool(data.input_image),
        input_file=bool(data.input_file),
        input_video=bool(data.input_video),
        input_audio=bool(data.input_audio),
        output_text=data.output_text if data.output_text is not None else True,
        output_image=bool(data.output_image),
        output_file=bool(data.output_file),
        output_video=bool(data.output_video),
        output_audio=bool(data.output_audio),
    )

    db.add(llm)
    await db.commit()
    await db.refresh(llm)
    return llm


async def get_llm(llm_id: int) -> Optional[LLM]:
    """Return an LLM by ID with provider information."""
    db = get_db()
    result = await db.execute(
        select(LLM).options(joinedload(LLM.provider)).where(LLM.id == llm_id)
    )
    return result.scalar_one_or_none()


async def get_llm_by_code(code: str) -> Optional[LLM]:
    """Return an LLM by stable code with provider information."""
    db = get_db()
    result = await db.execute(
        select(LLM)
        .options(joinedload(LLM.provider))
        .where(LLM.code == code)
    )
    return result.scalar_one_or_none()


async def get_llm_from_value(value: str, model_field: str) -> Optional[LLM]:
    """Resolve an LLM from a stored profile identifier."""
    try:
        llm_id = int(value)
        return await get_llm(llm_id)
    except ValueError as e:
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.invalid_profile_model_id"),
                model_field=model_field,
                value=value,
            )
        ) from e


async def get_profile_llm(model_field: str, *, agent: Any = None) -> Optional[LLM]:
    """Resolve a model from exactly one effective profile."""
    from . import profile_service

    value = await profile_service.get_agent_profile_value(agent, model_field)
    return await get_llm_from_value(value, model_field) if value is not None else None


async def get_profile_llm_for_agent_id(
    model_field: str,
    agent_id: int | None,
) -> Optional[LLM]:
    """Resolve one usage without loading the full Agent graph."""
    from . import profile_service

    if agent_id is None:
        return await get_profile_llm(model_field)
    row = (
        await get_db().execute(
            select(Agent.id, Agent.profile_id).where(
                Agent.id == agent_id,
                Agent.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    profile_id = row.profile_id
    if profile_id is None:
        return await get_profile_llm(model_field)
    value = await profile_service.get_profile_value(int(profile_id), model_field)
    return await get_llm_from_value(value, model_field) if value is not None else None


async def get_profile_reasoning_effort(
    model_field: str,
    *,
    agent: Any = None,
) -> ReasoningEffort | None:
    """Resolve the reasoning value paired with one text tier."""

    from . import profile_service

    return await profile_service.get_agent_reasoning_effort(agent, model_field)


async def get_profile_reasoning_effort_for_agent_id(
    model_field: str,
    agent_id: int | None,
) -> ReasoningEffort | None:
    """Resolve one tier's reasoning without loading the full Agent graph."""

    from . import profile_service

    if agent_id is None:
        return await get_profile_reasoning_effort(model_field)
    row = (
        await get_db().execute(
            select(Agent.id, Agent.profile_id).where(
                Agent.id == agent_id,
                Agent.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    if row.profile_id is None:
        return await get_profile_reasoning_effort(model_field)
    return await profile_service.get_profile_reasoning_effort(
        int(row.profile_id),
        model_field,
    )


async def get_llm_for_agent(agent: Any) -> Optional[LLM]:
    """Resolve an agent's LLM from its profile or the current profile.

    Centralized resolution ensures Hermes and media-capability wiring use the same source.
    """
    return await get_profile_llm(model_usages.EXECUTOR, agent=agent)


async def get_executor_llm_for_effort(agent: Any, effort: str = "standard") -> Optional[LLM]:
    """Resolve the executor LLM for standard or high effort.

    The high model of the agent's single effective profile may override its
    standard model for demanding work. Missing high configuration falls back
    only to the standard executor of that same profile.
    """
    if effort == "high":
        # Resolution stays inside the agent's single effective profile.
        high_llm = await get_profile_llm(model_usages.EXECUTOR_HIGH, agent=agent)
        if high_llm is not None:
            return high_llm
    return await get_llm_for_agent(agent)


async def get_executor_llm_for_task(task: Any) -> Optional[LLM]:
    """Return the executor LLM for a Galaris task."""
    effort = str(getattr(task, "effort", "standard") or "standard").strip().lower()
    return await get_executor_llm_for_effort(getattr(task, "agent", None), effort)


async def get_vision_llm(
    exclude_llm_id: Optional[int] = None,
    *,
    agent_id: int | None = None,
) -> Optional[LLM]:
    """Return the image-analysis model of the effective profile."""
    llm = await get_profile_llm_for_agent_id(model_usages.VISION, agent_id)
    if llm is None or llm.id == exclude_llm_id:
        return None
    if not llm.input_image or not llm.output_text:
        return None
    return llm


async def get_document_llm(
    exclude_llm_id: Optional[int] = None,
    *,
    agent_id: int | None = None,
) -> Optional[LLM]:
    """Return the native document-analysis model of the effective profile."""
    llm = await get_profile_llm_for_agent_id(model_usages.DOCUMENT, agent_id)
    if (
        llm is None
        or llm.id == exclude_llm_id
        or not llm.input_file
        or not llm.output_text
    ):
        return None
    return llm


async def get_audio_llm(
    exclude_llm_id: Optional[int] = None,
    *,
    agent_id: int | None = None,
) -> Optional[LLM]:
    """Return the native audio-understanding model of the effective profile."""
    llm = await get_profile_llm_for_agent_id(model_usages.AUDIO, agent_id)
    if (
        llm is None
        or llm.id == exclude_llm_id
        or not llm.input_audio
        or not llm.output_text
    ):
        return None
    return llm


async def get_video_llm(
    exclude_llm_id: Optional[int] = None,
    *,
    agent_id: int | None = None,
) -> Optional[LLM]:
    """Return the video-analysis model of the effective profile."""
    llm = await get_profile_llm_for_agent_id(model_usages.VIDEO, agent_id)
    if (
        llm is None
        or llm.id == exclude_llm_id
        or not llm.input_video
        or not llm.output_text
    ):
        return None
    return llm


async def get_image_llm(*, agent_id: int | None = None) -> Optional[LLM]:
    """Return the image-generation LLM of the effective profile.

    An image-output model is invoked on demand and is not used as an agent brain.
    """
    return await get_profile_llm_for_agent_id(model_usages.IMAGE, agent_id)


async def get_transcription_llm(agent_id: int | None = None) -> Optional[LLM]:
    """Return the audio transcription LLM of the effective profile.

    ``None`` means transcription is disabled.
    """
    return await get_profile_llm_for_agent_id(model_usages.TRANSCRIPTION, agent_id)


async def list_llms(
    provider_id: Optional[int] = None,
    capability: Optional[str] = None,
) -> List[LLM]:
    """List configured AI resources, optionally filtered by provider and capability."""
    db = get_db()
    query = select(LLM).options(joinedload(LLM.provider))

    if provider_id is not None:
        query = query.where(LLM.llm_provider_id == provider_id)

    query = query.order_by(LLM.label)

    result = await db.execute(query)
    resources = list(result.scalars().all())
    if capability is not None:
        resources = [
            resource
            for resource in resources
            if capability in resource.service_capabilities
        ]
    return resources


async def update_llm(llm_id: int, data: LLMUpdate) -> Optional[LLM]:
    """Update a configured LLM."""
    db = get_db()
    llm = await get_llm(llm_id)
    if not llm:
        return None

    update_data = data.model_dump(exclude_unset=True)

    if "code" in update_data:
        raw_code = update_data.get("code")
        if not raw_code:
            raise ValueError(await tr("llm_api.errors.code_required"))
        await _assert_llm_code_available(raw_code, exclude_llm_id=llm.id)

    primary_capability = str(
        update_data.get("primary_capability") or llm.primary_capability
    )
    if "service_capabilities" in update_data or "primary_capability" in update_data:
        capabilities = (
            [str(value) for value in data.service_capabilities]
            if data.service_capabilities is not None
            else list(llm.service_capabilities)
        )
        update_data["service_capabilities"] = list(
            dict.fromkeys([primary_capability, *capabilities])
        )

    for field, value in update_data.items():
        setattr(llm, field, value)

    await db.commit()
    await db.refresh(llm)
    return llm


async def delete_llm(llm_id: int) -> bool:
    """Soft-delete a configured LLM and detach its active configuration references."""
    llm = await get_llm(llm_id)
    if not llm:
        return False

    await _soft_delete_llms([llm])
    return True


async def soft_delete_provider_llms(provider_id: int) -> int:
    """Soft-delete every active LLM owned by a provider and commit the unit of work."""
    db = get_db()
    llms = list(
        (
            await db.execute(
                select(LLM).where(LLM.llm_provider_id == provider_id)
            )
        ).scalars().all()
    )
    await _soft_delete_llms(llms)
    return len(llms)


async def _soft_delete_llms(llms: list[LLM]) -> None:
    """Historize LLM rows and clear their profile and voice references."""
    db = get_db()
    llm_ids = {llm.id for llm in llms}
    if llm_ids:
        from .profile_models import UserLlmPreferences

        await db.execute(
            update(UserLlmPreferences)
            .where(UserLlmPreferences.voice_llm_id.in_(llm_ids))
            .values(voice_llm_id=None, voice_mode="tts", voice_code=None)
        )
        # Profiles pointing at deleted models are cleared column by column.
        # updated_at is bumped manually: the ORM onupdate does not apply to core
        # UPDATE statements.
        for column in PROFILE_MODEL_FIELDS:
            await db.execute(
                update(LlmProfile)
                .where(getattr(LlmProfile, column).in_(llm_ids))
                .values({column: None, "updated_at": func.now()})
            )

        voice_predicates: list[ColumnElement[bool]] = []
        for llm_id in llm_ids:
            voice_predicates.extend(
                (Agent.voice == f"tts:{llm_id}", Agent.voice.like(f"realtime:{llm_id}:%"))
            )
        await db.execute(
            update(Agent)
            .where(Agent.deleted_at.is_(None), or_(*voice_predicates))
            .values(voice=None)
        )

    for llm in llms:
        llm.soft_delete()

    await db.commit()
    if llm_ids:
        logger.info(
            "Soft-deleted {} LLM resource(s); cleared profile and voice references",
            len(llm_ids),
        )
