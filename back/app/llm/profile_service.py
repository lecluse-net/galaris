"""Service for LLM configuration profiles.

A profile is one row of the column-based ``llm_profiles`` table: text usages
share four tiers while specialized capabilities keep dedicated columns.
Editing a profile writes its columns directly — every profile is always
editable, whether or not it is the active one. The active profile is tracked by
the ``llm_profile_id`` global parameter; browsing a profile never mutates the
pointer.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, select

from core.database import get_db
from core.i18n import render_prompt, tr
from core.params import params_service
from core.params.consts import Params
from . import model_usages
from .profile_models import (
    LlmProfile,
    PROFILE_MODEL_FIELDS,
    PROFILE_REASONING_FIELDS,
)
from .provider_facade import ReasoningEffort
from .reasoning import normalize_reasoning_effort
from .embedding_events import notify_embedding_change

DEFAULT_PROFILE_LABEL = "Défaut"


class LastProfileDeletionError(ValueError):
    """Raised when deleting the last remaining profile, which is forbidden."""


async def _profile_message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"llm_api.errors.{key}"), **values)


async def _reconcile_if_vector_configured(profile: LlmProfile) -> None:
    """Queue an embedding reconciliation when an effective profile has a vector.

    Replaces the removed global model-setting listener: the effective
    embedding model now changes through the profiles, so profile mutations
    trigger registered consumers instead, without importing their domains.
    """
    if profile.vector_llm_id is None:
        return
    await notify_embedding_change()


async def list_profiles() -> list[LlmProfile]:
    """Return every profile ordered by creation."""
    db = get_db()
    return list(
        (
            await db.execute(select(LlmProfile).order_by(LlmProfile.id))
        ).scalars().all()
    )


async def get_profile(profile_id: int) -> Optional[LlmProfile]:
    """Return one profile."""
    db = get_db()
    return (
        await db.execute(
            select(LlmProfile).where(LlmProfile.id == profile_id)
        )
    ).scalar_one_or_none()


async def get_profile_value(profile_id: int, model_field: str) -> Optional[str]:
    """Return one model value of a profile, or ``None`` when not configured."""
    db = get_db()
    column = getattr(LlmProfile, model_field)
    value = (
        await db.execute(
            select(column).where(LlmProfile.id == profile_id)
        )
    ).scalar_one_or_none()
    return str(value) if value is not None else None


async def get_agent_profile_value(agent: Any, model_field: str) -> Optional[str]:
    """Return one value from the agent's single effective profile.

    A null ``profile_id`` means the current profile. A custom profile is never
    mixed with the current one when one of its usage columns is empty.
    """
    profile_id = getattr(agent, "profile_id", None) if agent is not None else None
    if profile_id is None:
        profile_id = await get_current_profile_id()
    if profile_id is None:
        return None
    return await get_profile_value(profile_id, model_field)


async def get_agent_reasoning_effort(
    agent: Any,
    model_field: str,
) -> ReasoningEffort | None:
    """Return the configured reasoning paired with one text-model tier."""

    from .model_usages import reasoning_field_for_text_tier

    reasoning_field = reasoning_field_for_text_tier(model_field)
    if reasoning_field is None:
        return None
    value = await get_agent_profile_value(agent, reasoning_field)
    return normalize_reasoning_effort(value)


async def get_profile_reasoning_effort(
    profile_id: int,
    model_field: str,
) -> ReasoningEffort | None:
    """Return one profile's reasoning value for a text-model tier."""

    from .model_usages import reasoning_field_for_text_tier

    reasoning_field = reasoning_field_for_text_tier(model_field)
    if reasoning_field is None:
        return None
    value = await get_profile_value(profile_id, reasoning_field)
    return normalize_reasoning_effort(value)


async def get_current_profile_id() -> Optional[int]:
    """Return the id of the active profile, or ``None`` when unset.

    The value is a free-form string in the ``params`` table; an unset, blank,
    or unparseable value resolves to ``None`` without raising.
    """
    raw = await params_service.get(Params.LLM_PROFILE_ID)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        logger.debug(
            "Ignoring unparseable current-profile parameter '{}'", raw
        )
        return None


async def set_current_profile_id(profile_id: int) -> bool:
    """Point the current-profile parameter at ``profile_id``.

    Returns ``False`` without raising when the parameter row is not declared
    (defensive: ``sync()`` normally runs before the profile seeding).
    """
    ok = await params_service.set(Params.LLM_PROFILE_ID, str(profile_id))
    if not ok:
        logger.warning(
            "Cannot set current-profile parameter '{}' to {}: row not declared",
            Params.LLM_PROFILE_ID,
            profile_id,
        )
    return ok


async def seed_current_profile_id(profile_id: int) -> bool:
    """Set the current profile once, when no profile is active yet."""
    if await get_current_profile_id() is not None:
        return False
    return await set_current_profile_id(profile_id)


async def get_current_profile_value(model_field: str) -> Optional[str]:
    """Return one value of the current profile, or ``None`` when unconfigured."""
    profile_id = await get_current_profile_id()
    if profile_id is None:
        return None
    return await get_profile_value(profile_id, model_field)


async def has_current_profile_value(model_field: str) -> bool:
    """Return whether the current profile configures ``model_field``."""
    return await get_current_profile_value(model_field) is not None


async def has_any_profile_value(model_field: str) -> bool:
    """Return whether at least one profile configures an LLM usage."""
    db = get_db()
    column = getattr(LlmProfile, model_field)
    return (
        await db.execute(select(LlmProfile.id).where(column.is_not(None)).limit(1))
    ).scalar_one_or_none() is not None


async def _validate_label(label: str, exclude_id: Optional[int] = None) -> str:
    """Normalize a label and reject empty, oversized, or duplicate values."""
    value = label.strip()
    if not value:
        raise ValueError(await _profile_message("profile_label_required"))
    if len(value) > 100:
        raise ValueError(await _profile_message("profile_label_too_long"))

    db = get_db()
    query = select(LlmProfile.id).where(LlmProfile.label == value)
    if exclude_id is not None:
        query = query.where(LlmProfile.id != exclude_id)
    if (await db.execute(query.limit(1))).scalar_one_or_none() is not None:
        raise ValueError(await _profile_message("profile_label_in_use", label=value))
    return value


async def _validate_profile_values(values: dict[str, Optional[str]]) -> None:
    """Validate profile field names and stored model identifiers."""
    from . import llm_service

    for model_field, raw_value in values.items():
        if model_field == "decision_fallback_policy":
            if raw_value not in {"text_on_failure", "disabled"}:
                raise ValueError("Invalid decision fallback policy.")
            continue
        if model_field in PROFILE_REASONING_FIELDS:
            if raw_value is None or not raw_value.strip():
                continue
            if normalize_reasoning_effort(raw_value, strict=False) is None:
                raise ValueError(
                    await _profile_message(
                        "profile_value_invalid",
                        parameter=model_field,
                        value=raw_value.strip(),
                    )
                )
            continue
        if model_field not in PROFILE_MODEL_FIELDS:
            raise ValueError(
                await _profile_message(
                    "profile_param_invalid", parameter=model_field
                )
            )
        if raw_value is None or not raw_value.strip():
            continue
        value = raw_value.strip()
        try:
            llm_id = int(value)
        except ValueError as e:
            raise ValueError(
                await _profile_message(
                    "profile_value_invalid", parameter=model_field, value=value
                )
            ) from e
        resource = await llm_service.get_llm(llm_id)
        generation_capability = {
            **{field: "chat" for field in model_usages.TEXT_TIERS},
            "decision_llm_id": "decision",
            "sound_generation_llm_id": "sound_generation",
            "music_generation_llm_id": "music_generation",
            "video_generation_llm_id": "video_generation",
        }.get(model_field)
        if resource is None or (generation_capability is not None and generation_capability not in {
            resource.primary_capability, *resource.service_capabilities,
        }):
            raise ValueError(
                await _profile_message(
                    "profile_value_invalid", parameter=model_field, value=value
                )
            )


async def create_profile(label: str) -> LlmProfile:
    """Create a profile; values are added afterwards via update."""
    label = await _validate_label(label)
    db = get_db()
    profile = LlmProfile(label=label)
    db.add(profile)
    await db.flush()
    profile_id = profile.id
    await db.commit()
    created = await get_profile(profile_id)
    assert created is not None  # just inserted above
    return created


async def update_profile(
    profile_id: int,
    label: Optional[str] = None,
    values: Optional[dict[str, Optional[str]]] = None,
) -> Optional[LlmProfile]:
    """Rename a profile and/or write its model columns.

    A value of ``None`` (or blank) clears the model column so the usage has no
    model selected. Returns ``None`` when the profile does not exist.
    """
    profile = await get_profile(profile_id)
    if profile is None:
        return None

    db = get_db()
    old_vector = profile.vector_llm_id

    if label is not None:
        profile.label = await _validate_label(label, exclude_id=profile_id)

    if values is not None:
        await _validate_profile_values(values)
        for model_field, raw_value in values.items():
            if model_field == "decision_fallback_policy":
                profile.decision_fallback_policy = str(raw_value)
                continue
            if raw_value is None or not raw_value.strip():
                setattr(profile, model_field, None)
                continue
            value = raw_value.strip()
            if model_field in PROFILE_REASONING_FIELDS:
                normalized_effort = normalize_reasoning_effort(value, strict=True)
                assert normalized_effort is not None
                setattr(profile, model_field, normalized_effort)
                continue
            setattr(
                profile,
                model_field,
                int(value),
            )

    await db.commit()

    # An embedding-model change on the *current* profile changes the effective
    # embedding model: queue the reconciliation job the removed global setting
    # listener used to trigger.
    vector_changed = old_vector != profile.vector_llm_id
    if vector_changed and profile.vector_llm_id is not None and (
        await get_current_profile_id() == profile_id
    ):
        await _reconcile_if_vector_configured(profile)

    return await get_profile(profile_id)


async def delete_profile(profile_id: int) -> bool:
    """Delete a profile and let its agents follow the current profile.

    Deleting the last profile is forbidden. Returns ``False`` when the profile
    does not exist.
    """
    db = get_db()

    profile = (
        await db.execute(
            select(LlmProfile).where(LlmProfile.id == profile_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        return False

    count = (
        await db.execute(select(func.count()).select_from(LlmProfile))
    ).scalar_one()
    if count <= 1:
        raise LastProfileDeletionError(
            await _profile_message("last_profile_delete_forbidden")
        )

    was_current = await get_current_profile_id() == profile_id

    fallback_id = (
        await db.execute(
            select(LlmProfile.id)
            .where(LlmProfile.id != profile_id)
            .order_by(LlmProfile.id)
            .limit(1)
        )
    ).scalar_one()
    await db.delete(profile)
    await db.flush()

    # The deleted profile cannot stay current. Agents previously attached to it
    # are now NULL through the FK and therefore follow this replacement.
    if was_current:
        await set_current_profile_id(fallback_id)

    await db.commit()

    if was_current:
        fallback = await get_profile(fallback_id)
        if fallback is not None:
            await _reconcile_if_vector_configured(fallback)

    return True


async def use_profile(profile_id: int) -> int:
    """Make ``profile_id`` the current profile and return that id.

    Browsing never mutates anything; this function only moves the
    ``llm_profile_id`` pointer. The profile columns already carry the values,
    so there is nothing left to apply.
    """
    profile = await get_profile(profile_id)
    if profile is None:
        raise ValueError(
            await _profile_message("profile_not_found", profile_id=profile_id)
        )

    await set_current_profile_id(profile_id)
    await _reconcile_if_vector_configured(profile)
    return profile_id


async def ensure_default_profile_id() -> int:
    """Return an existing profile id, seeding the default when the table is empty."""
    db = get_db()
    profile_id = (
        await db.execute(
            select(LlmProfile.id)
            .where(LlmProfile.label == DEFAULT_PROFILE_LABEL)
            .order_by(LlmProfile.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if profile_id is None:
        profile_id = (
            await db.execute(
                select(LlmProfile.id)
                .order_by(LlmProfile.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if profile_id is None:
        profile = LlmProfile(label=DEFAULT_PROFILE_LABEL)
        db.add(profile)
        await db.flush()
        profile_id = profile.id
        await db.commit()
        logger.info(
            "Seeded the default LLM profile id={} '{}'",
            profile_id,
            DEFAULT_PROFILE_LABEL,
        )
    return int(profile_id)


async def ensure_default_profile() -> LlmProfile:
    """Seed a profile and the current-profile pointer. Idempotent."""
    profile_id = await ensure_default_profile_id()
    current_profile_id = await get_current_profile_id()
    if (
        current_profile_id is None
        or await get_profile(current_profile_id) is None
    ):
        await set_current_profile_id(profile_id)
    profile = await get_profile(profile_id)
    assert profile is not None  # seeded above when the table was empty
    return profile
