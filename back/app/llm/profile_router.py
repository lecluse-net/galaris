"""API routes for LLM configuration profiles."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from loguru import logger

from core.authorize import Privileges, authorize
from core.i18n import render_prompt, tr
from . import profile_service
from .profile_models import (
    PROFILE_MODEL_FIELDS,
    PROFILE_REASONING_FIELDS,
    LlmProfile,
)
from .profile_schemas import (
    LlmProfileCreate,
    LlmProfileListResponse,
    LlmProfileOut,
    LlmProfileUpdate,
    LlmProfileUseResponse,
)
from .profile_service import LastProfileDeletionError

router = APIRouter(prefix="/llm-profiles", tags=["llm-profiles"])


async def _message(key: str, **values: Any) -> str:
    return render_prompt(await tr(f"llm_api.{key}"), **values)


async def _not_found(profile_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=await _message("errors.profile_not_found", profile_id=profile_id),
    )


def _profile_out(profile: LlmProfile) -> LlmProfileOut:
    return LlmProfileOut.model_validate(profile)


def _update_values(payload: LlmProfileUpdate) -> dict[str, str | None] | None:
    """Translate the explicitly provided columns into stored profile values.

    ``exclude_unset`` keeps the absent/None distinction: only the columns the
    client actually sent reach the service, where ``None`` clears that usage.
    """
    data = payload.model_dump(exclude_unset=True)
    explicit_columns = [
        column
        for column in (*PROFILE_MODEL_FIELDS, *PROFILE_REASONING_FIELDS, "decision_fallback_policy")
        if column in data
    ]
    if not explicit_columns:
        return None
    return {
        column: (
            str(data[column]) if data[column] is not None else None
        )
        for column in explicit_columns
    }


@router.get("", response_model=LlmProfileListResponse)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def list_profiles() -> LlmProfileListResponse:
    """List every profile for browsing without applying anything."""
    profiles = await profile_service.list_profiles()
    return LlmProfileListResponse(
        profiles=[_profile_out(profile) for profile in profiles],
        current_profile_id=await profile_service.get_current_profile_id(),
    )


@router.get("/{profile_id}", response_model=LlmProfileOut)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def get_profile(profile_id: int) -> LlmProfileOut:
    """Return one profile with its stored values."""
    profile = await profile_service.get_profile(profile_id)
    if profile is None:
        raise await _not_found(profile_id)
    return _profile_out(profile)


@router.post("", response_model=LlmProfileOut, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def create_profile(profile_create: LlmProfileCreate) -> LlmProfileOut:
    """Create a profile with a label; values are edited afterwards."""
    logger.info("Creating LLM profile '{}'", profile_create.label)
    try:
        profile = await profile_service.create_profile(profile_create.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _profile_out(profile)


@router.put("/{profile_id}", response_model=LlmProfileOut)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def update_profile(
    profile_id: int, profile_update: LlmProfileUpdate
) -> LlmProfileOut:
    """Rename a profile and/or set its model columns (explicit null clears)."""
    try:
        profile = await profile_service.update_profile(
            profile_id,
            label=profile_update.label,
            values=_update_values(profile_update),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if profile is None:
        raise await _not_found(profile_id)
    return _profile_out(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def delete_profile(profile_id: int) -> None:
    """Delete a profile. Deleting the last remaining profile is forbidden."""
    try:
        deleted = await profile_service.delete_profile(profile_id)
    except LastProfileDeletionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not deleted:
        raise await _not_found(profile_id)


@router.post(
    "/{profile_id}/use",
    response_model=LlmProfileUseResponse,
)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def use_profile(profile_id: int) -> LlmProfileUseResponse:
    """Make the profile the current one (pointer only, no value copy)."""
    try:
        current_id = await profile_service.use_profile(profile_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    logger.info("Activated LLM profile {}", profile_id)
    return LlmProfileUseResponse(
        profile_id=profile_id,
        current_profile_id=current_id,
    )
